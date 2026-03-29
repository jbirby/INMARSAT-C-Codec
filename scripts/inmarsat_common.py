#!/usr/bin/env python3
"""
Shared module for INMARSAT-C encoding/decoding.

Contains:
  - Convolutional encoder/Viterbi decoder (rate 1/2, K=7)
  - Block interleaver/deinterleaver
  - Message header construction and parsing
  - ITA2 (Baudot) and IA5 (ASCII) text encoding
  - CRC-16 calculation
  - FSK modulation/demodulation
  - Unique word generation and detection

INMARSAT-C signal structure:
  [Unique Word] [Header] [Payload] [CRC-16] [FEC tail] → [Interleave] → [FSK modulate to audio]

Protocol notes:
  - Store-and-forward satellite messaging system (GMDSS mandatory since 1999)
  - L-band transmission (1.5-1.6 GHz, represented as FSK audio)
  - Data rates: 600 bps (ship-to-shore/return) or 1200 bps (shore-to-ship/forward)
  - Modulation: BPSK over RF; represented as FSK in audio (Mark=1200 Hz for 600 bps, etc.)
  - FEC: Rate 1/2 convolutional, K=7, polynomials G1=0o171, G2=0o133
  - Interleaving: Block interleaver (write by rows, read by columns)
  - Message types: distress, urgency, safety, routine, EGC SafetyNET
"""

import numpy as np
import struct

# ============================================================================
# Constants
# ============================================================================

SAMPLE_RATE = 44100

# Data rates (bits per second)
DATA_RATE_600 = 600
DATA_RATE_1200 = 1200

# FSK frequencies for each mode
# 600 bps mode: Mark=1200 Hz, Space=1800 Hz (600 Hz shift)
MARK_FREQ_600 = 1200.0
SPACE_FREQ_600 = 1800.0

# 1200 bps mode: Mark=1200 Hz, Space=2400 Hz (1200 Hz shift)
MARK_FREQ_1200 = 1200.0
SPACE_FREQ_1200 = 2400.0

# Message types (in header)
MSG_TYPE_DISTRESS = 0x01
MSG_TYPE_URGENCY = 0x02
MSG_TYPE_SAFETY = 0x03
MSG_TYPE_ROUTINE = 0x04
MSG_TYPE_EGC_SAFETY = 0x10

# Priority levels
PRIORITY_DISTRESS = 3
PRIORITY_URGENCY = 2
PRIORITY_SAFETY = 1
PRIORITY_ROUTINE = 0

# Convolutional encoder polynomials (K=7, rate 1/2)
G1_POLY = 0o171  # 0b1111001
G2_POLY = 0o133  # 0b1011011
K = 7

# ============================================================================
# ITA2 Baudot Code Tables (for telex-compatible messages)
# ============================================================================

# ITA2 code -> character (LTRS shift = letters/common)
ITA2_LTRS = {
    0x00: '\x00',   # NULL / Blank
    0x01: 'E',
    0x02: '\n',     # Line Feed
    0x03: 'A',
    0x04: ' ',      # Space
    0x05: 'S',
    0x06: 'I',
    0x07: 'U',
    0x08: '\r',     # Carriage Return
    0x09: 'D',
    0x0A: 'R',
    0x0B: 'J',
    0x0C: 'N',
    0x0D: 'F',
    0x0E: 'C',
    0x0F: 'K',
    0x10: 'T',
    0x11: 'Z',
    0x12: 'L',
    0x13: 'W',
    0x14: 'H',
    0x15: 'Y',
    0x16: 'P',
    0x17: 'Q',
    0x18: 'O',
    0x19: 'B',
    0x1A: 'G',
    0x1B: None,     # FIGS shift marker
    0x1C: 'M',
    0x1D: 'X',
    0x1E: 'V',
    0x1F: None,     # LTRS shift marker
}

