#!/usr/bin/env python3
"""Skip native AVX2 L1 columns whose four activated input bytes are all zero."""

from pathlib import Path

path = Path("crates/chess-eval/src/hyperstition.rs")
text = path.read_text(encoding="utf-8")
old = """        let input_word = i32::from_le_bytes(\n            ft[input_base..input_base + L1_INPUT_CHUNK]\n                .try_into()\n                .expect(\"four-byte FT chunk\"),\n        );\n        let input = m256i::from([input_word; 8]);\n"""
new = """        let input_word = i32::from_le_bytes(\n            ft[input_base..input_base + L1_INPUT_CHUNK]\n                .try_into()\n                .expect(\"four-byte FT chunk\"),\n        );\n        if input_word == 0 {\n            continue;\n        }\n        let input = m256i::from([input_word; 8]);\n"""
if text.count(old) != 1:
    raise SystemExit(f"expected one AVX2 input chunk site, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("applied Hyperstition AVX2 zero-chunk skip probe")
