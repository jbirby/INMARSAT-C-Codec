#!/usr/bin/env python3
"""
INMARSAT-C Decoder — Convert INMARSAT-C audio WAV to text.

Extracts data from a standards-compliant INMARSAT-C transmission:
  1. Read WAV file (any sample rate — resamples to 44100 if needed)
  2. FSK-demodulate to extract bits
  3. Find and verify unique word for frame sync
  4. De-interleave the bit stream
  5. Viterbi-decode FEC to recover original bits
  6. Extract header, verify CRC
  7. Decode payload (auto-detect IA5 vs ITA2)
  8. Display message type, priority, addresses, text

Usage:
    python3 inmarsat_decode.py <input.wav> [output.txt] [options]

Options:
    --mode 600|1200     Data rate in bps (default: auto-detect)
    --no-fec            Disable FEC decoding
"""

import sys
import wave
import os
import numpy as np
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from inmarsat_common import (
    SAMPLE_RATE, DATA_RATE_600, DATA_RATE_1200,
    MARK_FREQ_600, SPACE_FREQ_600, MARK_FREQ_1200, SPACE_FREQ_1200,
    MSG_TYPE_DISTRESS, MSG_TYPE_URGENCY, MSG_TYPE_SAFETY, MSG_TYPE_ROUTINE, MSG_TYPE_EGC_SAFETY,
    PRIORITY_DISTRESS, PRIORITY_URGENCY, PRIORITY_SAFETY, PRIORITY_ROUTINE,
    parse_inmarsat_header, decode_ia5_payload, decode_ita2_payload,
    viterbi_decode, deinterleave, crc16, fsk_demodulate,
    find_unique_word,
)


def resample_audio(audio, orig_rate, target_rate):
    """Resample audio using linear interpolation."""
    if orig_rate == target_rate:
        return audio

    ratio = target_rate / orig_rate
    new_length = int(len(audio) * ratio)
    new_audio = np.interp(
        np.linspace(0, len(audio) - 1, new_length),
        np.arange(len(audio)),
        audio
    )
    return new_audio


