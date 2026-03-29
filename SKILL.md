---
name: inmarsat-c-codec
description: >
  Encode text into INMARSAT-C satellite messaging audio WAV files and decode
  INMARSAT-C recordings back into text. INMARSAT-C is a store-and-forward
  satellite messaging system for GMDSS maritime distress alerting, SafetyNET
  broadcasts, and ship-to-shore text messaging via Inmarsat L-band satellites.
  Supports 600/1200 bps with rate 1/2 convolutional FEC and block interleaving.
  Use this skill whenever the user mentions INMARSAT-C, Inmarsat, GMDSS,
  maritime satellite, SafetyNET, EGC, maritime distress, ship-to-shore messaging,
  Inmarsat Mobile Numbers, L-band satellite data, or wants to create/analyze
  INMARSAT-C WAV files. Covers encoding (text to WAV) and decoding (WAV to text).
---

# INMARSAT-C Codec

This skill converts between text and INMARSAT-C satellite messaging audio files.
INMARSAT-C is a mandatory Global Maritime Distress and Safety System (GMDSS)
component since 1999, providing store-and-forward text messaging, position
reporting, distress alerting, and SafetyNET maritime safety broadcasts via
geostationary Inmarsat satellites in the L-band (1.5–1.6 GHz).

Each message is encoded with convolutional forward error correction (rate 1/2,
constraint length 7), block interleaving for burst protection, and modulated as
FSK audio representing the BPSK baseband.

The generated WAV files are protocol-correct INMARSAT-C transmissions with
authentic message framing, FEC, and interleaving. They represent what the
baseband signal would sound like when converted to audio tones.

## Quick reference: the INMARSAT-C signal

An INMARSAT-C transmission consists of:

1. **Unique Word (UW)** — Known sync pattern (32+ bits) for frame synchronization.
   Allows the receiver to detect and lock onto the transmission start.

2. **Message Header** — Contains:
   - Message type (distress, urgency, safety, routine, EGC SafetyNET, etc.)
   - Priority level
   - Source and destination Inmarsat Mobile Numbers (IMN, 9 digits each)
   - Message reference number
   - Packet sequence number

3. **Payload** — Text data:
   - ITA2 (5-bit Baudot) encoding for telex-compatible messages
   - Or IA5 (7-bit ASCII) for data messages
   - Up to ~32 KB per message

4. **CRC-16** — Error detection checksum over header + payload.

5. **FEC (Forward Error Correction)** — Rate 1/2 convolutional code:
   - Constraint length K=7
   - Generator polynomials: G1=0o171 (0b1111001), G2=0o133 (0b1011011)
   - Viterbi decoder used for hard-decision decoding

6. **Block Interleaving** — Protects against burst errors:
   - Write by rows, read by columns
   - Typical: 16 rows × variable columns

7. **FSK Modulation** — Two-tone audio representation:
   - 600 bps mode: Mark=1200 Hz, Space=1800 Hz
   - 1200 bps mode: Mark=1200 Hz, Space=2400 Hz
   - Continuous-phase FSK

## Message types and priority levels

| Type     | Code | Use case             |
|----------|------|----------------------|
| Distress | 0x01 | Life-threatening emergency; highest priority |
| Urgency  | 0x02 | Urgent problem; mediate priority |
| Safety   | 0x03 | Safety information; low priority |
| Routine  | 0x04 | Normal messaging; lowest priority |
| EGC SafetyNET | 0x10 | Maritime safety broadcasts (MSI, weather, NAVAREA) |

## How to use this skill

There are three Python scripts in the `scripts/` directory. Use them rather than
writing INMARSAT-C logic from scratch.

### Encoding (text to INMARSAT-C WAV)

```bash
python3 <skill-path>/scripts/inmarsat_encode.py <output.wav> [options]
```

The encoder:
1. Reads text from a file (with `--text-file`) or command line (with `--text`)
2. Encodes as IA5 (7-bit ASCII) or ITA2 (5-bit Baudot)
3. Builds message header with type, priority, addresses, sequence numbers
4. Appends CRC-16 checksum
5. Applies rate 1/2 convolutional FEC encoding (Viterbi-ready)
6. Applies block interleaving
7. Prepends unique word for frame sync
8. FSK-modulates with continuous-phase onto audio
9. Writes a 16-bit mono WAV at 44100 Hz

Options:
- `--mode 600|1200` — Data rate: 600 bps (return) or 1200 bps (forward), default 1200
- `--type TYPE` — Message type: distress, urgency, safety, routine, egc (default routine)
- `--source IMN` — Source Inmarsat Mobile Number (9 digits, default 412345678)
- `--dest IMN` — Destination IMN (default 000000000 for broadcast)
- `--text TEXT` — Message text (literal string)
- `--text-file FILE` — Read message from text file
- `--encoding ascii|ita2` — Text encoding (default ascii)
- `--no-fec` — Skip FEC encoding (for testing only)

### Decoding (INMARSAT-C WAV to text)

```bash
python3 <skill-path>/scripts/inmarsat_decode.py <input.wav> [output.txt] [options]
```

The decoder:
1. Reads the WAV (any sample rate — resamples to 44100 if needed)
2. FSK-demodulates by measuring mark/space energy per bit period
3. Detects unique word for frame sync
4. De-interleaves the bit stream
5. Viterbi-decodes the FEC to recover original bits
6. Extracts header, verifies CRC
7. Decodes payload (auto-detects IA5 vs ITA2)
8. Displays message type, priority, addresses, text

Options:
- `--mode 600|1200` — Data rate (default: auto-detect by trying both)
- `--no-fec` — Skip FEC decoding

### Testing

```bash
python3 <skill-path>/scripts/inmarsat_test.py [--verbose]
```

Runs the full validation suite: convolutional encode/Viterbi roundtrips,
interleaving roundtrips, ITA2/IA5 encoding roundtrips, CRC verification,
full message encode/decode at 600 and 1200 bps, different message types,
and distress message formats.

### Typical workflow

**User wants to encode a maritime distress message as audio:**
1. Run the encoder with `--type distress` and distress text
2. Optionally verify by decoding the WAV back and comparing
3. Deliver the WAV file to the user

**User wants to decode an INMARSAT-C recording:**
1. Run the decoder on their WAV
2. Show them the decoded message, type, addresses
3. Note: real-world recordings may have noise or fading. The decoder works best on clean signals.

**User wants a roundtrip demonstration:**
1. Encode a test message to WAV
2. Decode WAV back to text
3. Compare the original and recovered text
4. Report the match quality

**User asks about INMARSAT-C format details:**
The quick reference above covers the key parameters. Main things people care
about: rate 1/2 convolutional FEC with K=7, block interleaving for burst
protection, 600/1200 bps modes, and message types (distress, safety, routine, etc.).

## Dependencies

The scripts use only `numpy` and the standard library `wave` module.
Install if needed:

```bash
pip install numpy --break-system-packages
```
