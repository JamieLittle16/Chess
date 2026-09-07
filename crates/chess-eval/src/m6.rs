//! M6-A learned-evaluation runtime substrate.
//!
//! This module deliberately does not participate in production evaluation yet. It defines the
//! integer inference contract for the first large-data Bullet network so a trained checkpoint can
//! be validated against Rust before any search integration is attempted.

use chess_core::{Color, PieceKind, Position, Square};

pub const FEATURE_COUNT: usize = 768;
pub const HIDDEN_SIZE: usize = 512;
pub const QA: i16 = 255;
pub const QB: i16 = 64;
pub const EVAL_SCALE: i32 = 400;

const FEATURE_WEIGHTS_COUNT: usize = FEATURE_COUNT * HIDDEN_SIZE;
const OUTPUT_WEIGHTS_COUNT: usize = 2 * HIDDEN_SIZE;
const LOGICAL_PAYLOAD_I16S: usize =
    FEATURE_WEIGHTS_COUNT + HIDDEN_SIZE + OUTPUT_WEIGHTS_COUNT + 1;
pub const BULLET_LOGICAL_BYTES: usize = LOGICAL_PAYLOAD_I16S * size_of::<i16>();
pub const BULLET_PADDED_BYTES: usize = BULLET_LOGICAL_BYTES.next_multiple_of(64);
const BULLET_PADDING: &[u8] = b"bullet";

const MAGIC: [u8; 8] = *b"CHM6A1\0\0";
const FORMAT_VERSION: u16 = 1;
const HEADER_LEN: usize = 72;
const MAX_FEATURE_WEIGHT_ABS: i16 = 512;
const MAX_OUTPUT_WEIGHT_ABS: i16 = 128;

/// Parsed M6-A network.
///
/// Tensor layout matches Bullet's saved format exactly:
/// `l0w`, `l0b`, `l1w`, `l1b`, all little-endian `i16`.
#[derive(Clone, Debug)]
pub struct Network {
    feature_weights: Box<[i16]>,
    feature_bias: Box<[i16]>,
    output_weights: Box<[i16]>,
    output_bias: i16,
    training_metadata_sha256: [u8; 32],
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NetworkError {
    BadMagic,
    UnsupportedVersion(u16),
    BadHeaderLength(u16),
    WrongFeatureCount(u16),
    WrongHiddenSize(u16),
    WrongQa(u16),
    WrongQb(u16),
    WrongEvalScale(i32),
    WrongPayloadLength(usize),
    BadPayloadChecksum,
    BadBulletPadding,
    WeightOutOfRange,
}

/// One perspective's quantised hidden accumulator.
#[derive(Clone, Debug, PartialEq, Eq)]
#[repr(C, align(64))]
pub struct Accumulator {
    vals: [i16; HIDDEN_SIZE],
}

impl Network {
    /// Parse the raw quantised `.bin` emitted by the pinned Bullet trainer.
    ///
    /// Bullet pads network files to 64-byte alignment with the repeating bytes `bullet`; both the
    /// logical unpadded tensor stream and the canonical padded file are accepted here.
    pub fn from_bullet_bytes(bytes: &[u8]) -> Result<Self, NetworkError> {
        let payload = match bytes.len() {
            BULLET_LOGICAL_BYTES => bytes,
            BULLET_PADDED_BYTES => {
                let (payload, padding) = bytes.split_at(BULLET_LOGICAL_BYTES);
                if !padding
                    .iter()
                    .enumerate()
                    .all(|(index, &byte)| byte == BULLET_PADDING[index % BULLET_PADDING.len()])
                {
                    return Err(NetworkError::BadBulletPadding);
                }
                payload
            }
            actual => return Err(NetworkError::WrongPayloadLength(actual)),
        };
        Self::from_logical_payload(payload, [0; 32])
    }

