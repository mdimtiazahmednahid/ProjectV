"""
Pure-Python ISO/IEC 18004 QR Code Generator (Versions 1..10, Error Correction Level L/M)
with PySide6 QImage / QPixmap rendering for Android 11+ Wireless Debugging QR Code Pairing:
  Format: WIFI:T:ADB;S:<service_name>;P:<password>;;
Zero third-party dependencies required — works offline in macOS .app and Windows .exe builds.
"""

from typing import Callable, List

# Capacities (data codewords) and EC codewords per block for Versions 1..10 at EC Level M (0b00)
# Using EC Level M (15% error recovery) makes phone camera scanning faster and more resilient on screens.
# Format: version -> (total_codewords, ec_codewords_per_block, num_blocks_group1, data_codewords_group1, num_blocks_group2, data_codewords_group2)
_VERSION_TABLE_M = {
    1: (26, 10, 1, 16, 0, 0),
    2: (44, 16, 1, 28, 0, 0),
    3: (70, 26, 1, 44, 0, 0),
    4: (100, 18, 2, 32, 0, 0),
    5: (134, 24, 2, 43, 0, 0),
    6: (172, 16, 4, 27, 0, 0),
    7: (196, 18, 4, 31, 0, 0),
    8: (242, 22, 2, 38, 2, 39),
    9: (292, 22, 3, 36, 2, 37),
    10: (346, 26, 4, 43, 1, 44),
}

_ALIGNMENT_POSITIONS = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

