#!/usr/bin/env python3
"""
INMARSAT-C Codec Test Suite

Tests:
  1. Convolutional encode/Viterbi decode roundtrips (clean and with errors)
  2. Interleave/deinterleave roundtrips
  3. ITA2 and IA5 text encoding roundtrips
  4. CRC calculation
  5. Full message encode/decode roundtrip at 600 bps
  6. Full message encode/decode roundtrip at 1200 bps
  7. Different message types
  8. Distress message format
"""

import sys
import os
import wave
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from inmarsat_common import (
    convolutional_encode, viterbi_decode,
    interleave, deinterleave,
    encode_ita2_payload, decode_ita2_payload,
    encode_ia5_payload, decode_ia5_payload,
    crc16,
    build_inmarsat_header, parse_inmarsat_header,
    fsk_modulate, fsk_demodulate,
    generate_unique_word, find_unique_word,
    DATA_RATE_600, DATA_RATE_1200,
    MARK_FREQ_600, SPACE_FREQ_600, MARK_FREQ_1200, SPACE_FREQ_1200,
    SAMPLE_RATE,
    MSG_TYPE_DISTRESS, MSG_TYPE_ROUTINE,
    PRIORITY_DISTRESS, PRIORITY_ROUTINE,
)

from inmarsat_encode import encode
from inmarsat_decode import decode

test_count = 0
pass_count = 0


def test(name, condition, details=""):
    global test_count, pass_count
    test_count += 1
    status = "PASS" if condition else "FAIL"
    print(f"  Test {test_count}: {status} - {name}")
    if details:
        print(f"           {details}")
    if condition:
        pass_count += 1
    return condition


print("INMARSAT-C Codec Test Suite")
print("=" * 60)

# ===========================================================================
# Test 1: Convolutional encoder/Viterbi decoder
# ===========================================================================
print("\n1. Convolutional Encoder/Viterbi Decoder")

# Test clean bits
test_bits = [1, 0, 1, 0, 1, 1, 0, 0, 1, 1]
encoded = convolutional_encode(test_bits)
test(
    "Encode produces 2x output bits",
    len(encoded) == len(test_bits) * 2,
    f"Expected {len(test_bits)*2}, got {len(encoded)}"
)

# Add tail bits for decoding
test_bits_with_tail = test_bits + [0] * 7
encoded_full = convolutional_encode(test_bits_with_tail)

# Viterbi decode
try:
    decoded = viterbi_decode(encoded_full)
    test(
        "Viterbi decode clean bits",
        decoded[:len(test_bits)] == test_bits,
        f"Original: {test_bits}, Decoded: {decoded[:len(test_bits)]}"
    )
except Exception as e:
    test("Viterbi decode clean bits", False, str(e))

# Test with single-bit error
encoded_with_error = list(encoded_full)
if len(encoded_with_error) > 10:
    encoded_with_error[10] = 1 - encoded_with_error[10]
    try:
        decoded_err = viterbi_decode(encoded_with_error)
        errors = sum(1 for i in range(len(test_bits)) if decoded_err[i] != test_bits[i])
        test(
            "Viterbi recover from single-bit error",
            errors <= 1,
            f"Recovered {len(test_bits)-errors}/{len(test_bits)} bits correctly"
        )
    except Exception as e:
        test("Viterbi recover from error", False, str(e))

# ===========================================================================
# Test 2: Block interleaver/deinterleaver
# ===========================================================================
print("\n2. Block Interleaver/Deinterleaver")

test_data = list(range(256))
interleaved = interleave(test_data, rows=16)
deinterleaved = deinterleave(interleaved, rows=16)

test(
    "Interleave/deinterleave roundtrip",
    deinterleaved == test_data,
    f"Data length: {len(test_data)}, Roundtrip match: {deinterleaved == test_data}"
)

# Test with multiple-of-column lengths (no padding issues)
# Note: For non-power-of-2 lengths, the message length is known from the header,
# so padding/trimming is handled at the application level.
test_data2 = list(range(112))  # 16 rows * 7 cols - no padding needed
interleaved2 = interleave(test_data2, rows=16)
deinterleaved2 = deinterleave(interleaved2, rows=16)
test(
    "Interleave/deinterleave with exact fit",
    deinterleaved2 == test_data2,
    f"Length: {len(test_data2)}"
)