# ITA2 code -> figure (FIGS shift = figures/symbols)
ITA2_FIGS = {
    0x00: '\x00',
    0x01: '3',
    0x02: '\n',
    0x03: '-',
    0x04: ' ',
    0x05: '?',
    0x06: '8',
    0x07: '7',
    0x08: '\r',
    0x09: '$',
    0x0A: '4',
    0x0B: '\x07',   # BELL
    0x0C: ',',
    0x0D: '!',
    0x0E: '(',
    0x0F: ')',
    0x10: '5',
    0x11: '+',
    0x12: ')',
    0x13: '2',
    0x14: '#',
    0x15: '6',
    0x16: '0',
    0x17: '1',
    0x18: '9',
    0x19: '?',
    0x1A: '&',
    0x1B: None,     # FIGS shift marker
    0x1C: '/',
    0x1D: '=',
    0x1E: '/',
    0x1F: None,     # LTRS shift marker
}

# Reverse lookup: character -> ITA2 code
CHAR_TO_ITA2 = {}
for code, char in ITA2_LTRS.items():
    if char is not None and char not in CHAR_TO_ITA2:
        CHAR_TO_ITA2[char] = (code, 'LTRS')

for code, char in ITA2_FIGS.items():
    if char is not None and char not in CHAR_TO_ITA2:
        CHAR_TO_ITA2[char] = (code, 'FIGS')

# IA5 (7-bit ASCII) table
IA5_TABLE = {}
for i in range(128):
    IA5_TABLE[i] = chr(i)

CHAR_TO_IA5 = {chr(i): i for i in range(128)}

# ============================================================================
# Convolutional Encoder (Rate 1/2, K=7)
# ============================================================================

def convolutional_encode(bits):
    """
    Encode a bit stream with rate 1/2 convolutional code (K=7).

    Args:
        bits: list or array of input bits (0 or 1)

    Returns:
        Encoded bits (2 output bits per input bit)

    Polynomials:
        G1 = 0o171 = 0b1111001
        G2 = 0o133 = 0b1011011

    Each input bit feeds into a 7-bit shift register.
    Two output bits per input bit (G1 and G2 outputs).
    """
    bits = list(bits)
    state = 0  # 7-bit shift register
    output = []

    for bit in bits:
        # Shift register: newest bit goes to MSB
        state = ((state << 1) | bit) & 0x7F  # Keep only 7 bits

        # XOR taps for G1
        g1_out = bin(state & G1_POLY).count('1') % 2

        # XOR taps for G2
        g2_out = bin(state & G2_POLY).count('1') % 2

        output.append(g1_out)
        output.append(g2_out)

    return output


def viterbi_decode(received_bits, max_errors=None):
    """
    Viterbi decoder for rate 1/2 convolutional code (K=7).
    Hard-decision decoding (treats 0/1 bits directly, no soft values).

    Args:
        received_bits: list of received bits (should be 2*N bits for N data bits)
        max_errors: optional max bit errors to accept (None = no limit)

    Returns:
        Decoded bit stream (original data bits)

    The state machine has 64 states (2^(K-1) = 2^6).
    """
    if len(received_bits) % 2 != 0:
        # Pad to even length
        received_bits = list(received_bits) + [0]

    received_bits = list(received_bits)
    n_states = 1 << (K - 1)  # 2^(K-1) = 64 states

    # Path tracking: store (metric, path_bits)
    path_metrics = [float('inf')] * n_states
    path_metrics[0] = 0
    path_bits = [[] for _ in range(n_states)]

    # Process pairs of received bits
    for i in range(0, len(received_bits), 2):
        received_pair = (received_bits[i], received_bits[i + 1] if i + 1 < len(received_bits) else 0)
        new_metrics = [float('inf')] * n_states
        new_paths = [[] for _ in range(n_states)]

        for prev_state in range(n_states):
            if path_metrics[prev_state] == float('inf'):
                continue

            for input_bit in (0, 1):
                # Compute next state and output
                shift_reg = (prev_state << 1) | input_bit
                next_state = (shift_reg & 0x3F)  # Lower 6 bits become next state

                # Compute output bits
                g1_out = bin(shift_reg & G1_POLY).count('1') % 2
                g2_out = bin(shift_reg & G2_POLY).count('1') % 2

                # Hamming distance to received pair
                error_count = 0
                if g1_out != received_pair[0]:
                    error_count += 1
                if g2_out != received_pair[1]:
                    error_count += 1

                metric = path_metrics[prev_state] + error_count

                if metric < new_metrics[next_state]:
                    new_metrics[next_state] = metric
                    new_paths[next_state] = path_bits[prev_state] + [input_bit]

        path_metrics = new_metrics
        path_bits = new_paths

    # Find state with best metric
    best_state = min(range(n_states), key=lambda s: path_metrics[s])
    best_metric = path_metrics[best_state]

    if max_errors is not None and best_metric > max_errors:
        raise ValueError(f"Viterbi decoder failed: {best_metric} errors (threshold {max_errors})")

    return path_bits[best_state]


