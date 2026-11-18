"""TRIHX PDF window colors and saved appearance preferences."""
from string import Template

from PySide6.QtGui import QColor, QPalette


DEFAULT_CUSTOM_COLOR = "#317b75"
MODES = {"light": "Sáng", "dark": "Tối", "custom": "Màu tùy chọn…"}


def read_appearance(settings):
    mode = settings.value("appearance/mode", "light", type=str)
    custom = QColor(settings.value("appearance/customColor", DEFAULT_CUSTOM_COLOR, type=str))
    if not custom.isValid():
        custom = QColor(DEFAULT_CUSTOM_COLOR)
        if mode == "custom":
            mode = "light"
    return mode if mode in MODES else "light", custom.name()


def _mix(first, second, amount):
    left = QColor(first).getRgbF()[:3]
    right = QColor(second).getRgbF()[:3]
    return QColor.fromRgbF(*(a + (b - a) * amount for a, b in zip(left, right))).name()


def _ink(background):
    # Use the more legible of black and white, including for mid-tone custom colors.
    rgb = QColor(background).getRgbF()[:3]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    luminance = sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#000000" if (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) else "#ffffff"


def theme_colors(mode, custom):
    dark = mode == "dark" or (mode == "custom" and _ink(custom) == "#ffffff")
    if dark:
        colors = dict(canvas="#171d26", toolbar="#26303d", title="#202a38", surface="#2b3645",
                      text="#edf2f8", border="#465568", accent="#88baff")
    else:
        colors = dict(canvas="#e8edf4", toolbar="#e9edf5", title="#e1e7f2", surface="#ffffff",
                      text="#26354a", border="#cbd5e3", accent="#175bdf")
    if mode == "custom":
        colors.update(title=custom, accent=custom)
        for key, weight in (("canvas", .12), ("toolbar", .18), ("surface", .04), ("border", .24)):
            colors[key] = _mix(colors[key], custom, weight)
    colors.update(
        title_text=_ink(colors["title"]) if mode == "custom" else colors["text"],
        accent_text=_ink(colors["accent"]),
        muted=_mix(colors["text"], colors["surface"], .26),
        disabled=_mix(colors["text"], colors["toolbar"], .54),
        tab=_mix(colors["toolbar"], colors["text"], .07),
        hover=_mix(colors["toolbar"], colors["accent"], .16),
        title_hover=_mix(colors["title"], "#344052" if dark else "#d5deea", .38),
        close_hover=_mix(colors["title"], "#e65260", .42),
        shadow=_mix(colors["canvas"], "#000000", .15),
        link=_mix(colors["text"], colors["accent"], .38),
    )
    return colors


def apply_appearance(app, mode, custom):
    colors = theme_colors(mode, custom)
    role = QPalette.ColorRole
    palette = QPalette()
    for name, keys in (
        ("canvas", (role.Window,)),
        ("surface", (role.Base, role.Button, role.ToolTipBase, role.Light)),
        ("toolbar", (role.AlternateBase, role.Midlight)),
        ("text", (role.Text, role.WindowText, role.ButtonText, role.ToolTipText)),
        ("muted", (role.PlaceholderText,)),
        ("border", (role.Mid, role.Dark)),
        ("shadow", (role.Shadow,)),
        ("accent", (role.Highlight, role.Accent)),
        ("accent_text", (role.HighlightedText,)),
        ("link", (role.Link, role.LinkVisited)),
    ):
        for key in keys:
            palette.setColor(key, QColor(colors[name]))
    for key in (role.Text, role.WindowText, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, key, QColor(colors["disabled"]))
    app.setPalette(palette)
    app.setStyleSheet(_STYLES.substitute(colors))
    return colors


_STYLES = Template("""
    QMainWindow, QDialog, QWidget#documentCanvas, QScrollArea#documentScroll { background: $canvas; }
    QScrollArea#documentScroll { border: 0; }
    QToolBar { background: $toolbar; border: 0; border-bottom: 1px solid $border; spacing: 5px; padding: 5px 9px; }
    QWidget#documentTabs { background: $title; border-bottom: 1px solid $border; }
    QPushButton, QToolButton { color: $text; background: $surface; border: 1px solid $border; border-radius: 8px; padding: 7px 12px; }
    QPushButton:hover, QToolButton:hover { background: $hover; }
    QPushButton:disabled, QToolButton:disabled { color: $disabled; }
    QPushButton#fileAction { background: transparent; border: 0; padding: 5px 10px; }
    QPushButton#fileAction:hover { background: $hover; }
    QToolButton#officeBrand { background: $tab; border: 0; font-weight: bold; padding: 5px 10px; }
    QToolButton#themeButton { color: $title_text; background: transparent; border: 1px solid transparent; padding: 4px 14px 4px 8px; }
    QToolButton#themeButton:focus { border-color: $title_text; }
    QToolButton#themeButton:hover, QToolButton#themeButton:pressed { background: $title_hover; }
    QToolButton[captionButton="true"] { background: transparent; border: 0; border-radius: 0; padding: 0; }
    QToolButton[captionButton="true"]:hover { background: $title_hover; }
    QToolButton#captionClose:hover { background: $close_hover; }
    QLineEdit { color: $text; background: $surface; border: 1px solid $border; border-radius: 7px; padding: 5px 4px; }
    QLineEdit:focus { border-color: $accent; }
    QLineEdit:disabled { color: $disabled; }
    QTabBar::tab { color: $text; background: $tab; padding: 4px 8px; margin-right: 4px; max-width: 220px; border: 1px solid transparent; border-bottom-width: 2px; border-radius: 7px; }
    QTabBar::tab:hover { background: $hover; }
    QTabBar::tab:selected { background: $surface; border-color: $border; border-bottom-color: $accent; }
    QTabBar QToolButton { padding: 0; border-radius: 0; }
    QToolButton#tabClose { background: transparent; border: 0; border-radius: 5px; padding: 0; }
    QToolButton#tabClose:hover { background: $hover; }
    QMenu { background: $surface; color: $text; border: 1px solid $border; }
    QMenu::item:selected { background: $accent; color: $accent_text; }
    QMenu::item:disabled { color: $disabled; }
    QStatusBar { background: $surface; color: $muted; border-top: 1px solid $border; }
    QToolButton#updateButton { background: transparent; border: 0; padding: 1px 8px; }
    QToolButton#updateButton:hover { background: $hover; }
    QDialog#recentPopup { background: $surface; border: 1px solid $border; border-radius: 8px; }
    QListWidget#recentList { background: $surface; border: 0; }
    QListWidget#recentList::item { border-bottom: 1px solid $border; }
    QListWidget#recentList::item:selected, QListWidget#recentList::item:hover { background: $hover; }
    QLabel#recentTitle { color: $text; font-size: 16px; font-weight: 600; }
    QLabel#recentFilename { color: $text; font-size: 12px; }
    QLabel#recentDetail { color: $muted; font-size: 10px; }
    QLabel#emptyState { background: $surface; color: $muted; font-size: 18px; border: 1px solid $border; border-radius: 10px; }
    QLabel#pdfPage { background: white; color: #202020; border: 1px solid $border; }
    QPushButton#submitPrint:enabled { background: $accent; color: $accent_text; padding: 7px 22px; }
""")