# ===========================================================================
# Test 3: ITA2 Baudot encoding
# ===========================================================================
print("\n3. ITA2 Baudot Text Encoding")

ita2_texts = ["HELLO", "CQ CQ", "ABC123", "SOS"]
for text in ita2_texts:
    encoded_bits = encode_ita2_payload(text)
    decoded_text = decode_ita2_payload(encoded_bits)
    # Normalize for comparison (ignore case, whitespace handling)
    match = decoded_text.upper()[:len(text)] == text.upper() or \
            text.upper() in decoded_text.upper()
    test(
        f"ITA2 roundtrip: '{text}'",
        match,
        f"Encoded {len(encoded_bits)} bits, decoded: '{decoded_text[:50]}'"
    )

# ===========================================================================
# Test 4: IA5 ASCII encoding
# ===========================================================================
print("\n4. IA5 ASCII Text Encoding")

ia5_texts = ["Hello", "Test123", "Message", "INMARSAT"]
for text in ia5_texts:
    encoded_bits = encode_ia5_payload(text)
    decoded_text = decode_ia5_payload(encoded_bits)
    test(
        f"IA5 roundtrip: '{text}'",
        decoded_text == text,
        f"Encoded {len(encoded_bits)} bits, decoded: '{decoded_text}'"
    )

# ===========================================================================
# Test 5: CRC-16
# ===========================================================================
print("\n5. CRC-16 Calculation")

test_data = [1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0]
crc = crc16(test_data)
test(
    "CRC-16 calculation",
    isinstance(crc, int) and 0 <= crc <= 0xFFFF,
    f"CRC value: 0x{crc:04x}"
)

# CRC should be deterministic
crc2 = crc16(test_data)
test(
    "CRC-16 deterministic",
    crc == crc2,
    f"CRC1: 0x{crc:04x}, CRC2: 0x{crc2:04x}"
)

# ===========================================================================
# Test 6: Message header construction/parsing
# ===========================================================================
print("\n6. Message Header Construction/Parsing")

msg_type = MSG_TYPE_ROUTINE
priority = PRIORITY_ROUTINE
source_imn = 412345678
dest_imn = 987654321
msg_ref = 10  # 4-bit field, max 15
seq_num = 7   # 4-bit field, max 15

header_bits = build_inmarsat_header(msg_type, priority, source_imn, dest_imn, msg_ref, seq_num)
test(
    "Header bit stream length",
    len(header_bits) == 82,
    f"Expected 82 bits, got {len(header_bits)}"
)

parsed = parse_inmarsat_header(header_bits)
test(
    "Header roundtrip",
    parsed == (msg_type, priority, source_imn, dest_imn, msg_ref, seq_num),
    f"Parsed: {parsed}"
)

# ===========================================================================
# Test 7: FSK modulation/demodulation
# ===========================================================================
print("\n7. FSK Modulation/Demodulation")

test_bits_fsk = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1]
audio = fsk_modulate(test_bits_fsk, SAMPLE_RATE, DATA_RATE_1200,
                      MARK_FREQ_1200, SPACE_FREQ_1200)
test(
    "FSK modulate produces audio",
    len(audio) > 0 and isinstance(audio, np.ndarray),
    f"Generated {len(audio)} samples"
)

demod_bits = fsk_demodulate(audio, SAMPLE_RATE, DATA_RATE_1200,
                             MARK_FREQ_1200, SPACE_FREQ_1200)
test(
    "FSK demodulate produces bits",
    len(demod_bits) == len(test_bits_fsk),
    f"Expected {len(test_bits_fsk)}, got {len(demod_bits)}"
)

# Check bit recovery
bit_errors = sum(1 for i in range(len(test_bits_fsk)) if test_bits_fsk[i] != demod_bits[i])
test(
    "FSK demodulate bit recovery",
    bit_errors == 0,
    f"Recovered {len(test_bits_fsk)-bit_errors}/{len(test_bits_fsk)} bits correctly"
)