# ============================================================================
# Block Interleaver/Deinterleaver
# ============================================================================

def interleave(bits, rows=16):
    """
    Block interleave a bit stream.
    Write by rows, read by columns.

    Args:
        bits: list of bits to interleave
        rows: number of rows (default 16)

    Returns:
        Interleaved bits
    """
    bits = list(bits)
    cols = (len(bits) + rows - 1) // rows  # Ceiling division

    # Pad to fill matrix
    padded = bits + [0] * (rows * cols - len(bits))

    # Write by rows
    matrix = [padded[i*cols:(i+1)*cols] for i in range(rows)]

    # Read by columns
    interleaved = []
    for c in range(cols):
        for r in range(rows):
            if c < len(matrix[r]):
                interleaved.append(matrix[r][c])

    return interleaved[:len(bits)]


def deinterleave(bits, rows=16):
    """
    Block deinterleave a bit stream (reverse of interleave).
    Interleave writes by rows, reads by columns.
    Deinterleave writes by columns, reads by rows.

    Args:
        bits: list of bits to deinterleave
        rows: number of rows (must match encoding)

    Returns:
        Deinterleaved bits
    """
    bits = list(bits)
    cols = (len(bits) + rows - 1) // rows

    # Pad to fill matrix
    padded = bits + [0] * (rows * cols - len(bits))

    # Write by columns (reverse the read-by-columns operation)
    matrix = [[0] * cols for _ in range(rows)]
    idx = 0
    for c in range(cols):
        for r in range(rows):
            if idx < len(padded):
                matrix[r][c] = padded[idx]
                idx += 1

    # Read by rows (reverse the write-by-rows operation)
    deinterleaved = []
    for r in range(rows):
        for c in range(cols):
            deinterleaved.append(matrix[r][c])

    return deinterleaved[:len(bits)]


# ============================================================================
# Message Header Construction/Parsing
# ============================================================================

def build_inmarsat_header(msg_type, priority, source_imn, dest_imn, msg_ref, seq_num):
    """
    Build an INMARSAT-C message header as bits.

    Header format (82 bits total):
      - Message type (8 bits)
      - Priority (2 bits)
      - Source IMN (32 bits, 9-digit number encoded)
      - Destination IMN (32 bits)
      - Message reference (4 bits)
      - Sequence number (4 bits)

    Args:
        msg_type: message type code (0x01-0x04, 0x10)
        priority: priority level (0-3)
        source_imn: 9-digit IMN string or number
        dest_imn: 9-digit IMN string or number
        msg_ref: message reference number (0-15)
        seq_num: sequence number (0-15)

    Returns:
        List of header bits (82 bits)
    """
    if isinstance(source_imn, str):
        source_imn = int(source_imn)
    if isinstance(dest_imn, str):
        dest_imn = int(dest_imn)

    bits = []

    # Message type (8 bits)
    bits.extend([(msg_type >> i) & 1 for i in range(8)])

    # Priority (2 bits)
    bits.extend([(priority >> i) & 1 for i in range(2)])

    # Source IMN (32 bits)
    bits.extend([(source_imn >> i) & 1 for i in range(32)])

    # Destination IMN (32 bits)
    bits.extend([(dest_imn >> i) & 1 for i in range(32)])

    # Message reference (4 bits)
    bits.extend([(msg_ref >> i) & 1 for i in range(4)])

    # Sequence number (4 bits)
    bits.extend([(seq_num >> i) & 1 for i in range(4)])

    return bits


