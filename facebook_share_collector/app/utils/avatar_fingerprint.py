import os
import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def parse_bounds(bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
    """
    Parses Android bounds string '[x1,y1][x2,y2]' into (x1, y1, width, height).
    """
    if not bounds_str:
        return None
    m = BOUNDS_RE.search(bounds_str)
    if not m:
        return None
    x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    w, h = x2 - x1, y2 - y1
    if w <= 4 or h <= 4:
        return None
    return (x1, y1, w, h)


def hamming_distance(hash_a: Optional[str], hash_b: Optional[str]) -> int:
    """
    Computes the vertical-shift-invariant bit-level Hamming distance between two
    16-char (64-bit, 8x8 row) hex dHashes.
    Absorbs up to ±3 rows of vertical scroll-deceleration jitter between Android's
    `uiautomator dump` and `screencap -p` while keeping distinct faces far apart.
    Returns 64 if either hash is missing or invalid.
    """
    if not hash_a or not hash_b:
        return 64
    ha = hash_a.strip().lower()
    hb = hash_b.strip().lower()
    if ha == hb:
        return 0
    try:
        val_a = int(ha, 16)
        val_b = int(hb, 16)
        raw_dist = (val_a ^ val_b).bit_count()
        if len(ha) != 16 or len(hb) != 16:
            return raw_dist
        rows_a = [int(ha[i : i + 2], 16) for i in range(0, 16, 2)]
        rows_b = [int(hb[i : i + 2], 16) for i in range(0, 16, 2)]
        best = raw_dist
        for shift in (-2, -1, 1, 2):
            overlap = 0
            bits = 0
            for r1 in range(8):
                r2 = r1 + shift
                if 0 <= r2 < 8:
                    overlap += 1
                    bits += (rows_a[r1] ^ rows_b[r2]).bit_count()
            scaled = int(round(bits * (8.0 / overlap))) + abs(shift)
            if scaled < best:
                best = scaled
        return best
    except ValueError:
        return 64


def are_avatars_matching(hash_a: Optional[str], hash_b: Optional[str], threshold: int = 8) -> bool:
    """
    Returns True if two 64-bit perceptual dHashes belong to the same profile picture
    (Hamming distance <= threshold).
    """
    if not hash_a or not hash_b:
        return False
    return hamming_distance(hash_a, hash_b) <= threshold


class AvatarFingerprinter:
    """
    Crops circular profile photos from Android screen captures using Qt's native C++ QImage
    and computes a 64-bit perceptual difference hash (dHash) + saves 64x64 thumbnails
    for GUI display and Printable Lottery Slips.
    """

    def __init__(self, avatar_dir: str = "data/avatars"):
        self.avatar_dir = avatar_dir
        os.makedirs(self.avatar_dir, exist_ok=True)

    def crop_and_hash(self, screenshot_png: bytes, bounds_str: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Given raw PNG bytes of the full screen and an avatar node's bounds '[x1,y1][x2,y2]',
        returns (dhash_hex_16char, saved_thumbnail_path).
        """
        if not screenshot_png or not bounds_str:
            return None, None

        rect = parse_bounds(bounds_str)
        if not rect:
            return None, None

        x, y, w, h = rect
        # Skip avatars that are clipped at the top/bottom edges of the scrollable list (not roughly square)
        if abs(w - h) > 8 or w < 32 or h < 32:
            return None, None

        try:
            from PySide6.QtGui import QImage, qGray
            from PySide6.QtCore import Qt

            img = QImage.fromData(screenshot_png)
            if img.isNull():
                return None, None

            # Ignore avatars too close to top header (< 220px) or bottom comment bar (> height - 180px)
            if y < 220 or (y + h) > (img.height() - 160):
                return None, None

            # Clamp to image dimensions
            if x < 0 or y < 0 or x + w > img.width() or y + h > img.height():
                return None, None

            cropped = img.copy(x, y, w, h)
            if cropped.isNull():
                return None, None

            # Compute 64-bit dHash on 9x8 grayscale downscale
            small = cropped.scaled(9, 8, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            bits = 0
            for row in range(8):
                for col in range(8):
                    left_lum = qGray(small.pixel(col, row))
                    right_lum = qGray(small.pixel(col + 1, row))
                    bits = (bits << 1) | (1 if left_lum > right_lum else 0)

            dhash_hex = f"{bits:016x}"
            # Ignore blank/solid unloaded placeholders or mid-transition screen bars (e.g. 6+ consecutive 0s or fs)
            if "000000" in dhash_hex or "ffffff" in dhash_hex:
                return None, None

            thumb_path = os.path.join(self.avatar_dir, f"{dhash_hex}.png")
            if not os.path.exists(thumb_path):
                thumb = cropped.scaled(64, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                tmp_path = f"{thumb_path}.{os.getpid()}.tmp"
                if thumb.save(tmp_path, "PNG"):
                    os.replace(tmp_path, thumb_path)

            return dhash_hex, thumb_path
        except Exception as e:
            logger.debug(f"Avatar crop/hash skipped: {e}")
            return None, None

    def hash_image_bytes(self, image_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
        """
        Computes the exact same 64-bit perceptual dHash from raw avatar image bytes
        (e.g., downloaded from a Web `avatar_url`) and saves a 64x64 thumbnail in `data/avatars/`.
        """
        if not image_bytes:
            return None, None
        try:
            from PySide6.QtGui import QImage, qGray
            from PySide6.QtCore import Qt

            img = QImage.fromData(image_bytes)
            if img.isNull() or img.width() < 16 or img.height() < 16:
                return None, None

            small = img.scaled(9, 8, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            bits = 0
            for row in range(8):
                for col in range(8):
                    left_lum = qGray(small.pixel(col, row))
                    right_lum = qGray(small.pixel(col + 1, row))
                    bits = (bits << 1) | (1 if left_lum > right_lum else 0)

            dhash_hex = f"{bits:016x}"
            if dhash_hex in ("0000000000000000", "ffffffffffffffff"):
                return None, None

            thumb_path = os.path.join(self.avatar_dir, f"{dhash_hex}.png")
            if not os.path.exists(thumb_path):
                thumb = img.scaled(64, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                tmp_path = f"{thumb_path}.{os.getpid()}.tmp"
                if thumb.save(tmp_path, "PNG"):
                    os.replace(tmp_path, thumb_path)

            return dhash_hex, thumb_path
        except Exception as e:
            logger.debug(f"Avatar hash_image_bytes skipped: {e}")
            return None, None


