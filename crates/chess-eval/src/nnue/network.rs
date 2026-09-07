//! Deterministic integer network format and full-refresh scalar inference.
//!
//! NNUE-2 deliberately remains outside production search. A loaded network can evaluate a `Position`
//! from the proven sparse feature oracle, but no recursive search state uses it yet. This keeps file
//! compatibility, quantized arithmetic and model provenance testable before incremental accumulators
//! make the learned path hot.

pub mod accumulator;

use core::fmt;

use chess_core::{Color, Position};

use super::{FEATURE_COUNT, FEATURE_SET_ID, FeatureFrame, FeatureIndex, active_features};

const MAGIC: [u8; 8] = *b"CHNNUE1\0";
const FORMAT_VERSION: u16 = 1;
const FEATURE_ID_BYTES: usize = 32;
const HEADER_LEN: usize = 98;
const MAX_HIDDEN: usize = 128;
const MAX_ABS_WEIGHT: i16 = 4096;
const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;
const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;

/// Supported hidden widths for the first cost/strength ladder.
pub const SUPPORTED_HIDDEN: [usize; 3] = [32, 64, 128];

/// Parsed immutable integer network.
///
/// Heap allocation happens only when a network file is loaded. Full inference itself allocates no
/// heap memory, and NNUE-3 reuses the exact weight layout for incremental accumulators.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Network {
    hidden: usize,
    activation_max: i32,
    output_scale: i32,
    input_bias: Box<[i16]>,
    input_weights: Box<[i16]>,
    output_weights: Box<[i16]>,
    output_bias: i32,
    training_metadata_sha256: [u8; 32],
}

impl Network {
    /// Parse and validate one deterministic `CHNNUE1` network blob.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, NetworkError> {
        if bytes.len() < HEADER_LEN {
            return Err(NetworkError::Truncated);
        }
        if bytes[..MAGIC.len()] != MAGIC {
            return Err(NetworkError::BadMagic);
        }

        let mut cursor = MAGIC.len();
        let version = read_u16(bytes, &mut cursor)?;
        if version != FORMAT_VERSION {
            return Err(NetworkError::UnsupportedVersion(version));
        }

        let feature_id = read_array::<FEATURE_ID_BYTES>(bytes, &mut cursor)?;
        if feature_id != encoded_feature_id() {
            return Err(NetworkError::FeatureSetMismatch);
        }

        let feature_count = read_u32(bytes, &mut cursor)? as usize;
        if feature_count != FEATURE_COUNT {
            return Err(NetworkError::FeatureCountMismatch(feature_count));
        }

        let hidden = usize::from(read_u16(bytes, &mut cursor)?);
        if !SUPPORTED_HIDDEN.contains(&hidden) {
            return Err(NetworkError::UnsupportedHidden(hidden));
        }

        let activation_max = i32::from(read_i16(bytes, &mut cursor)?);
        if !(1..=127).contains(&activation_max) {
            return Err(NetworkError::InvalidActivationMax(activation_max));
        }

        let output_scale = read_i32(bytes, &mut cursor)?;
        if output_scale <= 0 {
            return Err(NetworkError::InvalidOutputScale(output_scale));
        }

        let payload_len = read_u32(bytes, &mut cursor)? as usize;
        let expected_payload = payload_len_for(hidden).ok_or(NetworkError::LengthOverflow)?;
        if payload_len != expected_payload {
            return Err(NetworkError::PayloadLengthMismatch {
                expected: expected_payload,
                actual: payload_len,
            });
        }

        let expected_checksum = read_u64(bytes, &mut cursor)?;
        let training_metadata_sha256 = read_array::<32>(bytes, &mut cursor)?;
        debug_assert_eq!(cursor, HEADER_LEN);

        let total_len = HEADER_LEN
            .checked_add(payload_len)
            .ok_or(NetworkError::LengthOverflow)?;
        if bytes.len() != total_len {
            return Err(NetworkError::BlobLengthMismatch {
                expected: total_len,
                actual: bytes.len(),
            });
        }

