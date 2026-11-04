"""
Sentra Brand & Vector Logo Renderer
  Brand Name: SENTRA
  Tagline: "Every signal has a story."
  Description: "A public data intelligence platform that transforms digital activity into structured, measurable insight."
  Pillars: "OBSERVE. UNDERSTAND. DISCOVER."
"""

import math

APP_NAME = "Sentra"
APP_UPPER = "SENTRA"
APP_TAGLINE = "Every signal has a story."
APP_DESCRIPTION = (
    "A public data intelligence platform that transforms digital activity "
    "into structured, measurable insight."
)
APP_PILLARS = "OBSERVE. UNDERSTAND. DISCOVER."
APP_WINDOW_TITLE = "Sentra — Public Data Intelligence & Contest Validator (Every signal has a story)"


def get_sentra_logo_svg(size: int = 36, stroke_color: str = "#38bdf8", bg_fill: str = "none") -> str:
    """
    Returns an inline SVG of the Sentra orbital signal logo (center hollow node + two
    diagonal orbital nodes at 45° and 225° connected by dual sweeping signal arcs).
    """
    bg_rect = (
        f'<rect x="2" y="2" width="96" height="96" rx="22" fill="{bg_fill}" stroke="#1e293b" stroke-width="2"/>'
        if bg_fill and bg_fill != "none"
        else ""
    )
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 100 100" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle;flex-shrink:0;">'
        f"{bg_rect}"
        # Top-left orbital arc (from ~202° sweeping over top-left to ~63° where it meets the top-right node)
        f'<path d="M 20.3 62.3 A 32 32 0 0 1 62.3 20.3" stroke="{stroke_color}" stroke-width="6.5" stroke-linecap="round"/>'
        # Bottom-right orbital arc (from ~22° sweeping around bottom-right to ~243° where it meets the bottom-left node)
        f'<path d="M 79.7 37.7 A 32 32 0 0 1 37.7 79.7" stroke="{stroke_color}" stroke-width="6.5" stroke-linecap="round"/>'
        # Top-right orbital node (at ~45° on radius 32 -> x=72.6, y=27.4)
        f'<circle cx="72.6" cy="27.4" r="7.2" stroke="{stroke_color}" stroke-width="6" fill="#0b1120"/>'
        # Bottom-left orbital node (at ~225° on radius 32 -> x=27.4, y=72.6)
        f'<circle cx="27.4" cy="72.6" r="7.2" stroke="{stroke_color}" stroke-width="6" fill="#0b1120"/>'
        # Center signal core ring
        f'<circle cx="50" cy="50" r="8.2" stroke="{stroke_color}" stroke-width="6" fill="#0b1120"/>'
        f"</svg>"
    )


def render_sentra_logo_qimage(size: int = 512, with_badge_bg: bool = True):
    """
    Renders the Sentra orbital signal logo as a high-DPI antialiased `QImage`
    for macOS `.icns`, Windows `.ico`, `AppIcon.png`, and Qt widgets.
    """
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import (
        QColor,
        QGuiApplication,
        QImage,
        QLinearGradient,
        QPainter,
        QPen,
    )

    _app = QGuiApplication.instance() or QGuiApplication([])
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)

    s = float(size)
    cx, cy = s * 0.5, s * 0.5
    bg_dark = QColor("#0b1120")
    cyan = QColor("#35c5f0")

    if with_badge_bg:
        margin = s * 0.045
        rect_sz = s - 2.0 * margin
        radius = s * 0.22

        grad = QLinearGradient(0, 0, s, s)
        grad.setColorAt(0.0, QColor("#0d1526"))
        grad.setColorAt(0.6, QColor("#0b1120"))
        grad.setColorAt(1.0, QColor("#070b14"))

        p.setPen(QPen(QColor("#1e293b"), max(s * 0.015, 1.5)))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(margin, margin, rect_sz, rect_sz), radius, radius)

    orbit_r = s * (0.31 if with_badge_bg else 0.35)
    stroke_w = max(s * (0.064 if with_badge_bg else 0.072), 2.2)
    orbit_rect = QRectF(cx - orbit_r, cy - orbit_r, orbit_r * 2.0, orbit_r * 2.0)

    arc_pen = QPen(cyan, stroke_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(arc_pen)
    p.setBrush(Qt.NoBrush)

    # Qt drawArc angles are in 1/16th of a degree, counter-clockwise from 3 o'clock (0°):
    # Top-right node sits at +45°; bottom-left node sits at +225°.
    # Arc 1 (Top-Left): from 62° counter-clockwise to 198° (span = 136°)
    p.drawArc(orbit_rect, int(62 * 16), int(136 * 16))
    # Arc 2 (Bottom-Right): from 242° counter-clockwise to 378° (+18°) (span = 136°)
    p.drawArc(orbit_rect, int(242 * 16), int(136 * 16))

    # Node rings at +45° (top-right) and +225° (bottom-left)
    node_r = s * (0.072 if with_badge_bg else 0.080)
    node_pen = QPen(cyan, stroke_w * 0.92, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(node_pen)
    p.setBrush(bg_dark)

    for angle_deg in (45.0, 225.0):
        rad = math.radians(angle_deg)
        nx = cx + orbit_r * math.cos(rad)
        ny = cy - orbit_r * math.sin(rad)
        p.drawEllipse(QPointF(nx, ny), node_r, node_r)

    # Center core ring
    center_r = s * (0.082 if with_badge_bg else 0.090)
    p.drawEllipse(QPointF(cx, cy), center_r, center_r)

    p.end()
    return img


def render_sentra_mark_pixmap(size: int = 44, with_badge_bg: bool = False):
    """
    Returns a high-DPI `QPixmap` of the Sentra orbital signal logo for Qt GUI headers.
    """
    from PySide6.QtGui import QPixmap

    img = render_sentra_logo_qimage(size=size, with_badge_bg=with_badge_bg)
    return QPixmap.fromImage(img)

