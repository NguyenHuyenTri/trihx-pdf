from __future__ import annotations

import sys
import json
from datetime import datetime
from math import ceil
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import Qt, QSize, QTimer, QSettings, QPoint, QEvent
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QImage, QIntValidator, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from office_bridge import DOCUMENT_TYPES, FILE_FILTER, OFFICE_TYPES, OfficeWindow, show_office
from print_dialog import PdfPrintDialog
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QTabBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "TRIHX Office"
RENDER_SCALE = 1.35
MIN_ZOOM_PERCENT = 25
MAX_ZOOM_PERCENT = 400
HIGHLIGHT_COLOR = QColor(55, 135, 245, 115)


def resource_path(name: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / name


class PdfPageLabel(QLabel):
    def __init__(self, page, scale: float, on_focus) -> None:
        super().__init__()
        self.pdf_page = page
        self.scale = scale
        self.page_height = page.get_height()
        self.on_focus = on_focus
        self.selection_start: int | None = None
        self.selection_end: int | None = None
        self.search_matches: list[tuple[int, int]] = []
        self.active_search_match: tuple[int, int] | None = None
        self._textpage = None
        self._char_boxes: dict[int, tuple[float, float, float, float]] = {}
        self._dragging = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: white; border: 1px solid #d6dde7;")
        self.setFixedSize(ceil(page.get_width() * scale), ceil(page.get_height() * scale))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._copy_shortcuts = []
        for key in (QKeySequence.StandardKey.Copy, QKeySequence.StandardKey.Cut):
            shortcut = QShortcut(key, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(self.copy_selection)
            self._copy_shortcuts.append(shortcut)

    def _get_textpage(self):
        if self._textpage is None:
            self._textpage = self.pdf_page.get_textpage()
        return self._textpage

    def _char_at(self, point) -> int | None:
        x = point.x() / self.scale
        y = self.page_height - point.y() / self.scale
        try:
            return self._get_textpage().get_index(
                x, y, x_tol=max(2.5, 5.0 / self.scale), y_tol=max(3.0, 6.0 / self.scale)
            )
        except Exception:
            return None

    def _char_rect(self, textpage, index: int):
        if index not in self._char_boxes:
            try:
                self._char_boxes[index] = textpage.get_charbox(index)
            except Exception:
                self._char_boxes[index] = (0.0, 0.0, 0.0, 0.0)
        left, bottom, right, top = self._char_boxes[index]
        if right <= left or top <= bottom:
            return None
        return (left * self.scale, (self.page_height - top) * self.scale,
                (right - left) * self.scale, (top - bottom) * self.scale)

    def _paint_span(self, painter: QPainter, textpage, span: tuple[int, int], color: QColor) -> None:
        start, count = span
        line_rects: list[list[float]] = []
        for index in range(start, start + count):
            rect = self._char_rect(textpage, index)
            if rect is None:
                continue
            x, y, width, height = rect
            if line_rects:
                last = line_rects[-1]
                overlap = min(last[1] + last[3], y + height) - max(last[1], y)
                same_line = overlap >= min(last[3], height) * 0.25
                gap = x - (last[0] + last[2])
                gap_limit = max(5.0, min(last[3], height) * 0.85)
                if same_line and gap <= gap_limit:
                    right = max(last[0] + last[2], x + width)
                    bottom = max(last[1] + last[3], y + height)
                    last[0] = min(last[0], x)
                    last[1] = min(last[1], y)
                    last[2] = right - last[0]
                    last[3] = bottom - last[1]
                    continue
            line_rects.append([x, y, width, height])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for x, y, width, height in line_rects:
            painter.drawRoundedRect(x - 1, y, width + 2, height, 2.5, 2.5)

    def paintEvent(self, event) -> None:
        if self.pixmap().isNull() and self.pdf_page.raw is not None and not self.text():
            try:
                bitmap = self.pdf_page.render(scale=self.scale, draw_annots=True, may_draw_forms=True)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    pixels = QImage(image.tobytes(), image.width, image.height,
                                    image.width * 3, QImage.Format.Format_RGB888).copy()
                    self.setPixmap(QPixmap.fromImage(pixels))
                finally:
                    bitmap.close()
            except Exception:
                self.setText("Không thể hiển thị trang này.")
        super().paintEvent(event)
        if not self.search_matches and self.selection_start is None:
            return
        try:
            textpage = self._get_textpage()
        except Exception:
            return
        painter = QPainter(self)
        for span in self.search_matches:
            self._paint_span(painter, textpage, span, HIGHLIGHT_COLOR)
        if self.selection_start is not None and self.selection_end is not None:
            start = min(self.selection_start, self.selection_end)
            count = abs(self.selection_end - self.selection_start) + 1
            self._paint_span(painter, textpage, (start, count), HIGHLIGHT_COLOR)
        painter.end()

    def set_search_matches(self, matches: list[tuple[int, int]], active: tuple[int, int] | None) -> None:
        self.search_matches = matches
        self.active_search_match = active
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.on_focus(self)
            index = self._char_at(event.position())
            self._dragging = index is not None
            self.selection_start = index
            self.selection_end = index
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            index = self._char_at(event.position())
            if index is not None:
                self.selection_end = index
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging:
                index = self._char_at(event.position())
                if index is not None:
                    self.selection_end = index
                    self.update()
            self._dragging = False
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection(self) -> str:
        if self.selection_start is None or self.selection_end is None:
            return ""
        start = min(self.selection_start, self.selection_end)
        count = abs(self.selection_end - self.selection_start) + 1
        try:
            text = self._get_textpage().get_text_range(start, count).replace("\x00", "")
            if text:
                QApplication.clipboard().setText(text)
            return text
        except Exception:
            return ""

    def close_textpage(self) -> None:
        if self._textpage is not None:
            self._textpage.close()
            self._textpage = None
        self._char_boxes.clear()


class PdfReaderWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self._toolbar_icon("brand"))
        self.resize(1180, 820)
        self.setMinimumSize(760, 560)
        self.document = None
        self.file_path: Path | None = None
        self.page_index = 0
        self.zoom = RENDER_SCALE
        self.page_text: dict[int, str] = {}
        self.search_results: list[tuple[int, int, int]] = []
        self.search_position = -1
        self.last_search_query = ""
        self.page_labels: list[QLabel] = []
        self.active_page_label: PdfPageLabel | None = None
        self.open_tabs: dict[str, dict] = {}
        self.active_tab_key: str | None = None
        self._tab_change_blocked = False
        self.office_window = None
        self.settings = QSettings("TRIHX", "HX PDF")
        self.recent_files: list[dict[str, str | float]] = self._load_recent_files()
        self._build_ui()
        self._build_actions()
        self._set_empty_state()
        self._update_document_controls()

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QMainWindow { background: #eef2f7; }
            QToolBar { background: #e9edf5; border: 0; border-bottom: 1px solid #cbd5e3; spacing: 5px; padding: 5px 9px; }
            QToolBar#documentTabs { background: #e1e7f2; padding: 4px 8px 0px; }
            QPushButton#fileAction { background: transparent; border: 0; padding: 5px 10px; }
            QPushButton#fileAction:hover { background: #d7e0ef; }
            QToolButton#officeBrand { background: #d5deec; border: 0; font-weight: bold; padding: 5px 10px; }
            QToolButton, QPushButton { color: #26354a; background: #ffffff; border: 1px solid #d7e0eb; border-radius: 8px; padding: 7px 12px; }
            QToolButton:hover, QPushButton:hover { background: #f0f6ff; border-color: #9bbce8; }
            QLineEdit { color: #26354a; background: white; border: 1px solid #d7e0eb; border-radius: 7px; padding: 5px 4px; }
            QTabBar::tab { background: #e8edf4; color: #34445a; padding: 7px 14px; margin-right: 3px; max-width: 260px; border: 1px solid #d8e0eb; border-bottom: none; border-top-left-radius: 7px; border-top-right-radius: 7px; }
            QTabBar::tab:selected { background: #f8fbff; color: #14253c; border-color: #a7bedf; }
            QTabBar::tab:hover { background: #f7f9fc; }
            QStatusBar { background: #ffffff; border-top: 1px solid #dce3ec; color: #536276; }
        """)

        file_toolbar = QToolBar("Tệp")
        file_toolbar.setMovable(False)
        file_toolbar.setFloatable(False)
        self.addToolBar(file_toolbar)

        open_button = QPushButton("Open")
        open_button.setObjectName("fileAction")
        open_button.setIcon(self._toolbar_icon("open"))
        open_button.setIconSize(QSize(20, 20))
        open_button.clicked.connect(self.open_dialog)
        file_toolbar.addWidget(open_button)
        self.recent_button = QPushButton("Recent")
        self.recent_button.setObjectName("fileAction")
        self.recent_button.setIcon(self._toolbar_icon("recent"))
        self.recent_button.setIconSize(QSize(20, 20))
        self.recent_button.clicked.connect(self._show_recent_popup)
        file_toolbar.addWidget(self.recent_button)
        self.print_button = QPushButton("Print")
        self.print_button.setObjectName("fileAction")
        self.print_button.setIcon(self._toolbar_icon("print"))
        self.print_button.setIconSize(QSize(20, 20))
        self.print_button.clicked.connect(self.print_document)
        file_toolbar.addWidget(self.print_button)

        toolbar = file_toolbar
        before_pdf = len(toolbar.actions())
        toolbar.addSeparator()

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Tìm trong PDF")
        self.search_box.setFixedWidth(220)
        self.search_box.returnPressed.connect(self.search_next)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        self.search_box.setToolTip("Enter: kết quả tiếp theo • Shift+Enter: kết quả trước")
        self.search_previous_shortcut = QShortcut(QKeySequence("Shift+Return"), self.search_box)
        self.search_previous_shortcut.activated.connect(self.search_previous)
        toolbar.addWidget(self.search_box)
        self.search_count_label = QLabel("0/0")
        self.search_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.search_count_label.setFixedWidth(48)
        self.search_count_label.setToolTip("Enter/F3: kết quả tiếp theo • Shift+Enter/Shift+F3: kết quả trước")
        toolbar.addWidget(self.search_count_label)
        toolbar.addSeparator()

        self.page_input = QLineEdit("1")
        self.page_input.setValidator(QIntValidator(1, 999999, self.page_input))
        self.page_input.setToolTip("Nhập số trang rồi nhấn Enter")
        self.page_input.editingFinished.connect(self._page_input_changed)
        self.page_input.setFixedWidth(44)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_prev_button = QPushButton("−")
        self.page_prev_button.setFixedWidth(30)
        self.page_prev_button.setToolTip("Về trang trước (−1 trang)")
        self.page_prev_button.setEnabled(False)
        self.page_prev_button.clicked.connect(lambda: self.go_to_page(self.page_index - 1))
        toolbar.addWidget(self.page_prev_button)
        toolbar.addWidget(self.page_input)
        self.page_next_button = QPushButton("+")
        self.page_next_button.setFixedWidth(30)
        self.page_next_button.setToolTip("Đến trang tiếp theo (+1 trang)")
        self.page_next_button.setEnabled(False)
        self.page_next_button.clicked.connect(lambda: self.go_to_page(self.page_index + 1))
        toolbar.addWidget(self.page_next_button)
        self.page_total = QLabel("/ 0")
        toolbar.addWidget(self.page_total)
        toolbar.addSeparator()

        zoom_out = QPushButton("−")
        zoom_out.setFixedWidth(30)
        zoom_out.setToolTip("Thu nhỏ")
        zoom_out.clicked.connect(lambda: self.change_zoom(-10))
        toolbar.addWidget(zoom_out)
        self.zoom_input = QLineEdit("100")
        self.zoom_input.setValidator(QIntValidator(MIN_ZOOM_PERCENT, MAX_ZOOM_PERCENT, self.zoom_input))
        self.zoom_input.editingFinished.connect(self._zoom_input_changed)
        self.zoom_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_input.setToolTip("Nhập phần trăm thu phóng rồi nhấn Enter")
        self.zoom_input.setFixedWidth(46)
        toolbar.addWidget(self.zoom_input)
        self.zoom_suffix = QLabel("%")
        toolbar.addWidget(self.zoom_suffix)
        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(30)
        zoom_in.setToolTip("Phóng to")
        zoom_in.clicked.connect(lambda: self.change_zoom(10))
        toolbar.addWidget(zoom_in)
        fit_button = QToolButton()
        fit_button.setText("Vừa trang")
        fit_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        fit_button.clicked.connect(self.fit_page)
        fit_menu = QMenu(fit_button)
        fit_menu.addAction("Vừa trang", self.fit_page)
        fit_menu.addAction("Vừa chiều rộng", lambda: self.fit_page(width_only=True))
        fit_menu.addAction("100%", lambda: self.set_zoom(RENDER_SCALE))
        fit_button.setMenu(fit_menu)
        toolbar.addWidget(fit_button)
        self.pdf_actions = toolbar.actions()[before_pdf:]
        self.signature_action = toolbar.addAction("Chữ ký số")
        self.signature_action.triggered.connect(self.verify_signatures)
        self.pdf_actions.append(self.signature_action)
        self.office_options = QToolButton()
        self.office_options.setText("Cửa sổ Office")
        self.office_options.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        options = QMenu(self.office_options)
        self.hide_caption = options.addAction("Thử ẩn thanh tiêu đề Office")
        self.hide_caption.setCheckable(True)
        self.hide_caption.setChecked(self.settings.value("hideOfficeCaption", True, type=bool))
        self.hide_caption.toggled.connect(self._set_office_caption)
        options.addAction("Khôi phục cửa sổ Office", self._restore_office_window)
        self.office_options.setMenu(options)
        self.office_toolbar_action = toolbar.addWidget(self.office_options)

        self.tab_bar = QTabBar()
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setMovable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tab_bar.setIconSize(QSize(16, 16))
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        self.tab_bar.tabCloseRequested.connect(self.close_tab)
        self.app_home_button = QToolButton()
        self.app_home_button.setText(APP_NAME)
        self.app_home_button.setObjectName("officeBrand")
        self.app_home_button.setIcon(self._toolbar_icon("brand"))
        self.app_home_button.setIconSize(QSize(22, 22))
        self.app_home_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.app_home_button.setToolTip("Tệp gần đây")
        self.app_home_button.clicked.connect(self._show_recent_popup)
        self.add_tab_button = QToolButton()
        self.add_tab_button.setText("+")
        self.add_tab_button.setToolTip("Mở thêm tài liệu trong tab mới")
        self.add_tab_button.clicked.connect(self.open_dialog)
        self.document_tabs_toolbar = QToolBar("Các tài liệu đang mở")
        self.document_tabs_toolbar.setObjectName("documentTabs")
        self.document_tabs_toolbar.setMovable(False)
        self.document_tabs_toolbar.setFloatable(False)
        self.document_tabs_toolbar.addWidget(self.app_home_button)
        self.tabs_toolbar_action = self.document_tabs_toolbar.addWidget(self.tab_bar)
        self.tabs_toolbar_action.setVisible(False)
        self.document_tabs_toolbar.addWidget(self.add_tab_button)
        self.insertToolBar(file_toolbar, self.document_tabs_toolbar)
        self.insertToolBarBreak(file_toolbar)
        self.file_toolbar = file_toolbar

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.scroll.setStyleSheet("QScrollArea { border: 0; background: #e8edf4; }")
        self.pages_widget = QWidget()
        self.pages_layout = QVBoxLayout(self.pages_widget)
        self.pages_layout.setContentsMargins(20, 20, 20, 20)
        self.pages_layout.setSpacing(18)
        self.pages_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll.setWidget(self.pages_widget)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_page_from_scroll)

        self.recent_popup = QDialog(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.recent_popup.setStyleSheet("QDialog { background: #ffffff; border: 1px solid #cfd7e2; border-radius: 8px; }")
        recent_layout = QVBoxLayout(self.recent_popup)
        recent_layout.setContentsMargins(12, 10, 12, 10)
        recent_layout.setSpacing(6)
        recent_header = QHBoxLayout()
        recent_title = QLabel("Recent")
        recent_title.setStyleSheet("font-size: 16px; font-weight: 600; color: #26354a; border: none;")
        recent_header.addWidget(recent_title)
        recent_header.addStretch(1)
        refresh_recent = QToolButton()
        refresh_recent.setText("⟳")
        refresh_recent.setToolTip("Làm mới danh sách gần đây")
        refresh_recent.clicked.connect(self._refresh_recent_list)
        recent_header.addWidget(refresh_recent)
        close_recent = QToolButton()
        close_recent.setText("×")
        close_recent.clicked.connect(self.recent_popup.hide)
        recent_header.addWidget(close_recent)
        recent_layout.addLayout(recent_header)
        self.recent_list = QListWidget()
        self.recent_list.setStyleSheet("QListWidget { border: 0; } QListWidget::item { border-bottom: 1px solid #edf0f4; }")
        self.recent_list.itemClicked.connect(self._open_recent_item)
        recent_layout.addWidget(self.recent_list, 1)
        self._refresh_recent_list()
        self.recent_popup.resize(720, 600)
        self.setCentralWidget(self.scroll)
        self.setStatusBar(QStatusBar())

    def _load_recent_files(self) -> list[dict[str, str | float]]:
        saved = self.settings.value("recentFilesJson", "")
        try:
            entries = json.loads(saved) if saved else self.settings.value("recentFiles", []) or []
        except (TypeError, ValueError):
            entries = self.settings.value("recentFiles", []) or []
        recent: list[dict[str, str | float]] = []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("path"):
                try:
                    recent.append({"path": str(entry["path"]), "opened": float(entry.get("opened", 0))})
                except (TypeError, ValueError):
                    continue
            elif isinstance(entry, str):
                recent.append({"path": entry, "opened": 0.0})
        return recent[:30]

    def _record_recent_file(self, path: Path) -> None:
        try:
            path_string = str(path.resolve())
            self.recent_files = [entry for entry in self.recent_files if str(entry.get("path", "")).casefold() != path_string.casefold()]
            self.recent_files.insert(0, {"path": path_string, "opened": datetime.now().timestamp()})
            self.recent_files = self.recent_files[:30]
            self.settings.setValue("recentFilesJson", json.dumps(self.recent_files, ensure_ascii=False))
            self.settings.sync()
            self._refresh_recent_list()
        except Exception:
            # Recent history must never prevent opening a valid PDF.
            pass

    def _refresh_recent_list(self) -> None:
        if not hasattr(self, "recent_list"):
            return
        self.recent_list.clear()

        for entry in self.recent_files:
            path_value = str(entry.get("path", "")).strip()
            if not path_value:
                continue
            path = Path(path_value)
            try:
                opened = float(entry.get("opened", 0) or 0)
            except (TypeError, ValueError):
                opened = 0.0
            if opened:
                opened_at = datetime.fromtimestamp(opened)
                time_label = ("Today " if opened_at.date() == datetime.now().date() else opened_at.strftime("%d-%m ")) + opened_at.strftime("%H:%M")
            else:
                time_label = ""

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            item.setSizeHint(QSize(300, 58))
            self.recent_list.addItem(item)

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 4, 6, 4)
            row_layout.setSpacing(8)
            icon_label = QLabel()
            icon_label.setPixmap(self._file_icon(path).pixmap(28, 28))
            icon_label.setFixedSize(30, 34)
            row_layout.addWidget(icon_label)
            details = QVBoxLayout()
            details.setContentsMargins(0, 0, 0, 0)
            details.setSpacing(2)
            title_line = QHBoxLayout()
            title_line.setContentsMargins(0, 0, 0, 0)
            name_label = QLabel(path.name)
            name_label.setTextFormat(Qt.TextFormat.PlainText)
            name_label.setStyleSheet("color: #34445a; font-size: 12px; border: none;")
            name_label.setToolTip(str(path))
            title_line.addWidget(name_label, 1)
            time_text = QLabel(time_label)
            time_text.setStyleSheet("color: #8190a3; font-size: 10px; border: none;")
            title_line.addWidget(time_text)
            details.addLayout(title_line)
            folder_label = QLabel(str(path.parent))
            folder_label.setTextFormat(Qt.TextFormat.PlainText)
            folder_label.setStyleSheet("color: #8190a3; font-size: 10px; border: none;")
            folder_label.setToolTip(str(path.parent))
            details.addWidget(folder_label)
            row_layout.addLayout(details, 1)
            self.recent_list.setItemWidget(item, row)

        if not self.recent_files:
            empty = QListWidgetItem("Chưa có tệp PDF gần đây")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent_list.addItem(empty)

    def _show_recent_popup(self) -> None:
        self._refresh_recent_list()
        screen = self.screen().availableGeometry()
        width = min(720, screen.width() - 20)
        height = min(600, screen.height() - 40)
        origin = self.file_toolbar.mapToGlobal(QPoint(8, self.file_toolbar.height() + 4))
        x = min(max(origin.x(), screen.left() + 10), screen.right() - width - 10)
        y = min(max(origin.y(), screen.top() + 10), screen.bottom() - height - 10)
        self.recent_popup.resize(width, height)
        self.recent_popup.move(x, y)
        self.recent_popup.show()

    def _open_recent_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        candidate = Path(str(path))
        if not candidate.is_file():
            QMessageBox.warning(self, "Không tìm thấy tệp", f"Tệp PDF này không còn ở vị trí đã lưu:\n{candidate}")
            return
        self.open_file(candidate)
        self.recent_popup.hide()

    def _build_actions(self) -> None:
        shortcuts = [
            ("Ctrl+O", self.open_dialog),
            ("Ctrl+P", self.print_document),
            ("Ctrl+F", lambda: self.search_box.setFocus()),
            ("Ctrl+W", self.close_current_tab),
            ("Ctrl+Tab", lambda: self.select_tab_step(1)),
            ("Ctrl+Shift+Tab", lambda: self.select_tab_step(-1)),
            ("F3", self.search_next),
            ("Shift+F3", self.search_previous),
            ("Left", lambda: self.go_to_page(self.page_index - 1)),
            ("Right", lambda: self.go_to_page(self.page_index + 1)),
            ("Ctrl+Plus", lambda: self.change_zoom(10)),
            ("Ctrl+Minus", lambda: self.change_zoom(-10)),
        ]
        for shortcut, callback in shortcuts:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)

    def _set_empty_state(self) -> None:
        self.empty_label = QLabel("Kéo thả tài liệu vào cửa sổ hoặc bấm Open để bắt đầu")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumSize(QSize(340, 260))
        self.empty_label.setStyleSheet("background:#ffffff; color:#617188; font-size:18px; border:1px solid #d6dde7; border-radius:10px;")
        self.pages_layout.addWidget(self.empty_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.statusBar().showMessage("Tệp được mở trực tiếp trên máy tính.")
        self.print_button.setEnabled(False)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            candidate = Path(url.toLocalFile())
            if candidate.suffix.lower() in DOCUMENT_TYPES:
                self.open_file(candidate)

    def open_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Mở tài liệu", "", FILE_FILTER)
        for path in paths:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        path = path.expanduser().resolve()
        suffix = path.suffix.lower()
        if suffix not in DOCUMENT_TYPES or not path.is_file():
            QMessageBox.warning(self, "Không mở được tệp", "Hãy chọn tệp PDF, Word, Excel hoặc PowerPoint có sẵn.")
            return
        tab_key = str(path).casefold()
        if tab_key in self.open_tabs:
            self._record_recent_file(path)
            for index in range(self.tab_bar.count()):
                if self.tab_bar.tabData(index) == tab_key:
                    if self.tab_bar.currentIndex() == index and suffix in OFFICE_TYPES:
                        self._open_office(path)
                    else:
                        self.tab_bar.setCurrentIndex(index)
                    break
            return

        if suffix in OFFICE_TYPES:
            self._add_document_tab(tab_key, path, None)
            return

        try:
            new_document = pdfium.PdfDocument(str(path))
            new_document.init_forms()
            if len(new_document) == 0:
                raise ValueError("Tài liệu không có trang nào.")
        except Exception as exc:
            password, accepted = QInputDialog.getText(
                self,
                "PDF có mật khẩu?",
                "Nếu tài liệu được bảo vệ, nhập mật khẩu để mở:",
                QLineEdit.EchoMode.Password,
            )
            if not accepted or not password:
                QMessageBox.critical(self, "Không mở được PDF", f"Không thể mở tệp này.\n\nChi tiết: {exc}")
                return
            try:
                new_document = pdfium.PdfDocument(str(path), password=password)
                new_document.init_forms()
                if len(new_document) == 0:
                    raise ValueError("Tài liệu không có trang nào.")
            except Exception as password_exc:
                QMessageBox.critical(self, "Không mở được PDF", f"Mật khẩu không đúng hoặc tệp bị lỗi.\n\nChi tiết: {password_exc}")
                return

        self._add_document_tab(tab_key, path, new_document)

    def _add_document_tab(self, tab_key, path, document):
        self._record_recent_file(path)
        self._save_active_tab_state()
        self.open_tabs[tab_key] = {
            "path": path,
            "document": document,
            "page_index": 0,
            "zoom": RENDER_SCALE,
            "page_text": {},
            "search_results": [],
            "search_position": -1,
            "last_search_query": "",
            "search_text": "",
        }
        self._tab_change_blocked = True
        index = self.tab_bar.addTab(self._file_icon(path), path.name)
        self.tab_bar.setTabData(index, tab_key)
        self.tab_bar.setTabToolTip(index, str(path))
        self.tab_bar.setCurrentIndex(index)
        self._tab_change_blocked = False
        self.tabs_toolbar_action.setVisible(True)
        self._activate_tab(tab_key, save_previous=False)

    def _save_active_tab_state(self) -> None:
        if self.active_tab_key is None or self.active_tab_key not in self.open_tabs or self.document is None:
            return
        state = self.open_tabs[self.active_tab_key]
        state["page_index"] = self.page_index
        state["zoom"] = self.zoom
        state["page_text"] = self.page_text
        state["search_results"] = self.search_results
        state["search_position"] = self.search_position
        state["last_search_query"] = self.last_search_query
        state["search_text"] = self.search_box.text()

    def _on_tab_changed(self, index: int) -> None:
        if self._tab_change_blocked:
            return
        if index < 0:
            self._show_no_documents()
            return
        tab_key = self.tab_bar.tabData(index)
        if tab_key:
            self._activate_tab(str(tab_key))

    def _activate_tab(self, tab_key: str, save_previous: bool = True) -> None:
        if tab_key not in self.open_tabs:
            return
        self._restore_office_window()
        if save_previous:
            self._save_active_tab_state()
        self._clear_page_widgets()
        state = self.open_tabs[tab_key]
        self.active_tab_key = tab_key
        self.file_path = state["path"]
        self.document = state["document"]
        self._update_document_controls()
        if self.document is None:
            path = self.file_path
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label = QLabel(path.name)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            layout.addWidget(label)
            application = OFFICE_TYPES[path.suffix.lower()][0]
            reopen = QPushButton(f"Mở trong Microsoft {application}")
            reopen.clicked.connect(lambda: self._open_office(path))
            layout.addWidget(reopen, alignment=Qt.AlignmentFlag.AlignCenter)
            self.pages_layout.addWidget(panel)
            self.statusBar().showMessage(str(path))
            QTimer.singleShot(0, lambda: self._open_office(path) if self.active_tab_key == tab_key else None)
            return
        self.page_index = state["page_index"]
        self.zoom = state["zoom"]
        self.page_text = state["page_text"]
        self.search_results = state["search_results"]
        self.search_position = state["search_position"]
        self.last_search_query = state["last_search_query"]
        self.search_box.blockSignals(True)
        self.search_box.setText(state["search_text"])
        self.search_box.blockSignals(False)
        self.page_input.setText(str(self.page_index + 1))
        self.page_total.setText(f"/ {len(self.document)}")
        self.zoom_input.setText(str(round(self.zoom / RENDER_SCALE * 100)))
        if 0 <= self.search_position < len(self.search_results):
            self.search_count_label.setText(f"{self.search_position + 1}/{len(self.search_results)}")
        else:
            self.search_count_label.setText("0/0")
        self.page_prev_button.setEnabled(len(self.document) > 1 and self.page_index > 0)
        self.page_next_button.setEnabled(self.page_index < len(self.document) - 1)
        self.print_button.setEnabled(True)
        self.setWindowTitle(APP_NAME)
        self.render_page()
        self.statusBar().showMessage(f"{self.file_path.name}  •  {len(self.document)} trang  •  Tệp không rời khỏi máy tính")

    def close_tab(self, index: int) -> None:
        tab_key = self.tab_bar.tabData(index)
        if not tab_key:
            return
        tab_key = str(tab_key)
        is_active = tab_key == self.active_tab_key
        if is_active:
            self._restore_office_window()
            self._save_active_tab_state()
            self._clear_page_widgets()
            self.active_tab_key = None
        state = self.open_tabs.pop(tab_key, None)
        if state and state["document"] is not None:
            state["document"].close()
        self._tab_change_blocked = True
        self.tab_bar.removeTab(index)
        next_index = self.tab_bar.currentIndex()
        self._tab_change_blocked = False
        if self.tab_bar.count() == 0:
            self.tabs_toolbar_action.setVisible(False)
            self._show_no_documents()
        elif is_active:
            self._activate_tab(str(self.tab_bar.tabData(next_index)), save_previous=False)

    def close_current_tab(self) -> None:
        if self.tab_bar.currentIndex() >= 0:
            self.close_tab(self.tab_bar.currentIndex())

    def select_tab_step(self, step: int) -> None:
        count = self.tab_bar.count()
        if count > 1:
            self.tab_bar.setCurrentIndex((self.tab_bar.currentIndex() + step) % count)

    def _show_no_documents(self) -> None:
        self._clear_page_widgets()
        self.active_tab_key = None
        self.document = None
        self.file_path = None
        self.page_index = 0
        self.page_text = {}
        self.search_results = []
        self.search_position = -1
        self.last_search_query = ""
        self.page_input.setText("1")
        self.page_total.setText("/ 0")
        self.zoom_input.setText("100")
        self.search_box.clear()
        self.search_count_label.setText("0/0")
        self.page_prev_button.setEnabled(False)
        self.page_next_button.setEnabled(False)
        self._update_document_controls()
        self.setWindowTitle(APP_NAME)
        if not self.pages_layout.count():
            self._set_empty_state()

    def render_page(self) -> None:
        if self.document is None:
            return
        target = self.page_index
        self._clear_page_widgets()
        for index in range(len(self.document)):
            page = self.document[index]
            label = PdfPageLabel(page, self.zoom, self._set_active_page_label)
            self.pages_layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.page_labels.append(label)
        self.pages_layout.activate()
        self.page_input.setText(str(target + 1))
        self.zoom_input.setText(str(round(self.zoom / RENDER_SCALE * 100)))
        self._apply_search_markers()
        key = self.active_tab_key
        QTimer.singleShot(0, lambda: self.go_to_page(target) if self.active_tab_key == key else None)

    def _clear_page_widgets(self) -> None:
        self.page_labels.clear()
        self.active_page_label = None
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if isinstance(widget, PdfPageLabel):
                    widget.close_textpage()
                    widget.pdf_page.close()
                widget.hide()
                widget.deleteLater()

    def _set_active_page_label(self, label: PdfPageLabel) -> None:
        self.active_page_label = label

    def _scroll_to_page(self, index: int) -> None:
        if not self.page_labels:
            return
        index = max(0, min(index, len(self.page_labels) - 1))
        bar = self.scroll.verticalScrollBar()
        self._jumping = True
        try:
            bar.setValue(self.page_labels[index].y() - 20)
        finally:
            self._jumping = False

    def _sync_page_from_scroll(self, value: int) -> None:
        if not self.page_labels or getattr(self, "_jumping", False):
            return
        center = value + self.scroll.viewport().height() / 2
        index = min(
            range(len(self.page_labels)),
            key=lambda i: abs(self.page_labels[i].geometry().center().y() - center),
        )
        self.page_index = index
        viewport_height = self.scroll.viewport().height()
        for label in self.page_labels:
            if (label.y() + label.height() < value - 2 * viewport_height
                    or label.y() > value + 3 * viewport_height):
                if not label.pixmap().isNull():
                    label.clear()
        self.page_input.setText(str(index + 1))
        self._update_page_buttons()

    def go_to_page(self, index: int) -> None:
        if self.document is None:
            return
        self.page_index = max(0, min(index, len(self.document) - 1))
        self.page_input.setText(str(self.page_index + 1))
        self._update_page_buttons()
        self._scroll_to_page(self.page_index)

    def _update_page_buttons(self) -> None:
        has_document = self.document is not None
        self.page_prev_button.setEnabled(has_document and self.page_index > 0)
        self.page_next_button.setEnabled(has_document and self.page_index < len(self.document) - 1)

    def _page_input_changed(self) -> None:
        if self.document is None:
            self.page_input.setText("1")
            return
        try:
            page_number = int(self.page_input.text())
        except ValueError:
            page_number = self.page_index + 1
        self.go_to_page(page_number - 1)

    def change_zoom(self, delta_percent: int) -> None:
        try:
            current_percent = int(self.zoom_input.text())
        except ValueError:
            current_percent = round(self.zoom / RENDER_SCALE * 100)
        new_percent = max(MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, current_percent + delta_percent))
        self.set_zoom(RENDER_SCALE * new_percent / 100.0)

    def _zoom_input_changed(self) -> None:
        try:
            percent = int(self.zoom_input.text())
        except ValueError:
            percent = round(self.zoom / RENDER_SCALE * 100)
        percent = max(MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, percent))
        self.set_zoom(RENDER_SCALE * percent / 100.0)

    def set_zoom(self, value: float) -> None:
        self.zoom = max(RENDER_SCALE * MIN_ZOOM_PERCENT / 100.0,
                        min(value, RENDER_SCALE * MAX_ZOOM_PERCENT / 100.0))
        self.render_page()

    def fit_page(self, *, width_only=False) -> None:
        if self.document is None:
            return
        page = self.document[self.page_index]
        try:
            width, height = page.get_size()
        finally:
            page.close()
        viewport = self.scroll.viewport()
        zoom = max(1, viewport.width() - 48) / width
        if not width_only:
            zoom = min(zoom, max(1, viewport.height() - 48) / height)
        self.set_zoom(zoom)

    def eventFilter(self, watched, event):
        if (getattr(self, "scroll", None) is not None and watched is self.scroll.viewport() and event.type() == QEvent.Type.Wheel
                and self.document is not None
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                self.change_zoom(10 if delta > 0 else -10)
            return True
        return super().eventFilter(watched, event)

    def copy_selected_text(self) -> None:
        label = self.active_page_label
        if label is None:
            self.statusBar().showMessage("Hãy kéo chọn phần chữ trên trang PDF trước.")
            return
        text = label.copy_selection()
        if not text:
            self.statusBar().showMessage("Chưa có chữ được chọn để sao chép.")
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Đã sao chép {len(text)} ký tự.")

    def _text_for_page(self, index: int) -> str:
        if index not in self.page_text:
            page = self.document[index]
            textpage = page.get_textpage()
            self.page_text[index] = textpage.get_text_range()
            textpage.close()
        return self.page_text[index]

    def _apply_search_markers(self) -> None:
        matches_by_page: dict[int, list[tuple[int, int]]] = {}
        for page_index, char_index, char_count in self.search_results:
            matches_by_page.setdefault(page_index, []).append((char_index, char_count))
        active = None
        if 0 <= self.search_position < len(self.search_results):
            active = self.search_results[self.search_position]
        for page_index, label in enumerate(self.page_labels):
            active_span = (active[1], active[2]) if active and active[0] == page_index else None
            label.set_search_matches(matches_by_page.get(page_index, []), active_span)

    def _on_search_text_changed(self, text: str) -> None:
        query = text.strip().casefold()
        if query == self.last_search_query:
            return
        self.search_results.clear()
        self.search_position = -1
        self.last_search_query = ""
        self.search_count_label.setText("0/0")
        self._apply_search_markers()

    def _find_all(self) -> None:
        if self.document is None:
            return
        query = self.search_box.text().strip().casefold()
        self.search_results = []
        self.search_position = -1
        self.last_search_query = query
        if not query:
            self._apply_search_markers()
            self.search_count_label.setText("0/0")
            self.statusBar().showMessage("Nhập từ khóa để tìm trong tài liệu.")
            return
        for page_index in range(len(self.document)):
            textpage = self.document[page_index].get_textpage()
            searcher = textpage.search(query, match_case=False, match_whole_word=False)
            try:
                while True:
                    result = searcher.get_next()
                    if result is None:
                        break
                    char_index, char_count = result
                    self.search_results.append((page_index, char_index, char_count))
            finally:
                searcher.close()
                textpage.close()
        self._apply_search_markers()
        if not self.search_results:
            self.search_count_label.setText("0/0")
            self.statusBar().showMessage("Không có kết quả. Enter/F3: tiếp • Shift+Enter/Shift+F3: trước")
            return
        self.search_position = 0
        self._show_search_result()

    def _show_search_result(self) -> None:
        if not self.search_results:
            return
        page_index, start, _ = self.search_results[self.search_position]
        self.search_count_label.setText(f"{self.search_position + 1}/{len(self.search_results)}")
        self._apply_search_markers()
        self.go_to_page(page_index)
        label = self.page_labels[page_index]
        rect = label._char_rect(label._get_textpage(), start)
        if rect is not None:
            self.scroll.ensureVisible(label.x() + round(rect[0]), label.y() + round(rect[1]), 30, 60)
        self.statusBar().showMessage(
            f"Kết quả {self.search_position + 1}/{len(self.search_results)} — trang {page_index + 1}"
            " • Enter/F3: tiếp • Shift+Enter/Shift+F3: trước"
        )

    def search_next(self) -> None:
        query = self.search_box.text().strip().casefold()
        if not self.search_results or not query or query != self.last_search_query:
            self._find_all()
            return
        self.search_position = (self.search_position + 1) % len(self.search_results)
        self._show_search_result()

    def search_previous(self) -> None:
        query = self.search_box.text().strip().casefold()
        if not self.search_results or not query or query != self.last_search_query:
            self._find_all()
            return
        self.search_position = (self.search_position - 1) % len(self.search_results)
        self._show_search_result()

    def _update_document_controls(self):
        for action in self.pdf_actions:
            action.setVisible(self.document is not None)
        self.print_button.setEnabled(self.file_path is not None)
        self.office_toolbar_action.setVisible(self.file_path is not None and self.document is None)

    @staticmethod
    def _file_icon(path):
        _, _, letter, color = OFFICE_TYPES.get(path.suffix.lower(), ("", "", "PDF", "#cf2929"))
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        with QPainter(pixmap) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(0, 0, 32, 32, 5, 5)
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(QFont("Segoe UI", 9 if letter == "PDF" else 15, QFont.Weight.Bold))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, letter)
        return QIcon(pixmap)

    @staticmethod
    def _toolbar_icon(kind):
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        with QPainter(pixmap) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#25364e"), 1.7))
            if kind == "brand":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#d9242d"))
                painter.drawRoundedRect(1, 1, 22, 22, 4, 4)
                painter.setPen(Qt.GlobalColor.white)
                painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
                painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "T")
            elif kind == "open":
                painter.drawRoundedRect(2, 7, 20, 13, 2, 2)
                painter.drawLine(3, 7, 3, 4)
                painter.drawLine(3, 4, 10, 4)
                painter.drawLine(10, 4, 13, 7)
            elif kind == "recent":
                painter.drawEllipse(3, 3, 18, 18)
                painter.drawLine(12, 7, 12, 12)
                painter.drawLine(12, 12, 16, 14)
            else:
                painter.drawRoundedRect(2, 8, 20, 10, 2, 2)
                painter.fillRect(6, 13, 12, 9, QColor("#e9edf5"))
                painter.drawRect(6, 13, 12, 9)
                painter.drawRect(6, 2, 12, 6)
                painter.drawLine(9, 17, 15, 17)
        return QIcon(pixmap)

    def _open_office(self, path, *, printing=False):
        try:
            hwnd = show_office(path, printing=printing)
            if hwnd and not printing:
                if self.office_window is None or self.office_window.hwnd != hwnd:
                    self._restore_office_window()
                    self.office_window = OfficeWindow(hwnd)
                self._align_office_window()
            elif not printing:
                self.statusBar().showMessage("Đã gửi tệp tới Microsoft Office. Kiểm tra cửa sổ Office trên thanh tác vụ.")
            self._record_recent_file(path)
        except Exception as exc:
            QMessageBox.warning(self, "Microsoft Office",
                                f"Không mở được thao tác trong Microsoft Office.\n{exc}")

    def _set_office_caption(self, hidden):
        self.settings.setValue("hideOfficeCaption", hidden)
        self._align_office_window()

    def _align_office_window(self):
        if getattr(self, "office_window", None) is None or self.isMinimized():
            return
        try:
            from ctypes import byref, c_void_p, windll
            from ctypes.wintypes import POINT, RECT

            # Native client coordinates account for the monitor's DPI.
            hwnd = c_void_p(int(self.scroll.winId()))
            origin, size = POINT(), RECT()
            if windll.user32.GetClientRect(hwnd, byref(size)) and windll.user32.ClientToScreen(hwnd, byref(origin)):
                self.office_window.move(origin.x, origin.y, size.right, size.bottom,
                                        hide_title=self.hide_caption.isChecked())
        except Exception:
            self._restore_office_window()

    def _restore_office_window(self):
        window, self.office_window = self.office_window, None
        if window is not None:
            try:
                window.restore()
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._align_office_window)

    def moveEvent(self, event):
        super().moveEvent(event)
        QTimer.singleShot(0, self._align_office_window)

    def verify_signatures(self):
        if self.file_path is None or self.document is None:
            return
        try:
            from signatures import signature_report
            report = signature_report(self.file_path)
        except Exception as exc:
            report = f"Không xác minh được chữ ký số trong tệp này.\n{exc}"
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Chữ ký số")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(report)
        dialog.exec()

    def print_document(self) -> None:
        if self.document is not None:
            dialog = PdfPrintDialog(self.document, self.page_index, self.settings, self)
            dialog.exec()
        elif self.file_path is not None:
            self._open_office(self.file_path, printing=True)

    def closeEvent(self, event) -> None:
        self._restore_office_window()
        self._clear_page_widgets()
        for state in self.open_tabs.values():
            try:
                if state["document"] is not None:
                    state["document"].close()
            except Exception:
                pass
        self.open_tabs.clear()
        event.accept()


def register_pdf_open_with() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    import winreg

    exe_path = str(Path(sys.executable).resolve())
    exe_name = Path(exe_path).name
    classes = r"Software\Classes"
    app_key = classes + rf"\Applications\{exe_name}"
    prog_id = "HXPDF.Document"
    command = f'"{exe_path}" "%1"'

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_key) as key:
        winreg.SetValueEx(key, "FriendlyAppName", 0, winreg.REG_SZ, APP_NAME)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_key + r"\SupportedTypes") as key:
        winreg.SetValueEx(key, ".pdf", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_key + r"\shell\open\command") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + rf"\{prog_id}") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "HX PDF document")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + rf"\{prog_id}\DefaultIcon") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f'"{exe_path}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + rf"\{prog_id}\shell\open\command") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + r"\.pdf\OpenWithProgids") as key:
        winreg.SetValueEx(key, prog_id, 0, winreg.REG_SZ, "")

    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass


def main() -> int:
    input_files = list(sys.argv[1:])
    try:
        register_pdf_open_with()
    except OSError:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(resource_path("app_icon.png"))))
    window = PdfReaderWindow()
    window.show()
    candidates = [
        Path(argument.strip('"'))
        for argument in input_files
        if Path(argument.strip('"')).suffix.lower() in DOCUMENT_TYPES and Path(argument.strip('"')).is_file()
    ]
    if candidates:
        QTimer.singleShot(0, lambda paths=candidates: [window.open_file(path) for path in paths])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