        let payload = &bytes[HEADER_LEN..];
        let actual_checksum = payload_checksum(payload);
        if actual_checksum != expected_checksum {
            return Err(NetworkError::PayloadChecksumMismatch {
                expected: expected_checksum,
                actual: actual_checksum,
            });
        }

        let mut payload_cursor = 0;
        let input_bias = read_i16_box(payload, &mut payload_cursor, hidden)?;
        let input_weight_count = FEATURE_COUNT
            .checked_mul(hidden)
            .ok_or(NetworkError::LengthOverflow)?;
        let input_weights = read_i16_box(payload, &mut payload_cursor, input_weight_count)?;
        let output_weights = read_i16_box(payload, &mut payload_cursor, hidden * 2)?;
        let output_bias = read_i32(payload, &mut payload_cursor)?;
        debug_assert_eq!(payload_cursor, payload.len());

        validate_weight_bound(&input_bias)?;
        validate_weight_bound(&input_weights)?;
        validate_weight_bound(&output_weights)?;

        Ok(Self {
            hidden,
            activation_max,
            output_scale,
            input_bias,
            input_weights,
            output_weights,
            output_bias,
            training_metadata_sha256,
        })
    }

    /// Hidden width of this network.
    #[must_use]
    pub const fn hidden(&self) -> usize {
        self.hidden
    }

    /// Clipped-ReLU ceiling used by scalar and future SIMD inference.
    #[must_use]
    pub const fn activation_max(&self) -> i32 {
        self.activation_max
    }

    /// Integer divisor converting the raw output dot product to engine score units.
    #[must_use]
    pub const fn output_scale(&self) -> i32 {
        self.output_scale
    }

    /// Training-manifest SHA-256 embedded by the exporter.
    #[must_use]
    pub const fn training_metadata_sha256(&self) -> &[u8; 32] {
        &self.training_metadata_sha256
    }

    /// Full-refresh integer evaluation from the side-to-move perspective.
    ///
    /// This is the slow correctness/reference path. It reconstructs both sparse perspective feature
    /// sets directly from the board and then forms two hidden accumulators on the stack. NNUE-3 proves
    /// its incremental accumulator produces exactly the same score.
    #[must_use]
    pub fn evaluate_full(&self, position: &Position) -> Option<i32> {
        let mut white_acc = [0_i32; MAX_HIDDEN];
        let mut black_acc = [0_i32; MAX_HIDDEN];
        self.rebuild_perspective(position, Color::White, &mut white_acc)?;
        self.rebuild_perspective(position, Color::Black, &mut black_acc)?;
        Some(self.score_accumulators(&white_acc, &black_acc, position.side_to_move()))
    }

    fn rebuild_perspective(
        &self,
        position: &Position,
        perspective: Color,
        target: &mut [i32; MAX_HIDDEN],
    ) -> Option<FeatureFrame> {
        let features = active_features(position, perspective)?;
        self.rebuild_accumulator(features.as_slice(), target);
        Some(features.frame())
    }

    fn rebuild_accumulator(&self, features: &[FeatureIndex], target: &mut [i32; MAX_HIDDEN]) {
        for (neuron, slot) in target[..self.hidden].iter_mut().enumerate() {
            *slot = i32::from(self.input_bias[neuron]);
        }
        target[self.hidden..].fill(0);
        for &feature in features {
            self.apply_feature_row(target, feature, 1);
        }
    }

    fn apply_feature_row(
        &self,
        target: &mut [i32; MAX_HIDDEN],
        feature: FeatureIndex,
        direction: i32,
    ) {
        debug_assert!(direction == -1 || direction == 1);
        let base = usize::from(feature.raw()) * self.hidden;
        for (neuron, slot) in target[..self.hidden].iter_mut().enumerate() {
            *slot += direction * i32::from(self.input_weights[base + neuron]);
        }
    }

    fn score_accumulators(
        &self,
        white: &[i32; MAX_HIDDEN],
        black: &[i32; MAX_HIDDEN],
        side_to_move: Color,
    ) -> i32 {
        let (us, them) = match side_to_move {
            Color::White => (&white[..self.hidden], &black[..self.hidden]),
            Color::Black => (&black[..self.hidden], &white[..self.hidden]),
        };

        let mut sum = i64::from(self.output_bias);
        for neuron in 0..self.hidden {
            let own = i64::from(us[neuron].clamp(0, self.activation_max));
            let opp = i64::from(them[neuron].clamp(0, self.activation_max));
            sum += own * i64::from(self.output_weights[neuron]);
            sum += opp * i64::from(self.output_weights[self.hidden + neuron]);
        }

        let scaled = sum / i64::from(self.output_scale);
        scaled.clamp(i64::from(i32::MIN), i64::from(i32::MAX)) as i32
    }
}