    /// Parse the versioned Chess wrapper used for retained M6 checkpoints.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, NetworkError> {
        if bytes.len() < HEADER_LEN {
            return Err(NetworkError::WrongPayloadLength(bytes.len()));
        }
        if bytes[..8] != MAGIC {
            return Err(NetworkError::BadMagic);
        }
        let version = read_u16(bytes, 8);
        if version != FORMAT_VERSION {
            return Err(NetworkError::UnsupportedVersion(version));
        }
        let header_len = read_u16(bytes, 10);
        if usize::from(header_len) != HEADER_LEN {
            return Err(NetworkError::BadHeaderLength(header_len));
        }
        let features = read_u16(bytes, 12);
        if usize::from(features) != FEATURE_COUNT {
            return Err(NetworkError::WrongFeatureCount(features));
        }
        let hidden = read_u16(bytes, 14);
        if usize::from(hidden) != HIDDEN_SIZE {
            return Err(NetworkError::WrongHiddenSize(hidden));
        }
        let qa = read_u16(bytes, 16);
        if qa != QA as u16 {
            return Err(NetworkError::WrongQa(qa));
        }
        let qb = read_u16(bytes, 18);
        if qb != QB as u16 {
            return Err(NetworkError::WrongQb(qb));
        }
        let scale = read_i32(bytes, 20);
        if scale != EVAL_SCALE {
            return Err(NetworkError::WrongEvalScale(scale));
        }
        let payload_len = read_u32(bytes, 24) as usize;
        if payload_len != BULLET_LOGICAL_BYTES || bytes.len() != HEADER_LEN + payload_len {
            return Err(NetworkError::WrongPayloadLength(
                bytes.len().saturating_sub(HEADER_LEN),
            ));
        }
        let expected_checksum = read_u64(bytes, 28);
        let payload = &bytes[HEADER_LEN..];
        if fnv1a64(payload) != expected_checksum {
            return Err(NetworkError::BadPayloadChecksum);
        }
        let mut training_metadata_sha256 = [0_u8; 32];
        training_metadata_sha256.copy_from_slice(&bytes[36..68]);
        Self::from_logical_payload(payload, training_metadata_sha256)
    }

    /// Construct a versioned Chess network from a raw Bullet checkpoint.
    ///
    /// This is primarily an exporter/oracle helper; training metadata is represented by the
    /// caller-provided SHA-256 rather than embedding machine-specific paths.
    pub fn wrap_bullet_bytes(
        bullet_bytes: &[u8],
        training_metadata_sha256: [u8; 32],
    ) -> Result<Vec<u8>, NetworkError> {
        let net = Self::from_bullet_bytes(bullet_bytes)?;
        let logical = net.logical_payload();
        let mut bytes = Vec::with_capacity(HEADER_LEN + logical.len());
        bytes.extend_from_slice(&MAGIC);
        bytes.extend_from_slice(&FORMAT_VERSION.to_le_bytes());
        bytes.extend_from_slice(&(HEADER_LEN as u16).to_le_bytes());
        bytes.extend_from_slice(&(FEATURE_COUNT as u16).to_le_bytes());
        bytes.extend_from_slice(&(HIDDEN_SIZE as u16).to_le_bytes());
        bytes.extend_from_slice(&(QA as u16).to_le_bytes());
        bytes.extend_from_slice(&(QB as u16).to_le_bytes());
        bytes.extend_from_slice(&EVAL_SCALE.to_le_bytes());
        bytes.extend_from_slice(&(logical.len() as u32).to_le_bytes());
        bytes.extend_from_slice(&fnv1a64(&logical).to_le_bytes());
        bytes.extend_from_slice(&training_metadata_sha256);
        bytes.extend_from_slice(&[0_u8; HEADER_LEN - 68]);
        bytes.extend_from_slice(&logical);
        Ok(bytes)
    }

    #[must_use]
    pub const fn training_metadata_sha256(&self) -> &[u8; 32] {
        &self.training_metadata_sha256
    }

    /// Slow full-refresh oracle from canonical board state.
    #[must_use]
    pub fn evaluate_full(&self, position: &Position) -> i32 {
        let us = position.side_to_move();
        let them = us.opposite();
        let us_acc = self.rebuild(position, us);
        let them_acc = self.rebuild(position, them);
        self.evaluate_accumulators(&us_acc, &them_acc)
    }

    /// Rebuild one perspective's hidden accumulator from canonical piece bitboards.
    #[must_use]
    pub fn rebuild(&self, position: &Position, perspective: Color) -> Accumulator {
        let mut acc = Accumulator {
            vals: [0; HIDDEN_SIZE],
        };
        acc.vals.copy_from_slice(&self.feature_bias);

        for color in Color::ALL {
            for kind in PieceKind::ALL {
                let mut pieces = position.pieces(color, kind);
                while let Some(square) = pieces.pop_lsb() {
                    let feature = feature_index(color, kind, square, perspective);
                    self.add_feature(&mut acc, feature);
                }
            }
        }
        acc
    }