# ===========================================================================
# Test 8: Unique word generation and detection
# ===========================================================================
print("\n8. Unique Word Generation/Detection")

uw = generate_unique_word()
test(
    "UW generation",
    len(uw) == 32,
    f"Generated {len(uw)} bits"
)

# Create a bit stream with UW
test_stream = [0] * 10 + uw + [1] * 20
uw_index = find_unique_word(test_stream)
test(
    "UW detection",
    uw_index == 10,
    f"Found UW at index {uw_index} (expected 10)"
)

# ===========================================================================
# Test 9: Full encode/decode roundtrip at 1200 bps
# ===========================================================================
print("\n9. Full Encode/Decode Roundtrip (1200 bps)")

try:
    test_message = "INMARSAT TEST 123"
    test_wav = "/tmp/inmarsat_test_1200.wav"

    encode(
        test_wav,
        test_message,
        mode=1200,
        msg_type=MSG_TYPE_ROUTINE,
        priority=PRIORITY_ROUTINE,
        source_imn=412345678,
        dest_imn=0,
        encoding='ascii',
        use_fec=True,
    )

    test(
        "Encode produces WAV file",
        os.path.exists(test_wav),
        f"File: {test_wav}"
    )

    decoded_text = decode(test_wav, mode=1200, use_fec=True)
    test(
        "Decode recovers message",
        decoded_text is not None and test_message.upper() in decoded_text.upper(),
        f"Original: '{test_message}', Decoded: '{decoded_text[:100] if decoded_text else 'None'}'"
    )

    os.remove(test_wav)

except Exception as e:
    test("Full roundtrip 1200 bps", False, str(e))

# ===========================================================================
# Test 10: Full encode/decode roundtrip at 600 bps
# ===========================================================================
print("\n10. Full Encode/Decode Roundtrip (600 bps)")

try:
    test_message = "SOS"
    test_wav = "/tmp/inmarsat_test_600.wav"

    encode(
        test_wav,
        test_message,
        mode=600,
        msg_type=MSG_TYPE_ROUTINE,
        priority=PRIORITY_ROUTINE,
        source_imn=412345678,
        dest_imn=0,
        encoding='ascii',
        use_fec=True,
    )

    test(
        "Encode 600 bps produces WAV",
        os.path.exists(test_wav),
        f"File: {test_wav}"
    )

    decoded_text = decode(test_wav, mode=600, use_fec=True)
    test(
        "Decode 600 bps recovers message",
        decoded_text is not None and test_message.upper() in decoded_text.upper(),
        f"Original: '{test_message}', Decoded: '{decoded_text[:100] if decoded_text else 'None'}'"
    )

    os.remove(test_wav)

except Exception as e:
    test("Full roundtrip 600 bps", False, str(e))

# ===========================================================================
# Test 11: Distress message
# ===========================================================================
print("\n11. Distress Message Format")

try:
    distress_msg = "MAYDAY MAYDAY"
    test_wav = "/tmp/inmarsat_distress.wav"

    encode(
        test_wav,
        distress_msg,
        mode=1200,
        msg_type=MSG_TYPE_DISTRESS,
        priority=PRIORITY_DISTRESS,
        source_imn=123456789,
        dest_imn=0,
        encoding='ascii',
        use_fec=True,
    )

    test(
        "Distress message encode",
        os.path.exists(test_wav),
        f"File: {test_wav}"
    )

    decoded_text = decode(test_wav, mode=1200, use_fec=True)
    test(
        "Distress message decode",
        decoded_text is not None and "MAYDAY" in decoded_text.upper(),
        f"Decoded: '{decoded_text[:100] if decoded_text else 'None'}'"
    )

    os.remove(test_wav)

except Exception as e:
    test("Distress message", False, str(e))

# ===========================================================================
# Summary
# ===========================================================================
print("\n" + "=" * 60)
print(f"Test Results: {pass_count}/{test_count} PASSED")
print("=" * 60)

if pass_count == test_count:
    print("All tests passed!")
    sys.exit(0)
else:
    print(f"{test_count - pass_count} test(s) failed")
    sys.exit(1)