/// Validation failure for an NNUE network blob.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NetworkError {
    Truncated,
    BadMagic,
    UnsupportedVersion(u16),
    FeatureSetMismatch,
    FeatureCountMismatch(usize),
    UnsupportedHidden(usize),
    InvalidActivationMax(i32),
    InvalidOutputScale(i32),
    LengthOverflow,
    PayloadLengthMismatch { expected: usize, actual: usize },
    BlobLengthMismatch { expected: usize, actual: usize },
    PayloadChecksumMismatch { expected: u64, actual: u64 },
    WeightOutOfRange(i16),
}

impl fmt::Display for NetworkError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated => formatter.write_str("truncated NNUE network"),
            Self::BadMagic => formatter.write_str("invalid NNUE magic"),
            Self::UnsupportedVersion(version) => {
                write!(formatter, "unsupported NNUE version {version}")
            }
            Self::FeatureSetMismatch => {
                formatter.write_str("NNUE feature-set id does not match engine")
            }
            Self::FeatureCountMismatch(count) => write!(
                formatter,
                "NNUE feature count {count} does not match engine"
            ),
            Self::UnsupportedHidden(hidden) => {
                write!(formatter, "unsupported NNUE hidden width {hidden}")
            }
            Self::InvalidActivationMax(value) => {
                write!(formatter, "invalid NNUE activation maximum {value}")
            }
            Self::InvalidOutputScale(value) => {
                write!(formatter, "invalid NNUE output scale {value}")
            }
            Self::LengthOverflow => formatter.write_str("NNUE length arithmetic overflow"),
            Self::PayloadLengthMismatch { expected, actual } => write!(
                formatter,
                "NNUE payload length {actual} != expected {expected}"
            ),
            Self::BlobLengthMismatch { expected, actual } => write!(
                formatter,
                "NNUE blob length {actual} != expected {expected}"
            ),
            Self::PayloadChecksumMismatch { expected, actual } => write!(
                formatter,
                "NNUE payload checksum {actual:#018x} != expected {expected:#018x}"
            ),
            Self::WeightOutOfRange(weight) => write!(
                formatter,
                "NNUE weight {weight} exceeds accepted quantization bound"
            ),
        }
    }
}

impl std::error::Error for NetworkError {}