    /// Evaluate already-maintained side-to-move and opponent accumulators.
    #[must_use]
    pub fn evaluate_accumulators(&self, us: &Accumulator, them: &Accumulator) -> i32 {
        let mut output = 0_i64;
        for (&input, &weight) in us
            .vals
            .iter()
            .zip(&self.output_weights[..HIDDEN_SIZE])
        {
            output += screlu(input) * i64::from(weight);
        }
        for (&input, &weight) in them
            .vals
            .iter()
            .zip(&self.output_weights[HIDDEN_SIZE..])
        {
            output += screlu(input) * i64::from(weight);
        }

        output /= i64::from(QA);
        output += i64::from(self.output_bias);
        output *= i64::from(EVAL_SCALE);
        output /= i64::from(QA) * i64::from(QB);
        output.clamp(i64::from(i32::MIN), i64::from(i32::MAX)) as i32
    }

    fn from_logical_payload(
        payload: &[u8],
        training_metadata_sha256: [u8; 32],
    ) -> Result<Self, NetworkError> {
        if payload.len() != BULLET_LOGICAL_BYTES {
            return Err(NetworkError::WrongPayloadLength(payload.len()));
        }
        let values = decode_i16(payload);
        debug_assert_eq!(values.len(), LOGICAL_PAYLOAD_I16S);

        let feature_weights_end = FEATURE_WEIGHTS_COUNT;
        let feature_bias_end = feature_weights_end + HIDDEN_SIZE;
        let output_weights_end = feature_bias_end + OUTPUT_WEIGHTS_COUNT;

        let feature_weights = values[..feature_weights_end].to_vec().into_boxed_slice();
        let feature_bias = values[feature_weights_end..feature_bias_end]
            .to_vec()
            .into_boxed_slice();
        let output_weights = values[feature_bias_end..output_weights_end]
            .to_vec()
            .into_boxed_slice();
        let output_bias = values[output_weights_end];

        if feature_weights
            .iter()
            .chain(feature_bias.iter())
            .any(|&weight| weight.unsigned_abs() > MAX_FEATURE_WEIGHT_ABS as u16)
            || output_weights
                .iter()
                .any(|&weight| weight.unsigned_abs() > MAX_OUTPUT_WEIGHT_ABS as u16)
        {
            return Err(NetworkError::WeightOutOfRange);
        }

        Ok(Self {
            feature_weights,
            feature_bias,
            output_weights,
            output_bias,
            training_metadata_sha256,
        })
    }

    fn add_feature(&self, accumulator: &mut Accumulator, feature: usize) {
        let start = feature * HIDDEN_SIZE;
        let weights = &self.feature_weights[start..start + HIDDEN_SIZE];
        for (value, &weight) in accumulator.vals.iter_mut().zip(weights) {
            *value = value
                .checked_add(weight)
                .expect("validated M6-A weights fit an i16 accumulator");
        }
    }

    fn logical_payload(&self) -> Vec<u8> {
        let mut payload = Vec::with_capacity(BULLET_LOGICAL_BYTES);
        for &value in self
            .feature_weights
            .iter()
            .chain(self.feature_bias.iter())
            .chain(self.output_weights.iter())
            .chain(core::iter::once(&self.output_bias))
        {
            payload.extend_from_slice(&value.to_le_bytes());
        }
        debug_assert_eq!(payload.len(), BULLET_LOGICAL_BYTES);
        payload
    }
}

/// Exact Bullet `Chess768` feature mapping for one absolute Rust position/perspective.
///
/// Own pieces occupy inputs `0..384`, opponent pieces `384..768`. Black's perspective mirrors
/// ranks (`sq ^ 56`) so both accumulators use the same side-to-move-relative coordinate system.
#[must_use]
pub const fn feature_index(
    piece_color: Color,
    kind: PieceKind,
    square: Square,
    perspective: Color,
) -> usize {
    let ownership = if piece_color.index() == perspective.index() {
        0
    } else {
        384
    };
    let square = if perspective.index() == Color::White.index() {
        square.index()
    } else {
        square.index() ^ 56
    };
    ownership + kind.index() * 64 + square as usize
}

#[inline]
fn screlu(value: i16) -> i64 {
    let value = i64::from(value).clamp(0, i64::from(QA));
    value * value
}

fn decode_i16(bytes: &[u8]) -> Vec<i16> {
    bytes
        .chunks_exact(2)
        .map(|chunk| i16::from_le_bytes([chunk[0], chunk[1]]))
        .collect()
}

