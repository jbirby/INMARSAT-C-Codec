# INMARSAT-C Codec

A software INMARSAT-C encoder and decoder that converts text to satellite messaging audio WAV files and back. Produces protocol-correct INMARSAT-C transmissions using rate 1/2 convolutional FEC, block interleaving, and FSK modulation — the same forward error correction and modulation used by real maritime satellite messaging systems.

Text goes in, INMARSAT-C audio comes out. Feed that audio back through the decoder and you get the original text. The WAV files represent the baseband INMARSAT-C signal (with FSK audio representation of BPSK modulation).

## What is INMARSAT-C?

INMARSAT-C is a mandatory Global Maritime Distress and Safety System (GMDSS) component since 1999. It provides:
- **Store-and-forward text messaging** over geostationary Inmarsat satellites
- **Maritime distress alerting** — Highest priority, life-threatening emergencies
- **SafetyNET broadcasts** — Maritime safety information (MSI), weather, navigation warnings
- **Position reporting** — Ship location updates
- **Shore-to-ship and ship-to-shore communication** via L-band (1.5–1.6 GHz)

The system operates at two data rates:
- **600 bps** — Ship-to-shore (return channel)
- **1200 bps** — Shore-to-ship (forward channel)

## How It Works

The encoder converts each text character to IA5 (7-bit ASCII) or ITA2 (5-bit Baudot) code, builds a message header with type and priority, appends a CRC-16 checksum, applies rate 1/2 convolutional FEC encoding (Viterbi-ready), applies block interleaving for burst protection, and modulates the bits as FSK audio tones.

The decoder reverses the process: demodulates the FSK audio, finds the unique word for frame sync, de-interleaves, Viterbi-decodes the FEC, verifies the CRC, and decodes the text payload.

### Signal Structure

```
[Unique Word] [Header] [Payload + CRC] [FEC Encoding] [Interleaving] → [FSK Modulation to Audio]
   32 bits      82 bits   Variable      Rate 1/2        Block         Continuous-phase
                                        Convolution    16 rows      1200 Hz or 2400 Hz

Message Header (82 bits):
  [Type: 8] [Priority: 2] [Source IMN: 32] [Dest IMN: 32] [Msg Ref: 8] [Seq: 8]

Example payload (IA5 ASCII):
  "Hello" = 5 chars × 7 bits/char = 35 bits
  With CRC-16: 35 + 16 = 51 bits total
  After FEC (rate 1/2): 102 bits
  After interleaving: 102 bits (reshaped)
  After FSK modulation at 1200 bps: ~85 ms of audio
```

### Parameters

| Parameter | 600 bps Mode | 1200 bps Mode | Notes |
|-----------|--------------|---------------|-------|
| Data rate | 600 bps | 1200 bps | Ship-to-shore vs. shore-to-ship |
| Modulation | FSK (BPSK on RF) | FSK (BPSK on RF) | Mark/Space audio representation |
| Mark (binary 1) | 1200 Hz | 1200 Hz | Frequency for bit = 1 |
| Space (binary 0) | 1800 Hz | 2400 Hz | Frequency for bit = 0 |
| Shift | 600 Hz | 1200 Hz | Mark - Space separation |
| FEC | Rate 1/2, K=7 | Rate 1/2, K=7 | Convolutional code, Viterbi decoder |
| Interleaving | 16 rows | 16 rows | Block interleaver (write rows, read cols) |
| CRC | CRC-16 (0x1021) | CRC-16 (0x1021) | Error detection |
| Sample rate | 44100 Hz | 44100 Hz | CD-quality audio |
| Audio format | 16-bit mono WAV | 16-bit mono WAV | Standard WAV file |

### Message Types and Priority

| Type | Code | Priority | Use Case |
|------|------|----------|----------|
| Distress | 0x01 | 3 (highest) | Life-threatening emergency; immediate routing |
| Urgency | 0x02 | 2 | Urgent problem requiring prompt attention |
| Safety | 0x03 | 1 | Safety information; low priority |
| Routine | 0x04 | 0 (lowest) | Normal messaging; standard routing |
| EGC SafetyNET | 0x10 | Broadcast | Maritime safety broadcasts (MSI, weather) |

## Installation

Requires Python 3.7+ and NumPy:

```bash
pip install numpy
```

No other dependencies. The scripts use only `numpy` and `wave` from the standard library.

## Usage

### Encode text to INMARSAT-C audio

```bash
python3 scripts/inmarsat_encode.py <output.wav> [options]
```

Examples:

```bash
# Encode a simple routine message at 1200 bps
python3 scripts/inmarsat_encode.py message.wav --text "Hello maritime world"

# Encode a distress message at 600 bps (return channel)
python3 scripts/inmarsat_encode.py distress.wav --text "MAYDAY MAYDAY" \
  --type distress --mode 600

# Encode with ITA2 (telex) encoding
python3 scripts/inmarsat_encode.py telex.wav --text "CQ CQ" --encoding ita2

# Read message from a file
python3 scripts/inmarsat_encode.py output.wav --text-file message.txt

# Specify IMNs (Inmarsat Mobile Numbers)
python3 scripts/inmarsat_encode.py output.wav --text "Test" \
  --source 412345678 --dest 987654321

# Encode with FEC disabled (for testing raw payload)
python3 scripts/inmarsat_encode.py output.wav --text "Test" --no-fec
```