/// Stable non-cryptographic payload checksum used for corruption detection inside the model file.
///
/// Experiment manifests still identify whole files with SHA-256. FNV-1a here exists only so the
/// runtime can reject a damaged/truncated payload without pulling a hashing dependency into the
/// engine dependency graph.
#[must_use]
pub fn payload_checksum(payload: &[u8]) -> u64 {
    let mut hash = FNV_OFFSET;
    for &byte in payload {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    hash
}

fn encoded_feature_id() -> [u8; FEATURE_ID_BYTES] {
    let bytes = FEATURE_SET_ID.as_bytes();
    debug_assert!(bytes.len() <= FEATURE_ID_BYTES);
    let mut encoded = [0_u8; FEATURE_ID_BYTES];
    encoded[..bytes.len()].copy_from_slice(bytes);
    encoded
}

fn payload_len_for(hidden: usize) -> Option<usize> {
    let values = hidden
        .checked_add(FEATURE_COUNT.checked_mul(hidden)?)?
        .checked_add(hidden.checked_mul(2)?)?;
    values.checked_mul(2)?.checked_add(4)
}

fn validate_weight_bound(weights: &[i16]) -> Result<(), NetworkError> {
    for &weight in weights {
        if i32::from(weight).abs() > i32::from(MAX_ABS_WEIGHT) {
            return Err(NetworkError::WeightOutOfRange(weight));
        }
    }
    Ok(())
}

fn read_array<const N: usize>(bytes: &[u8], cursor: &mut usize) -> Result<[u8; N], NetworkError> {
    let end = cursor.checked_add(N).ok_or(NetworkError::LengthOverflow)?;
    let slice = bytes.get(*cursor..end).ok_or(NetworkError::Truncated)?;
    let mut result = [0_u8; N];
    result.copy_from_slice(slice);
    *cursor = end;
    Ok(result)
}

fn read_u16(bytes: &[u8], cursor: &mut usize) -> Result<u16, NetworkError> {
    Ok(u16::from_le_bytes(read_array::<2>(bytes, cursor)?))
}

fn read_i16(bytes: &[u8], cursor: &mut usize) -> Result<i16, NetworkError> {
    Ok(i16::from_le_bytes(read_array::<2>(bytes, cursor)?))
}

fn read_u32(bytes: &[u8], cursor: &mut usize) -> Result<u32, NetworkError> {
    Ok(u32::from_le_bytes(read_array::<4>(bytes, cursor)?))
}

fn read_i32(bytes: &[u8], cursor: &mut usize) -> Result<i32, NetworkError> {
    Ok(i32::from_le_bytes(read_array::<4>(bytes, cursor)?))
}

fn read_u64(bytes: &[u8], cursor: &mut usize) -> Result<u64, NetworkError> {
    Ok(u64::from_le_bytes(read_array::<8>(bytes, cursor)?))
}

fn read_i16_box(
    bytes: &[u8],
    cursor: &mut usize,
    count: usize,
) -> Result<Box<[i16]>, NetworkError> {
    let byte_count = count.checked_mul(2).ok_or(NetworkError::LengthOverflow)?;
    let end = cursor
        .checked_add(byte_count)
        .ok_or(NetworkError::LengthOverflow)?;
    let slice = bytes.get(*cursor..end).ok_or(NetworkError::Truncated)?;
    let (pairs, remainder) = slice.as_chunks::<2>();
    debug_assert!(remainder.is_empty());
    let mut values = Vec::with_capacity(count);
    for chunk in pairs {
        values.push(i16::from_le_bytes(*chunk));
    }
    *cursor = end;
    Ok(values.into_boxed_slice())
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, Position};

    use super::*;

    #[test]
    fn round_trip_parser_accepts_exact_tiny_layout() {
        let bytes = test_network(32, 127, 100, 300, None);
        let network = Network::from_bytes(&bytes).expect("valid test network");
        assert_eq!(network.hidden(), 32);
        assert_eq!(network.activation_max(), 127);
        assert_eq!(network.output_scale(), 100);
        assert_eq!(network.training_metadata_sha256(), &[7_u8; 32]);
        assert_eq!(network.evaluate_full(&Position::startpos()), Some(3));
    }

    #[test]
    fn parser_rejects_identity_checksum_and_weight_corruption() {
        let valid = test_network(32, 127, 100, 0, None);

        let mut magic = valid.clone();
        magic[0] ^= 1;
        assert_eq!(Network::from_bytes(&magic), Err(NetworkError::BadMagic));

        let mut feature = valid.clone();
        feature[10] ^= 1;
        assert_eq!(
            Network::from_bytes(&feature),
            Err(NetworkError::FeatureSetMismatch)
        );

        let mut payload = valid.clone();
        payload[HEADER_LEN] ^= 1;
        assert!(matches!(
            Network::from_bytes(&payload),
            Err(NetworkError::PayloadChecksumMismatch { .. })
        ));

        let mut out_of_range = test_network(32, 127, 100, 0, None);
        out_of_range[HEADER_LEN..HEADER_LEN + 2].copy_from_slice(&5000_i16.to_le_bytes());
        rewrite_checksum(&mut out_of_range);
        assert_eq!(
            Network::from_bytes(&out_of_range),
            Err(NetworkError::WeightOutOfRange(5000))
        );
    }

    #[test]
    fn full_inference_uses_side_to_move_perspective_order() {
        let white = Position::from_fen("4k3/8/8/8/8/8/P7/4K3 w - - 0 1").expect("valid FEN");
        let black = Position::from_fen("4k3/8/8/8/8/8/P7/4K3 b - - 0 1").expect("valid FEN");
        let white_features = active_features(&white, Color::White).expect("white features");
        let black_features = active_features(&white, Color::Black).expect("black features");
        let unique = white_features
            .as_slice()
            .iter()
            .copied()
            .find(|feature| !black_features.as_slice().contains(feature))
            .expect("asymmetric position has perspective-unique feature");

        let bytes = test_network(32, 127, 1, 0, Some(unique));
        let network = Network::from_bytes(&bytes).expect("valid feature test network");
        assert_eq!(network.evaluate_full(&white), Some(100));
        assert_eq!(network.evaluate_full(&black), Some(0));
    }

    #[test]
    fn supported_widths_have_exact_payload_sizes() {
        for hidden in SUPPORTED_HIDDEN {
            let bytes = test_network(hidden, 127, 64, 0, None);
            assert_eq!(
                bytes.len(),
                HEADER_LEN + payload_len_for(hidden).expect("supported width fits")
            );
            assert!(Network::from_bytes(&bytes).is_ok());
        }
    }

    fn test_network(
        hidden: usize,
        activation_max: i16,
        output_scale: i32,
        output_bias: i32,
        active_feature: Option<FeatureIndex>,
    ) -> Vec<u8> {
        let payload_len = payload_len_for(hidden).expect("test width fits");
        let mut payload = vec![0_u8; payload_len];

        if let Some(feature) = active_feature {
            let input_bias_bytes = hidden * 2;
            let weight_index = usize::from(feature.raw()) * hidden;
            let offset = input_bias_bytes + weight_index * 2;
            payload[offset..offset + 2].copy_from_slice(&100_i16.to_le_bytes());

            let output_weight_offset = input_bias_bytes + FEATURE_COUNT * hidden * 2;
            payload[output_weight_offset..output_weight_offset + 2]
                .copy_from_slice(&1_i16.to_le_bytes());
        }

        let output_bias_offset = payload_len - 4;
        payload[output_bias_offset..].copy_from_slice(&output_bias.to_le_bytes());

        let mut bytes = Vec::with_capacity(HEADER_LEN + payload_len);
        bytes.extend_from_slice(&MAGIC);
        bytes.extend_from_slice(&FORMAT_VERSION.to_le_bytes());
        bytes.extend_from_slice(&encoded_feature_id());
        bytes.extend_from_slice(&(FEATURE_COUNT as u32).to_le_bytes());
        bytes.extend_from_slice(&(hidden as u16).to_le_bytes());
        bytes.extend_from_slice(&activation_max.to_le_bytes());
        bytes.extend_from_slice(&output_scale.to_le_bytes());
        bytes.extend_from_slice(&(payload_len as u32).to_le_bytes());
        bytes.extend_from_slice(&payload_checksum(&payload).to_le_bytes());
        bytes.extend_from_slice(&[7_u8; 32]);
        assert_eq!(bytes.len(), HEADER_LEN);
        bytes.extend_from_slice(&payload);
        bytes
    }

    fn rewrite_checksum(bytes: &mut [u8]) {
        let checksum = payload_checksum(&bytes[HEADER_LEN..]);
        let checksum_offset = 58;
        bytes[checksum_offset..checksum_offset + 8].copy_from_slice(&checksum.to_le_bytes());
    }
}