fn read_u16(bytes: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes([bytes[offset], bytes[offset + 1]])
}

fn read_u32(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().expect("four bytes"))
}

fn read_i32(bytes: &[u8], offset: usize) -> i32 {
    i32::from_le_bytes(bytes[offset..offset + 4].try_into().expect("four bytes"))
}

fn read_u64(bytes: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(bytes[offset..offset + 8].try_into().expect("eight bytes"))
}

fn fnv1a64(bytes: &[u8]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for &byte in bytes {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

#[cfg(test)]
mod tests {
    use super::*;

    fn raw_network(output_bias: i16) -> Vec<u8> {
        let mut bytes = vec![0_u8; BULLET_LOGICAL_BYTES];
        let tail = bytes.len() - 2;
        bytes[tail..].copy_from_slice(&output_bias.to_le_bytes());
        bytes
    }

    fn padded(mut logical: Vec<u8>) -> Vec<u8> {
        let padding = BULLET_PADDED_BYTES - logical.len();
        for index in 0..padding {
            logical.push(BULLET_PADDING[index % BULLET_PADDING.len()]);
        }
        logical
    }

    #[test]
    fn feature_mapping_matches_bullet_chess768_perspectives() {
        let position = Position::from_fen("8/8/4k3/8/3N4/8/4P3/4K3 b - - 0 1").expect("fen");
        let e6 = Square::from_file_rank(4, 5).expect("e6");
        let d4 = Square::from_file_rank(3, 3).expect("d4");
        let e2 = Square::from_file_rank(4, 1).expect("e2");
        let e1 = Square::from_file_rank(4, 0).expect("e1");

        assert_eq!(feature_index(Color::Black, PieceKind::King, e6, Color::Black), 340);
        assert_eq!(feature_index(Color::White, PieceKind::Knight, d4, Color::Black), 483);
        assert_eq!(feature_index(Color::White, PieceKind::Pawn, e2, Color::Black), 436);
        assert_eq!(feature_index(Color::White, PieceKind::King, e1, Color::Black), 764);

        assert_eq!(feature_index(Color::Black, PieceKind::King, e6, Color::White), 748);
        assert_eq!(feature_index(Color::White, PieceKind::Knight, d4, Color::White), 91);
        assert_eq!(feature_index(Color::White, PieceKind::Pawn, e2, Color::White), 12);
        assert_eq!(feature_index(Color::White, PieceKind::King, e1, Color::White), 324);
    }

    #[test]
    fn bullet_padding_is_checked() {
        let logical = raw_network(0);
        assert!(Network::from_bullet_bytes(&logical).is_ok());
        let mut canonical = padded(logical);
        assert!(Network::from_bullet_bytes(&canonical).is_ok());
        *canonical.last_mut().expect("padding byte") ^= 1;
        assert_eq!(
            Network::from_bullet_bytes(&canonical).unwrap_err(),
            NetworkError::BadBulletPadding
        );
    }

    #[test]
    fn quantised_output_formula_matches_bullet_example() {
        let network = Network::from_bullet_bytes(&raw_network(QA * QB)).expect("network");
        assert_eq!(network.evaluate_full(&Position::startpos()), EVAL_SCALE);
    }

    #[test]
    fn wrapped_format_round_trips_payload_and_metadata() {
        let raw = padded(raw_network(QA * QB));
        let metadata = [0x5a; 32];
        let wrapped = Network::wrap_bullet_bytes(&raw, metadata).expect("wrap");
        let network = Network::from_bytes(&wrapped).expect("parse");
        assert_eq!(network.training_metadata_sha256(), &metadata);
        assert_eq!(network.evaluate_full(&Position::startpos()), EVAL_SCALE);
    }

    #[test]
    fn wrapped_checksum_detects_corruption() {
        let wrapped = Network::wrap_bullet_bytes(&raw_network(0), [0; 32]).expect("wrap");
        let mut corrupt = wrapped;
        *corrupt.last_mut().expect("payload") ^= 1;
        assert_eq!(
            Network::from_bytes(&corrupt).unwrap_err(),
            NetworkError::BadPayloadChecksum
        );
    }

    #[test]
    fn trained_range_guard_rejects_implausible_feature_weight() {
        let mut raw = raw_network(0);
        raw[..2].copy_from_slice(&513_i16.to_le_bytes());
        assert_eq!(
            Network::from_bullet_bytes(&raw).unwrap_err(),
            NetworkError::WeightOutOfRange
        );
    }
}