_MASK_FUNCTIONS: List[Callable[[int, int], bool]] = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: ((r // 2) + (c // 3)) % 2 == 0,
    lambda r, c: ((r * c) % 2) + ((r * c) % 3) == 0,
    lambda r, c: (((r * c) % 2) + ((r * c) % 3)) % 2 == 0,
    lambda r, c: (((r + c) % 2) + ((r * c) % 3)) % 2 == 0,
]

# GF(256) log/exp tables with primitive polynomial 0x11D
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(degree: int) -> List[int]:
    poly = [1]
    for i in range(degree):
        next_poly = [0] * (len(poly) + 1)
        factor = _GF_EXP[i]
        for j, coeff in enumerate(poly):
            next_poly[j] ^= coeff
            next_poly[j + 1] ^= _gf_mul(coeff, factor)
        poly = next_poly
    return poly


def _rs_encode(data_bytes: List[int], ec_len: int) -> List[int]:
    gen = _rs_generator_poly(ec_len)
    rem = [0] * ec_len
    for b in data_bytes:
        factor = b ^ rem[0]
        rem = rem[1:] + [0]
        if factor != 0:
            for j in range(ec_len):
                rem[j] ^= _gf_mul(gen[j + 1], factor)
    return rem


def _choose_version_m(payload_len: int) -> int:
    for ver in range(1, 11):
        _, _, b1, d1, b2, d2 = _VERSION_TABLE_M[ver]
        total_data_bytes = b1 * d1 + b2 * d2
        header_bytes = 2 if ver <= 9 else 3
        if payload_len + header_bytes <= total_data_bytes:
            return ver
    raise ValueError(f"QR payload too long ({payload_len} bytes; max supported is Version 10)")


def _encode_data_codewords(payload: bytes, ver: int) -> List[int]:
    _, ec_per_block, b1, d1, b2, d2 = _VERSION_TABLE_M[ver]
    total_data_codewords = b1 * d1 + b2 * d2

    bits: List[int] = []

    def _append_bits(val: int, count: int):
        for i in range(count - 1, -1, -1):
            bits.append((val >> i) & 1)

    # Mode indicator: Byte mode = 0100
    _append_bits(0b0100, 4)
    # Character count indicator: 8 bits for versions 1..9, 16 bits for 10+
    cc_bits = 8 if ver <= 9 else 16
    _append_bits(len(payload), cc_bits)

    for byte_val in payload:
        _append_bits(byte_val, 8)

    # Terminator (up to 4 zero bits)
    capacity_bits = total_data_codewords * 8
    term_len = min(4, capacity_bits - len(bits))
    _append_bits(0, term_len)

    # Pad to byte boundary
    while len(bits) % 8 != 0:
        bits.append(0)

    data_bytes = []
    for i in range(0, len(bits), 8):
        byte_val = 0
        for b in bits[i : i + 8]:
            byte_val = (byte_val << 1) | b
        data_bytes.append(byte_val)

    # Pad bytes 0xEC, 0x11
    pad_seq = (0xEC, 0x11)
    pad_idx = 0
    while len(data_bytes) < total_data_codewords:
        data_bytes.append(pad_seq[pad_idx % 2])
        pad_idx += 1

    # Split into blocks and compute Reed-Solomon EC for each block
    blocks_data: List[List[int]] = []
    blocks_ec: List[List[int]] = []
    offset = 0
    for _ in range(b1):
        blk = data_bytes[offset : offset + d1]
        offset += d1
        blocks_data.append(blk)
        blocks_ec.append(_rs_encode(blk, ec_per_block))
    for _ in range(b2):
        blk = data_bytes[offset : offset + d2]
        offset += d2
        blocks_data.append(blk)
        blocks_ec.append(_rs_encode(blk, ec_per_block))

    # Interleave data codewords, then EC codewords
    interleaved: List[int] = []
    max_d = max(d1, d2)
    for col in range(max_d):
        for blk in blocks_data:
            if col < len(blk):
                interleaved.append(blk[col])
    for col in range(ec_per_block):
        for ec_blk in blocks_ec:
            interleaved.append(ec_blk[col])

    return interleaved


def _place_finder_pattern(matrix: List[List[int]], reserved: List[List[bool]], r0: int, c0: int, size: int):
    for dr in range(-1, 8):
        for dc in range(-1, 8):
            r, c = r0 + dr, c0 + dc
            if 0 <= r < size and 0 <= c < size:
                if 0 <= dr <= 6 and 0 <= dc <= 6:
                    is_dark = (
                        dr in (0, 6)
                        or dc in (0, 6)
                        or (2 <= dr <= 4 and 2 <= dc <= 4)
                    )
                    matrix[r][c] = 1 if is_dark else 0
                else:
                    matrix[r][c] = 0
                reserved[r][c] = True


def _place_alignment_pattern(matrix: List[List[int]], reserved: List[List[bool]], r_center: int, c_center: int):
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            r, c = r_center + dr, c_center + dc
            is_dark = max(abs(dr), abs(dc)) in (0, 2)
            matrix[r][c] = 1 if is_dark else 0
            reserved[r][c] = True


def _compute_format_bits(ec_level_bits: int, mask_id: int) -> int:
    # EC Level M = 0b00, Level L = 0b01
    data = (ec_level_bits << 3) | mask_id
    rem = data << 10
    for i in range(4, -1, -1):
        if rem & (1 << (i + 10)):
            rem ^= 0x537 << i
    bits = ((data << 10) | rem) ^ 0x5412
    return bits


def _place_format_bits(matrix: List[List[int]], size: int, mask_id: int, ec_level_bits: int = 0b00):
    # bit 14 is MSB, bit 0 is LSB (ISO/IEC 18004 Figure 25)
    fmt = _compute_format_bits(ec_level_bits, mask_id)

    # Top-left copy: index i corresponds to bit i (0 = LSB at (0,8), 14 = MSB at (8,0))
    coords_tl = [
        (0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (7, 8), (8, 8),
        (8, 7), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0),
    ]
    for i, (r, c) in enumerate(coords_tl):
        matrix[r][c] = (fmt >> i) & 1

    # Second copy: bits 0..7 in row 8 from right edge (size-1 .. size-8)
    for i in range(8):
        matrix[8][size - 1 - i] = (fmt >> i) & 1
    # Bits 8..14 in col 8 from (size-7, 8) down to (size-1, 8)
    for i in range(8, 15):
        matrix[size - 15 + i][8] = (fmt >> i) & 1


def _penalty_score(matrix: List[List[int]]) -> int:
    size = len(matrix)
    score = 0

    # Rule 1: 5+ consecutive same-color modules in row/col
    for r in range(size):
        run_len = 1
        for c in range(1, size):
            if matrix[r][c] == matrix[r][c - 1]:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    for c in range(size):
        run_len = 1
        for r in range(1, size):
            if matrix[r][c] == matrix[r - 1][c]:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    # Rule 2: 2x2 blocks of same color
    for r in range(size - 1):
        for c in range(size - 1):
            v = matrix[r][c]
            if v == matrix[r][c + 1] == matrix[r + 1][c] == matrix[r + 1][c + 1]:
                score += 3

    return score


def generate_qr_matrix(text: str) -> List[List[int]]:
    """
    Generates a 2D boolean/int matrix (1 = dark module, 0 = light module) for `text`
    at Error Correction Level M with optimal mask selection.
    """
    payload = text.encode("utf-8")
    ver = _choose_version_m(len(payload))
    size = 17 + 4 * ver

    base_matrix = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    # 1. Finder patterns + separators
    _place_finder_pattern(base_matrix, reserved, 0, 0, size)
    _place_finder_pattern(base_matrix, reserved, 0, size - 7, size)
    _place_finder_pattern(base_matrix, reserved, size - 7, 0, size)

    # 2. Alignment patterns
    align_coords = _ALIGNMENT_POSITIONS[ver]
    for ar in align_coords:
        for ac in align_coords:
            if (ar == 6 and ac == 6) or (ar == 6 and ac == align_coords[-1]) or (ar == align_coords[-1] and ac == 6):
                continue
            _place_alignment_pattern(base_matrix, reserved, ar, ac)

    # 3. Timing patterns
    for i in range(8, size - 8):
        if not reserved[6][i]:
            base_matrix[6][i] = 1 if (i % 2 == 0) else 0
            reserved[6][i] = True
        if not reserved[i][6]:
            base_matrix[i][6] = 1 if (i % 2 == 0) else 0
            reserved[i][6] = True

    # 4. Dark module & reserve format information areas
    base_matrix[size - 8][8] = 1
    reserved[size - 8][8] = True
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    # 5. Encode data + EC bits
    codewords = _encode_data_codewords(payload, ver)
    bit_stream: List[int] = []
    for cw in codewords:
        for b in range(7, -1, -1):
            bit_stream.append((cw >> b) & 1)

    # 6. Evaluate all 8 masks and pick the lowest-penalty matrix
    best_matrix = None
    best_score = None
    for mask_id, mask_fn in enumerate(_MASK_FUNCTIONS):
        candidate = [row[:] for row in base_matrix]
        bit_idx = 0
        col = size - 1
        upward = True
        while col > 0:
            if col == 6:
                col -= 1
            row_iter = range(size - 1, -1, -1) if upward else range(size)
            for r in row_iter:
                for dc in (0, -1):
                    c = col + dc
                    if not reserved[r][c]:
                        val = bit_stream[bit_idx] if bit_idx < len(bit_stream) else 0
                        bit_idx += 1
                        if mask_fn(r, c):
                            val ^= 1
                        candidate[r][c] = val
            upward = not upward
            col -= 2

        _place_format_bits(candidate, size, mask_id=mask_id, ec_level_bits=0b00)
        sc = _penalty_score(candidate)
        if best_score is None or sc < best_score:
            best_score = sc
            best_matrix = candidate

    return best_matrix


def decode_qr_matrix(matrix: List[List[int]]) -> str:
    """
    Pure-Python verifier/decoder for matrices generated by `generate_qr_matrix`.
    Reads the format bits, unmasks the data modules, verifies Reed-Solomon EC, and returns the UTF-8 string.
    """
    size = len(matrix)
    ver = (size - 17) // 4
    coords_tl = [
        (0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (7, 8), (8, 8),
        (8, 7), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0),
    ]
    fmt = 0
    for i, (r, c) in enumerate(coords_tl):
        fmt |= (matrix[r][c] & 1) << i
    unmasked_fmt = fmt ^ 0x5412
    mask_id = (unmasked_fmt >> 10) & 0b111
    mask_fn = _MASK_FUNCTIONS[mask_id]

    # Build reserved map
    dummy = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]
    _place_finder_pattern(dummy, reserved, 0, 0, size)
    _place_finder_pattern(dummy, reserved, 0, size - 7, size)
    _place_finder_pattern(dummy, reserved, size - 7, 0, size)
    align_coords = _ALIGNMENT_POSITIONS[ver]
    for ar in align_coords:
        for ac in align_coords:
            if (ar == 6 and ac == 6) or (ar == 6 and ac == align_coords[-1]) or (ar == align_coords[-1] and ac == 6):
                continue
            _place_alignment_pattern(dummy, reserved, ar, ac)
    for i in range(8, size - 8):
        reserved[6][i] = True
        reserved[i][6] = True
    reserved[size - 8][8] = True
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    bits: List[int] = []
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        row_iter = range(size - 1, -1, -1) if upward else range(size)
        for r in row_iter:
            for dc in (0, -1):
                c = col + dc
                if not reserved[r][c]:
                    val = matrix[r][c]
                    if mask_fn(r, c):
                        val ^= 1
                    bits.append(val)
        upward = not upward
        col -= 2

    codewords = []
    for i in range(0, len(bits) - 7, 8):
        cw = 0
        for b in bits[i : i + 8]:
            cw = (cw << 1) | b
        codewords.append(cw)

    _, ec_per_block, b1, d1, b2, d2 = _VERSION_TABLE_M[ver]
    # De-interleave data blocks (for versions 1..3 b1=1, b2=0)
    blocks_data = [[] for _ in range(b1 + b2)]
    idx = 0
    max_d = max(d1, d2)
    for col_idx in range(max_d):
        for b_idx in range(b1 + b2):
            blk_len = d1 if b_idx < b1 else d2
            if col_idx < blk_len:
                blocks_data[b_idx].append(codewords[idx])
                idx += 1
    blocks_ec = [[] for _ in range(b1 + b2)]
    for _ in range(ec_per_block):
        for b_idx in range(b1 + b2):
            blocks_ec[b_idx].append(codewords[idx])
            idx += 1

    # Verify RS EC for every block
    data_bytes: List[int] = []
    for b_idx in range(b1 + b2):
        expected_ec = _rs_encode(blocks_data[b_idx], ec_per_block)
        if expected_ec != blocks_ec[b_idx]:
            raise ValueError("Reed-Solomon EC mismatch in QR matrix")
        data_bytes.extend(blocks_data[b_idx])

    data_bits: List[int] = []
    for byte_val in data_bytes:
        for b in range(7, -1, -1):
            data_bits.append((byte_val >> b) & 1)

    mode = 0
    for b in data_bits[:4]:
        mode = (mode << 1) | b
    if mode != 0b0100:
        raise ValueError(f"Unexpected QR mode: {mode}")
    cc_bits = 8 if ver <= 9 else 16
    char_count = 0
    for b in data_bits[4 : 4 + cc_bits]:
        char_count = (char_count << 1) | b
    out_bytes = bytearray()
    pos = 4 + cc_bits
    for _ in range(char_count):
        val = 0
        for b in data_bits[pos : pos + 8]:
            val = (val << 1) | b
        out_bytes.append(val)
        pos += 8
    return out_bytes.decode("utf-8")


def render_qr_pixmap(text: str, target_size_px: int = 220, quiet_zone: int = 4):
    """
    Renders a crisp black-on-white QR code QPixmap for PySide6 dialogs.
    """
    from PySide6.QtGui import QImage, QPainter, QColor, QPixmap
    from PySide6.QtCore import Qt

    matrix = generate_qr_matrix(text)
    n = len(matrix)
    total_modules = n + quiet_zone * 2
    scale = max(target_size_px // total_modules, 4)
    img_size = total_modules * scale

    img = QImage(img_size, img_size, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))

    painter = QPainter(img)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0))

    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                painter.drawRect(
                    (c + quiet_zone) * scale,
                    (r + quiet_zone) * scale,
                    scale,
                    scale,
                )
    painter.end()
    return QPixmap.fromImage(img)