def parse_inmarsat_header(bits):
    """
    Parse an INMARSAT-C message header from bits.

    Returns:
        Tuple of (msg_type, priority, source_imn, dest_imn, msg_ref, seq_num)
    """
    bits = list(bits)

    # Message type (8 bits)
    msg_type = sum((bits[i] << i) for i in range(8))

    # Priority (2 bits)
    priority = sum((bits[8 + i] << i) for i in range(2))

    # Source IMN (32 bits)
    source_imn = sum((bits[10 + i] << i) for i in range(32))

    # Destination IMN (32 bits)
    dest_imn = sum((bits[42 + i] << i) for i in range(32))

    # Message reference (4 bits)
    msg_ref = sum((bits[74 + i] << i) for i in range(4))

    # Sequence number (4 bits)
    seq_num = sum((bits[78 + i] << i) for i in range(4))

    return (msg_type, priority, source_imn, dest_imn, msg_ref, seq_num)


# ============================================================================
# Text Encoding
# ============================================================================

def encode_ia5_payload(text):
    """
    Encode text as IA5 (7-bit ASCII).

    Args:
        text: string to encode

    Returns:
        List of bits (7 bits per character, LSB first)
    """
    bits = []
    for char in text:
        if char not in CHAR_TO_IA5:
            char = '?'
        code = CHAR_TO_IA5[char]
        for i in range(7):
            bits.append((code >> i) & 1)
    return bits


def decode_ia5_payload(bits):
    """
    Decode IA5 bits back to text.

    Args:
        bits: list of bits

    Returns:
        Decoded string
    """
    bits = list(bits)
    text = []
    for i in range(0, len(bits) - 6, 7):
        code = sum((bits[i + j] << j) for j in range(7))
        if 0 <= code < 128:
            text.append(chr(code))
        else:
            text.append('?')
    return ''.join(text)


def encode_ita2_payload(text):
    """
    Encode text as ITA2 Baudot (5-bit) with automatic LTRS/FIGS shifts.

    Args:
        text: string to encode

    Returns:
        List of bits (5 bits per character, LSB first)
    """
    text = text.upper()
    bits = []
    current_shift = 'LTRS'

    for char in text:
        if char not in CHAR_TO_ITA2:
            # Try to find close match
            if char.lower() in CHAR_TO_ITA2:
                char = char.lower()
            else:
                char = ' '

        code, needed_shift = CHAR_TO_ITA2[char]

        # Insert shift code if needed
        if needed_shift != current_shift:
            if needed_shift == 'FIGS':
                shift_code = 0x1B
            else:
                shift_code = 0x1F

            for i in range(5):
                bits.append((shift_code >> i) & 1)
            current_shift = needed_shift

        # Add character code
        for i in range(5):
            bits.append((code >> i) & 1)

    return bits


def decode_ita2_payload(bits):
    """
    Decode ITA2 bits back to text.

    Args:
        bits: list of bits

    Returns:
        Decoded string
    """
    bits = list(bits)
    text = []
    current_shift = 'LTRS'

    for i in range(0, len(bits) - 4, 5):
        code = sum((bits[i + j] << j) for j in range(5))

        if code == 0x1B:  # FIGS shift
            current_shift = 'FIGS'
        elif code == 0x1F:  # LTRS shift
            current_shift = 'LTRS'
        else:
            if current_shift == 'LTRS':
                char = ITA2_LTRS.get(code, '?')
            else:
                char = ITA2_FIGS.get(code, '?')

            if char is not None:
                text.append(char)

    return ''.join(text)


# ============================================================================
# CRC-16
# ============================================================================

def crc16(data):
    """
    Calculate CRC-16 (CCITT polynomial 0x1021).

    Args:
        data: bytes or list of bits

    Returns:
        16-bit CRC value
    """
    if isinstance(data, list):
        # Convert bits to bytes
        data_bytes = []
        for i in range(0, len(data), 8):
            byte = sum((data[i + j] << j) for j in range(min(8, len(data) - i)))
            data_bytes.append(byte)
        data = bytes(data_bytes)

    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            crc <<= 1
            if crc & 0x10000:
                crc ^= 0x1021
            crc &= 0xFFFF
    return crc


