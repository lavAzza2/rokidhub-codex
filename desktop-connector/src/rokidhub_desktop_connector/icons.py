from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap


# Official Font Awesome 4.0.3 private-use codepoints from the bundled CSS.
GLYPHS = {
    "home": "\uf015",
    "folder": "\uf114",
    "code": "\uf121",
    "shield": "\uf132",
    "activity": "\uf080",
    "settings": "\uf013",
    "play": "\uf04b",
    "stop": "\uf04d",
    "check-circle": "\uf05d",
    "warning": "\uf071",
    "info": "\uf05a",
    "desktop": "\uf108",
    "link": "\uf0c1",
    "microphone": "\uf130",
    "eye": "\uf06e",
    "plus": "\uf067",
    "refresh": "\uf021",
    "save": "\uf0c7",
    "sign-out": "\uf08b",
    "circle-o": "\uf10c",
    "dot-circle-o": "\uf192",
}


class IconFactory:
    """Render the bundled Font Awesome library as scalable Qt icons."""

    def __init__(self):
        font_path = Path(__file__).resolve().parent / "assets" / "fontawesome-webfont.ttf"
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if not families:
            raise RuntimeError(f"Font Awesome asset could not be loaded: {font_path}")
        self.family = families[0]

    def icon(
        self,
        name: str,
        color: str = "#a8aea7",
        *,
        active_color: str | None = None,
        canvas: int = 64,
    ) -> QIcon:
        icon = QIcon(self.pixmap(name, color, canvas=canvas))
        if active_color:
            active = self.pixmap(name, active_color, canvas=canvas)
            icon.addPixmap(active, QIcon.Mode.Active, QIcon.State.Off)
            icon.addPixmap(active, QIcon.Mode.Normal, QIcon.State.On)
            icon.addPixmap(active, QIcon.Mode.Selected, QIcon.State.On)
        return icon

    def pixmap(self, name: str, color: str, *, canvas: int = 64) -> QPixmap:
        glyph = GLYPHS[name]
        pixmap = QPixmap(canvas, canvas)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setPen(QColor(color))
            font = QFont(self.family)
            font.setPixelSize(round(canvas * 0.88))
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            painter.setFont(font)
            painter.drawText(QRect(0, 0, canvas, canvas), Qt.AlignmentFlag.AlignCenter, glyph)
        finally:
            painter.end()
        return pixmap