Options:
- `--mode 600|1200` — Data rate in bps (default 1200)
- `--type TYPE` — Message type: distress, urgency, safety, routine, egc (default routine)
- `--source IMN` — Source Inmarsat Mobile Number, 9 digits (default 412345678)
- `--dest IMN` — Destination IMN, 9 digits (default 0 for broadcast)
- `--text TEXT` — Message text as literal string
- `--text-file FILE` — Read message from text file
- `--encoding ascii|ita2` — Text encoding: ascii (default) or ita2 (telex)
- `--no-fec` — Disable FEC encoding (testing only)

### Decode INMARSAT-C audio to text

```bash
python3 scripts/inmarsat_decode.py <input.wav> [output.txt] [options]
```

Examples:

```bash
# Decode and display to console
python3 scripts/inmarsat_decode.py recording.wav

# Decode and save to file
python3 scripts/inmarsat_decode.py recording.wav decoded.txt

# Decode 600 bps signal
python3 scripts/inmarsat_decode.py recording.wav --mode 600

# Decode without FEC (for testing or corrupted FEC)
python3 scripts/inmarsat_decode.py recording.wav --no-fec

# Auto-detect data rate (tries 1200 bps, then 600 bps)
python3 scripts/inmarsat_decode.py recording.wav
```

Options:
- `--mode 600|1200` — Data rate in bps (default: auto-detect)
- `--no-fec` — Disable FEC decoding

Output shows:
- Data rate (detected or specified)
- Message type and priority
- Source and destination Inmarsat Mobile Numbers
- Message reference and sequence numbers
- CRC verification (PASS/FAIL)
- Text encoding used (IA5 ASCII or ITA2 Baudot)
- Decoded message text

### Testing

```bash
python3 scripts/inmarsat_test.py [--verbose]
```

Runs the full validation suite:
1. Convolutional encode/Viterbi decode roundtrips (clean and with errors)
2. Block interleave/deinterleave roundtrips
3. ITA2 Baudot text encoding roundtrips
4. IA5 ASCII text encoding roundtrips
5. CRC-16 calculation and verification
6. Message header construction/parsing
7. FSK modulation/demodulation roundtrips
8. Unique word generation and detection
9. Full message encode/decode at 1200 bps
10. Full message encode/decode at 600 bps
11. Distress message format

Output: `Test Results: N/M PASSED` with pass/fail for each test.

## Examples

### Send a maritime safety message

```bash
# Create and encode a safety message
python3 scripts/inmarsat_encode.py safety.wav \
  --type safety \
  --text "STORM WARNING: SEVERE WEATHER EXPECTED IN AREA" \
  --source 412345678 \
  --dest 0

# Play the audio or verify by decoding
python3 scripts/inmarsat_decode.py safety.wav
```

### Encode and decode a distress alert

```bash
# Encode distress (highest priority)
python3 scripts/inmarsat_encode.py distress.wav \
  --type distress \
  --text "MAYDAY POSITION 45.3N 75.5W" \
  --mode 600 \
  --source 123456789

# Decode and verify
python3 scripts/inmarsat_decode.py distress.wav decoded_distress.txt
cat decoded_distress.txt
```

### Roundtrip test

```bash
# Encode
python3 scripts/inmarsat_encode.py test.wav --text "TEST MESSAGE"

# Decode
python3 scripts/inmarsat_decode.py test.wav

# Compare outputs
```

## Technical Details

### Convolutional FEC (Rate 1/2, K=7)

- **Generator polynomials:** G1 = 0o171 (0b1111001), G2 = 0o133 (0b1011011)
- **Constraint length:** K=7 (7-bit shift register)
- **States:** 64 (2^(K-1))
- **Decoding:** Hard-decision Viterbi algorithm with traceback
- **Capability:** Corrects random bit errors in the coded stream

### Block Interleaving

- **Method:** Write by rows, read by columns
- **Structure:** 16 rows × variable columns
- **Purpose:** Spreads burst errors across multiple FEC frames for better correction
- **Roundtrip:** De-interleave reverses the process deterministically

### FSK Modulation

- **Type:** Continuous-phase FSK (phase continuous between bit periods)
- **600 bps:** Mark=1200 Hz, Space=1800 Hz (600 Hz shift)
- **1200 bps:** Mark=1200 Hz, Space=2400 Hz (1200 Hz shift)
- **Modulation index:** Chosen for efficient spectral utilization

### Unique Word / Preamble

- **Pattern:** 32-bit synchronization sequence (0xFEDCBA98)
- **Detection:** Correlation-based search in received bits
- **Purpose:** Allows decoder to lock onto frame start and determine bit timing

## Limitations

- **Noise:** Performance degrades significantly with SNR below ~6 dB
- **Fading:** Rapid fading (e.g., from multipath) can cause bit errors
- **Sample rate:** Requires resampling if input WAV is not 44100 Hz
- **Message length:** Limited by payload size (~32 KB max per message, though typical messages are much shorter)
- **Latency:** Store-and-forward nature means messages are not real-time (typical delays: minutes to hours)

## File Structure

```
inmarsat-c/
├── README.md                      # This file
├── SKILL.md                       # Skill metadata and documentation
└── scripts/
    ├── inmarsat_common.py         # Shared constants and functions
    ├── inmarsat_encode.py         # CLI encoder (text → WAV)
    ├── inmarsat_decode.py         # CLI decoder (WAV → text)
    └── inmarsat_test.py           # Test suite
```

## References

- INMARSAT-C Handbook (INMARSAT)
- ITU-T Recommendation X.25 (packet-switched protocol)
- CCIR 465 (satellite communication standards)
- ITA2 / Baudot character tables (5-bit telex encoding)
- IA5 (ISO/IEC 646, 7-bit ASCII variant)
- Viterbi algorithm (error correction)
- Block interleaving (burst error protection)
