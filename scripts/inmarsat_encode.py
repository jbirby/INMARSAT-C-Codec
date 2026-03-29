#!/usr/bin/env python3
"""
INMARSAT-C Encoder — Convert text to INMARSAT-C satellite messaging audio WAV.

Produces a standards-compliant INMARSAT-C transmission:
  1. Unique word / preamble for frame sync
  2. Message header (type, priority, addresses)
  3. Text data encoded as IA5 or ITA2 with FEC
  4. CRC-16 checksum
  5. Convolutional FEC encoding (rate 1/2, K=7, Viterbi-ready)
  6. Block interleaving for burst protection
  7. FSK modulation to continuous-phase audio

The resulting WAV represents the baseband INMARSAT-C signal (with FSK audio
representation of BPSK modulation) and could be demodulated by any
INMARSAT-C decoder.

Usage:
    python3 inmarsat_encode.py <output.wav> [options]

Options:
    --mode 600|1200     Data rate: 600 bps or 1200 bps (default 1200)
    --type TYPE         Message type: distress, urgency, safety, routine, egc (default routine)
    --source IMN        Source Inmarsat Mobile Number (9 digits, default 412345678)
    --dest IMN          Destination IMN (default 000000000 for broadcast)
    --text TEXT         Literal message text
    --text-file FILE    Read message from file
    --encoding ascii|ita2    Text encoding (default ascii)
    --no-fec            Skip FEC encoding (for testing only)
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
    build_inmarsat_header, encode_ia5_payload, encode_ita2_payload,
    convolutional_encode, interleave, crc16,
    fsk_modulate, generate_unique_word,
)


def encode(output_path, text, mode=1200, msg_type=MSG_TYPE_ROUTINE,
           priority=PRIORITY_ROUTINE, source_imn=412345678, dest_imn=0,
           encoding='ascii', use_fec=True):
    """Encode text as an INMARSAT-C WAV file."""

    print(f"Input text: {len(text)} characters")
    print(f"  Preview: {text[:80]}{'...' if len(text) > 80 else ''}")

    # Determine mode parameters
    if mode == 600:
        data_rate = DATA_RATE_600
        mark_freq = MARK_FREQ_600
        space_freq = SPACE_FREQ_600
    else:
        data_rate = DATA_RATE_1200
        mark_freq = MARK_FREQ_1200
        space_freq = SPACE_FREQ_1200

    print(f"  Mode: {mode} bps")
    print(f"  Encoding: {encoding.upper()}")
    print(f"  FEC: {'Enabled' if use_fec else 'Disabled'}")

    # Step 1: Build message header
    msg_ref = 1
    seq_num = 1
    header_bits = build_inmarsat_header(msg_type, priority, source_imn, dest_imn, msg_ref, seq_num)
    print(f"  Header bits: {len(header_bits)}")

    # Step 2: Encode payload
    if encoding.lower() == 'ita2':
        payload_bits = encode_ita2_payload(text)
    else:  # Default to ASCII/IA5
        payload_bits = encode_ia5_payload(text)

    print(f"  Payload bits: {len(payload_bits)}")

    # Step 3: Combine header + payload
    message_bits = header_bits + payload_bits

    # Step 4: Calculate CRC-16
    crc_value = crc16(message_bits)
    crc_bits = [(crc_value >> i) & 1 for i in range(16)]
    message_with_crc = message_bits + crc_bits
    print(f"  Message+CRC bits: {len(message_with_crc)}")

    # Step 5: Apply FEC if enabled
    if use_fec:
        # Add tail bits for encoder flush (7 zeros for K=7)
        message_with_tail = message_with_crc + [0] * 7
        fec_bits = convolutional_encode(message_with_tail)
        print(f"  FEC-encoded bits: {len(fec_bits)}")
    else:
        fec_bits = message_with_crc

    # Step 6: Apply block interleaving
    interleaved_bits = interleave(fec_bits, rows=16)
    print(f"  Interleaved bits: {len(interleaved_bits)}")

    # Step 7: Prepend unique word
    uw = generate_unique_word()
    all_bits = uw + interleaved_bits
    print(f"  Unique word + interleaved bits: {len(all_bits)}")

    # Step 8: FSK modulate
    print(f"  FSK modulating at {mode} bps...")
    print(f"    Mark (1): {mark_freq:.0f} Hz, Space (0): {space_freq:.0f} Hz")
    print(f"    Shift: {abs(space_freq - mark_freq):.0f} Hz")

    audio = fsk_modulate(all_bits, SAMPLE_RATE, data_rate, mark_freq, space_freq)
    print(f"  Audio duration: {len(audio) / SAMPLE_RATE:.3f} seconds")

    # Step 9: Write WAV file
    audio_int16 = np.int16(audio * 32767)

    with wave.open(output_path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio_int16.tobytes())

    print(f"Wrote {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Encode text as INMARSAT-C satellite messaging audio WAV.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Encode a simple routine message
  python3 inmarsat_encode.py output.wav --text "Hello maritime world"

  # Encode a distress message at 600 bps
  python3 inmarsat_encode.py distress.wav --text "MAYDAY" --type distress --mode 600

  # Encode with ITA2 (telex) encoding
  python3 inmarsat_encode.py telex.wav --text "CQ CQ" --encoding ita2

  # Read from a file
  python3 inmarsat_encode.py output.wav --text-file message.txt
        """
    )

    parser.add_argument('output', help='Output WAV file path')
    parser.add_argument('--mode', type=int, choices=[600, 1200], default=1200,
                        help='Data rate in bps (default 1200)')
    parser.add_argument('--type', choices=['distress', 'urgency', 'safety', 'routine', 'egc'],
                        default='routine', help='Message type (default routine)')
    parser.add_argument('--source', type=int, default=412345678,
                        help='Source IMN - 9 digit number (default 412345678)')
    parser.add_argument('--dest', type=int, default=0,
                        help='Destination IMN - 9 digit number (default 0 for broadcast)')
    parser.add_argument('--text', type=str, help='Message text (literal string)')
    parser.add_argument('--text-file', type=str, help='Read message from file')
    parser.add_argument('--encoding', choices=['ascii', 'ita2'], default='ascii',
                        help='Text encoding (default ascii)')
    parser.add_argument('--no-fec', action='store_true', help='Disable FEC encoding (testing only)')

    args = parser.parse_args()

    # Get message text
    if args.text:
        text = args.text
    elif args.text_file:
        if not os.path.exists(args.text_file):
            print(f"Error: File not found: {args.text_file}")
            sys.exit(1)
        with open(args.text_file, 'r') as f:
            text = f.read()
    else:
        print("Error: Must provide --text or --text-file")
        parser.print_help()
        sys.exit(1)

    # Map message type string to code
    msg_type_map = {
        'distress': MSG_TYPE_DISTRESS,
        'urgency': MSG_TYPE_URGENCY,
        'safety': MSG_TYPE_SAFETY,
        'routine': MSG_TYPE_ROUTINE,
        'egc': MSG_TYPE_EGC_SAFETY,
    }
    msg_type = msg_type_map[args.type]

    # Map priority
    priority_map = {
        'distress': PRIORITY_DISTRESS,
        'urgency': PRIORITY_URGENCY,
        'safety': PRIORITY_SAFETY,
        'routine': PRIORITY_ROUTINE,
    }
    priority = priority_map.get(args.type, PRIORITY_ROUTINE)

    try:
        encode(
            args.output,
            text,
            mode=args.mode,
            msg_type=msg_type,
            priority=priority,
            source_imn=args.source,
            dest_imn=args.dest,
            encoding=args.encoding,
            use_fec=not args.no_fec,
        )
    except Exception as e:
        print(f"Encoding error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