def decode(input_path, mode=None, use_fec=True, output_file=None):
    """Decode an INMARSAT-C WAV file."""

    # Load WAV file
    with wave.open(input_path, 'rb') as wav:
        n_channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        framerate = wav.getframerate()
        n_frames = wav.getnframes()

        audio_bytes = wav.readframes(n_frames)
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        if n_channels == 2:
            audio = audio.reshape(-1, 2)
            audio = audio.mean(axis=1)

    print(f"Loaded {input_path}")
    print(f"  Sample rate: {framerate} Hz")
    print(f"  Samples: {len(audio)}")
    print(f"  Duration: {len(audio) / framerate:.3f} seconds")

    # Resample to 44100 if needed
    if framerate != SAMPLE_RATE:
        print(f"  Resampling to {SAMPLE_RATE} Hz...")
        audio = resample_audio(audio, framerate, SAMPLE_RATE)

    # Try both modes if not specified
    modes_to_try = [mode] if mode else [1200, 600]
    results = []

    for try_mode in modes_to_try:
        print(f"\nTrying mode {try_mode} bps...")

        if try_mode == 600:
            data_rate = DATA_RATE_600
            mark_freq = MARK_FREQ_600
            space_freq = SPACE_FREQ_600
        else:
            data_rate = DATA_RATE_1200
            mark_freq = MARK_FREQ_1200
            space_freq = SPACE_FREQ_1200

        try:
            # FSK demodulate
            print(f"  FSK demodulating...")
            bits = fsk_demodulate(audio, SAMPLE_RATE, data_rate, mark_freq, space_freq)
            print(f"  Demodulated {len(bits)} bits")

            # Find unique word
            print(f"  Searching for unique word...")
            uw_index = find_unique_word(bits)
            if uw_index < 0:
                print(f"  Warning: Unique word not found (might still decode)")
                uw_index = 0
            else:
                print(f"  Found unique word at bit {uw_index}")

            # Extract data after unique word
            data_bits = bits[uw_index + 32:]  # Skip UW (32 bits)
            print(f"  Data bits after UW: {len(data_bits)}")

            # De-interleave
            deint_bits = deinterleave(data_bits, rows=16)
            print(f"  De-interleaved bits: {len(deint_bits)}")

            # Viterbi decode FEC if enabled
            if use_fec:
                print(f"  Viterbi decoding...")
                try:
                    decoded_bits = viterbi_decode(deint_bits)
                    print(f"  FEC decoded to {len(decoded_bits)} bits")
                except Exception as e:
                    print(f"  FEC decode warning: {e}")
                    decoded_bits = deint_bits
            else:
                decoded_bits = deint_bits

            # Parse header
            print(f"  Parsing header...")
            if len(decoded_bits) < 82:
                raise ValueError(f"Not enough bits for header (need 82, got {len(decoded_bits)})")

            header_bits = decoded_bits[:82]
            try:
                msg_type, priority, source_imn, dest_imn, msg_ref, seq_num = parse_inmarsat_header(header_bits)
                print(f"  Message type: 0x{msg_type:02x}")
                print(f"  Priority: {priority}")
                print(f"  Source IMN: {source_imn:09d}")
                print(f"  Dest IMN: {dest_imn:09d}")
                print(f"  Message ref: {msg_ref}")
                print(f"  Sequence: {seq_num}")
            except Exception as e:
                print(f"  Header parse error: {e}")
                continue

            # Extract payload and CRC
            payload_crc_bits = decoded_bits[82:]

            if len(payload_crc_bits) < 16:
                raise ValueError("Not enough bits for CRC")

            # CRC is last 16 bits
            payload_bits = payload_crc_bits[:-16]
            crc_bits_received = payload_crc_bits[-16:]

            crc_received = sum((crc_bits_received[i] << i) for i in range(16))
            print(f"  Received CRC: 0x{crc_received:04x}")

            # Verify CRC
            message_bits = header_bits + payload_bits
            crc_calc = crc16(message_bits)
            print(f"  Calculated CRC: 0x{crc_calc:04x}")

            if crc_received == crc_calc:
                print(f"  CRC: PASS")
            else:
                print(f"  CRC: FAIL (mismatch)")

            # Try to decode payload (try both encodings)
            payload_text = None
            encoding_used = None

            # Try IA5 (7-bit ASCII)
            try:
                text_ia5 = decode_ia5_payload(payload_bits)
                # Check if result looks reasonable
                if text_ia5 and any(32 <= ord(c) <= 126 or c in '\r\n\t' for c in text_ia5[:10]):
                    payload_text = text_ia5
                    encoding_used = 'IA5 (ASCII)'
            except:
                pass

            # Try ITA2 if IA5 didn't work
            if not payload_text:
                try:
                    text_ita2 = decode_ita2_payload(payload_bits)
                    if text_ita2:
                        payload_text = text_ita2
                        encoding_used = 'ITA2 (Baudot)'
                except:
                    pass

            if payload_text:
                print(f"  Encoding: {encoding_used}")
                print(f"  Payload ({len(payload_bits)} bits):")
                print(f"    {payload_text[:200]}{'...' if len(payload_text) > 200 else ''}")

                results.append({
                    'mode': try_mode,
                    'msg_type': msg_type,
                    'priority': priority,
                    'source_imn': source_imn,
                    'dest_imn': dest_imn,
                    'msg_ref': msg_ref,
                    'seq_num': seq_num,
                    'crc_ok': crc_received == crc_calc,
                    'encoding': encoding_used,
                    'text': payload_text,
                })

        except Exception as e:
            print(f"  Decode error: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Output results
    if results:
        result = results[0]  # Use first successful result

        output_text = f"""INMARSAT-C Decoded Message
===========================

Data Rate: {result['mode']} bps
Message Type: 0x{result['msg_type']:02x}
Priority: {result['priority']}
Source IMN: {result['source_imn']:09d}
Dest IMN: {result['dest_imn']:09d}
Message Ref: {result['msg_ref']}
Sequence: {result['seq_num']}
CRC: {'PASS' if result['crc_ok'] else 'FAIL'}
Encoding: {result['encoding']}

Text:
------
{result['text']}
"""

        print("\n" + output_text)

        if output_file:
            with open(output_file, 'w') as f:
                f.write(output_text)
            print(f"Wrote {output_file}")

        return result['text']
    else:
        print("Failed to decode message")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Decode INMARSAT-C satellite messaging audio WAV to text.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Decode and display to console
  python3 inmarsat_decode.py recording.wav

  # Decode and save to file
  python3 inmarsat_decode.py recording.wav decoded.txt

  # Decode 600 bps signal
  python3 inmarsat_decode.py recording.wav --mode 600

  # Decode without FEC (for testing)
  python3 inmarsat_decode.py recording.wav --no-fec
        """
    )

    parser.add_argument('input', help='Input WAV file')
    parser.add_argument('output', nargs='?', help='Output text file (optional)')
    parser.add_argument('--mode', type=int, choices=[600, 1200],
                        help='Data rate in bps (default: auto-detect)')
    parser.add_argument('--no-fec', action='store_true', help='Disable FEC decoding')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    try:
        decode(
            args.input,
            mode=args.mode,
            use_fec=not args.no_fec,
            output_file=args.output,
        )
    except Exception as e:
        print(f"Decode error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