# ============================================================================
# FSK Modulation/Demodulation
# ============================================================================

def fsk_modulate(bits, sample_rate, data_rate, mark_freq, space_freq):
    """
    FSK modulate a bit stream to continuous-phase audio.

    Args:
        bits: list of bits (0 or 1)
        sample_rate: samples per second (default 44100)
        data_rate: bits per second (600 or 1200)
        mark_freq: frequency for bit 1
        space_freq: frequency for bit 0

    Returns:
        Numpy array of audio samples (float, -1 to +1)
    """
    bits = list(bits)
    samples_per_bit = sample_rate // data_rate

    # Build bit stream with marks
    audio = []
    phase = 0.0

    for bit in bits:
        freq = mark_freq if bit == 1 else space_freq

        # Generate samples for this bit period
        for sample_idx in range(samples_per_bit):
            t = sample_idx / sample_rate
            phase_increment = 2.0 * np.pi * freq * t
            sample = np.sin(phase + phase_increment)
            audio.append(sample)

        # Update phase for continuous phase
        total_phase_increment = 2.0 * np.pi * freq * (samples_per_bit / sample_rate)
        phase += total_phase_increment
        phase = phase % (2.0 * np.pi)

    return np.array(audio, dtype=np.float32)


def fsk_demodulate(audio, sample_rate, data_rate, mark_freq, space_freq):
    """
    FSK demodulate audio to extract bits using Goertzel-like energy detection.

    Args:
        audio: numpy array of audio samples
        sample_rate: samples per second
        data_rate: bits per second (600 or 1200)
        mark_freq: frequency for bit 1
        space_freq: frequency for bit 0

    Returns:
        List of demodulated bits (0 or 1)
    """
    audio = np.array(audio, dtype=np.float32)
    samples_per_bit = int(sample_rate / data_rate)

    bits = []
    for bit_idx in range(len(audio) // samples_per_bit):
        start = bit_idx * samples_per_bit
        end = start + samples_per_bit
        segment = audio[start:end]

        # Measure energy at mark and space frequencies using sine/cosine correlation
        mark_i = 0.0
        mark_q = 0.0
        space_i = 0.0
        space_q = 0.0

        for i, sample in enumerate(segment):
            t = (start + i) / sample_rate
            mark_phase = 2.0 * np.pi * mark_freq * t
            space_phase = 2.0 * np.pi * space_freq * t

            # In-phase and quadrature correlation
            mark_i += sample * np.cos(mark_phase)
            mark_q += sample * np.sin(mark_phase)
            space_i += sample * np.cos(space_phase)
            space_q += sample * np.sin(space_phase)

        # Calculate energy (magnitude squared)
        mark_energy = mark_i * mark_i + mark_q * mark_q
        space_energy = space_i * space_i + space_q * space_q

        # Decide based on which has more energy
        bit = 1 if mark_energy > space_energy else 0
        bits.append(bit)

    return bits


# ============================================================================
# Unique Word / Preamble
# ============================================================================

def generate_unique_word():
    """
    Generate a known synchronization pattern (unique word).
    Using a 32-bit pattern for reliable sync detection.

    Returns:
        List of 32 bits
    """
    # Using alternating pattern for good autocorrelation
    pattern = 0xFEDCBA98
    bits = [(pattern >> i) & 1 for i in range(32)]
    return bits


def find_unique_word(bits, uw_pattern=None):
    """
    Find the unique word in a bit stream.

    Args:
        bits: list of bits to search
        uw_pattern: expected UW pattern (default: standard UW)

    Returns:
        Index where UW starts, or -1 if not found
    """
    if uw_pattern is None:
        uw_pattern = generate_unique_word()

    uw_len = len(uw_pattern)
    for i in range(len(bits) - uw_len):
        if bits[i:i + uw_len] == uw_pattern:
            return i
    return -1
