# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only previews for documents and any other file in the fixed preview window."""
import hashlib
import html
import os
import stat
from pathlib import Path
import re
import shutil
import tarfile
import zipfile
from PyQt6.QtCore import (Qt, QDateTime, QEvent, QFileInfo, QLocale, QMargins, QMimeDatabase, QPointF,
                          QProcess, QSize, QThreadPool, QTimer, QUrl)
from PyQt6.QtGui import QColor, QFontDatabase, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtWidgets import (QAbstractItemView, QAbstractScrollArea, QFormLayout, QHBoxLayout,
                             QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QSizePolicy,
                             QTextBrowser, QVBoxLayout, QWidget)
from core import ARCHIVE_EXTENSIONS, MARKDOWN_EXTENSIONS, OFFICE_EXTENSIONS, PDF_EXTENSIONS
import highlight
from fileinfo import FolderScan, binary_format, cached_thumbnail, desktop_icon_name, permissions
from window import PreviewWindow, preview_size

MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 5000
CONVERT_TIMEOUT_MS = 60_000
SIDEBAR_WIDTH = 150
PAGE_MARGIN = 8
PAGED_HEIGHT = 0.9  # share of the screen's available height for paged documents
A4_ASPECT = 210 / 297
THUMBNAILS_PER_TICK = 2
TEXT_SUFFIXES = {".txt", ".log", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".toml", ".ini",
                 ".conf", ".cfg", ".py", ".sh", ".c", ".h", ".cpp", ".hpp", ".rs", ".go", ".js",
                 ".ts", ".java", ".kt", ".rb", ".php", ".pl", ".lua", ".sql", ".css", ".html",
                 ".htm", ".tex", ".srt", ".service", ".spec", ".patch", ".diff"}
STYLE = """
    QWidget#documentRoot { background: #111111; }
    QLabel#documentTitle { color: #dce2eb; background: #1b1d21; padding: 6px 12px; font-size: 12px; }
    QPlainTextEdit, QTextBrowser { background: #111111; color: #dce2eb; border: none;
        selection-background-color: #3d6ea8; padding: 6px; }
    QLabel#documentMessage { color: #dce2eb; background: #111111; padding: 20px; }
    QWidget#infoPanel { background: #111111; }
    QWidget#infoPanel QLabel { color: #dce2eb; background: transparent; }
    QLabel#infoName { font-size: 15px; font-weight: bold; }
    QLabel#infoKey { color: #8d96a3; }
    QListWidget#pageList { background: #17191c; border: none; color: #8d96a3; outline: none; }
    QListWidget#pageList::item { padding: 4px; border-radius: 4px; }
    QListWidget#pageList::item:selected { background: #2b3a4f; color: #dce2eb; }
"""


def cache_root():
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home()/".cache")/"kdeglance2"


def human_size(size):
    return QLocale().formattedDataSize(size)


def looks_binary(sample):
    return b"\0" in sample


def office_text(path):
    """Plain-text fallback for OOXML/ODF documents when LibreOffice is absent."""
    members = {".docx": ["word/document.xml"], ".odt": ["content.xml"], ".odp": ["content.xml"],
               ".ods": ["content.xml"], ".pptx": None, ".xlsx": ["xl/sharedStrings.xml"]}
    wanted = members.get(Path(path).suffix.lower(), [])
    with zipfile.ZipFile(path) as archive:
        if wanted is None:
            wanted = sorted((n for n in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                            key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        parts = []
        for name in wanted:
            xml = archive.read(name)[:MAX_TEXT_BYTES].decode("utf-8", "replace")
            xml = re.sub(r"</(w:p|text:p|text:h|a:p|si)>", "\n", xml)
            parts.append(html.unescape(re.sub(r"<[^>]+>", "", xml)))
    return "\n".join(parts).strip()


def archive_listing(path):
    lines = []
    suffix = Path(path).suffix.lower()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist()[:MAX_ARCHIVE_ENTRIES]:
                lines.append(f"{human_size(info.file_size):>10}  {info.filename}")
            total = len(archive.infolist())
    elif suffix != ".7z" and tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            total = 0
            for member in archive:
                total += 1
                if total <= MAX_ARCHIVE_ENTRIES:
                    lines.append(f"{human_size(member.size):>10}  {member.name}{'/' if member.isdir() else ''}")
    else:
        return None
    header = f"{total} entries" + (f" (first {MAX_ARCHIVE_ENTRIES} shown)" if total > MAX_ARCHIVE_ENTRIES else "")
    return header + "\n\n" + "\n".join(lines)


class ElidedLabel(QLabel):
    """One-line label that elides in the middle instead of overflowing the panel."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.full_text = text
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        super().setText(text)

    def minimumSizeHint(self):
        return QSize(20, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        text = self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideMiddle, self.width())
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)


class DocumentWindow(PreviewWindow):
    size_factor = 1.0
    def __init__(self, close_callback, navigate_callback=None):
        super().__init__(close_callback, navigate_callback or (lambda _: None))
        old_canvas = self.canvas
        self.layout().removeWidget(old_canvas)
        old_canvas.hide()
        old_canvas.deleteLater()
        self.canvas = QWidget(self)
        self.canvas.setObjectName("documentRoot")
        self.canvas.setStyleSheet(STYLE)
        self.layout().addWidget(self.canvas)
        root = QVBoxLayout(self.canvas)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.title = QLabel(self.canvas)
        self.title.setObjectName("documentTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.installEventFilter(self)
        root.addWidget(self.title)
        self.body = QHBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self.body, 1)
        self.content = None
        self.pdf = QPdfDocument(self)
        self.process = None
        self.process_timer = QTimer(self)
        self.process_timer.setSingleShot(True)
        self.process_timer.timeout.connect(self.conversion_timeout)
        self.phase, self.path, self.error, self.kind = "idle", "", "", ""
        self.theme = ""
        self.generation = 0
        self.folder_scan = None
        self.folder_pool = QThreadPool(self)
        self.folder_pool.setMaxThreadCount(1)
        self.size_value = None
        self.pages = None
        self.pdf_view = None
        self.tall = False
        self.wheel_remainder = 0.0
        self.thumbnail_queue = []
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.timeout.connect(self.render_thumbnails)

    # Content widgets -----------------------------------------------------
    def set_content(self, widget):
        if self.content is not None:
            self.body.removeWidget(self.content)
            self.content.hide()
            self.content.deleteLater()
        self.content = widget
        self.body.addWidget(widget)
        targets = [widget, *widget.findChildren(QWidget)]
        if isinstance(widget, QAbstractScrollArea):
            targets.append(widget.viewport())
        for target in targets:
            target.installEventFilter(self)
        widget.show()

    def show_message(self, text):
        label = QLabel(text, self.canvas)
        label.setObjectName("documentMessage")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        self.set_content(label)

    def show_text(self, text, markdown=False):
        if markdown:
            view = QTextBrowser(self.canvas)
            view.setOpenLinks(False)
            view.setMarkdown(text)
        else:
            view = QPlainTextEdit(self.canvas)
            view.setReadOnly(True)
            view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
            view.setPlainText(text)
        view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.set_content(view)

    def show_code(self, ok, output, text):
        """Highlighted code with line numbers, in the colors of the chosen editor theme."""
        parsed = highlight.with_line_numbers(output) if ok else None
        if parsed is None:
            self.kind = "text"
            self.show_text(text)
            self.ready()
            return
        background, foreground, code = parsed
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        view = QTextBrowser(self.canvas)
        view.setOpenLinks(False)
        view.setLineWrapMode(QTextBrowser.LineWrapMode.NoWrap)
        view.document().setDefaultFont(font)
        view.setStyleSheet(f"QTextBrowser {{ background: {background}; color: {foreground}; "
                           "border: none; padding: 6px; }")
        view.setHtml(f'<pre style="font-family:\'{font.family()}\'; margin:0">{code}</pre>')
        view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.set_content(view)
        self.ready()

    def show_pdf(self, path):
        self.pdf.close()
        error = self.pdf.load(str(path))
        if error != QPdfDocument.Error.None_:
            self.fail(f"Cannot open PDF ({error.name})")
            return
        # Page thumbnails on the side, pages on the right, as in a PDF viewer.
        container = QWidget(self.canvas)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        pages = QListWidget(container)
        pages.setObjectName("pageList")
        pages.setFixedWidth(SIDEBAR_WIDTH)
        pages.setViewMode(QListWidget.ViewMode.ListMode)
        pages.setFlow(QListWidget.Flow.TopToBottom)
        pages.setIconSize(QSize(SIDEBAR_WIDTH-40, SIDEBAR_WIDTH-40))
        pages.setSpacing(4)
        pages.setUniformItemSizes(True)
        pages.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pages.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        pages.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        view = QPdfView(container)
        view.setDocument(self.pdf)
        # One whole page at a time; arrow keys and the wheel turn pages.
        view.setPageMode(QPdfView.PageMode.SinglePage)
        view.setZoomMode(QPdfView.ZoomMode.FitInView)
        view.setDocumentMargins(QMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN))
        # The whole page always fits. Scrollbars would oscillate at the fit boundary
        # (hide -> wider viewport -> bigger page -> show) in an endless resize loop.
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setStyleSheet("background: #111111; border: none;")
        placeholder = QPixmap(pages.iconSize())
        placeholder.fill(QColor("#24272c"))
        for page in range(self.pdf.pageCount()):
            item = QListWidgetItem(QIcon(placeholder), str(page+1))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            item.setSizeHint(QSize(SIDEBAR_WIDTH-12, SIDEBAR_WIDTH-12))
            pages.addItem(item)
        layout.addWidget(pages)
        layout.addWidget(view, 1)
        self.pages, self.pdf_view = pages, view
        navigator = view.pageNavigator()
        pages.currentRowChanged.connect(
            lambda row: row >= 0 and navigator.currentPage() != row and navigator.jump(row, QPointF()))
        navigator.currentPageChanged.connect(self.page_changed)
        if pages.count():
            pages.setCurrentRow(0)
        self.set_content(container)
        self.show_page_number(0)
        self.thumbnail_queue = list(range(self.pdf.pageCount()))
        self.thumbnail_timer.start(0)
        self.ready()

    def page_changed(self, page):
        self.show_page_number(page)
        if self.pages is not None and 0 <= page < self.pages.count() and self.pages.currentRow() != page:
            self.pages.blockSignals(True)
            self.pages.setCurrentRow(page)
            self.pages.blockSignals(False)
            self.pages.scrollToItem(self.pages.item(page))

    def show_page_number(self, page):
        count = self.pdf.pageCount()
        if count:
            self.title.setText(f"{Path(self.path).name}  —  page {page+1} / {count}")

    def current_page(self):
        return self.pdf_view.pageNavigator().currentPage() if self.pdf_view is not None else -1

    def go_to_page(self, page):
        """Jump by index; returns False past either end so the caller can change file."""
        if self.pdf_view is None or not 0 <= page < self.pdf.pageCount():
            return False
        navigator = self.pdf_view.pageNavigator()
        if navigator.currentPage() != page:
            navigator.jump(page, QPointF())
        return True

    def page_aspect(self):
        size = self.pdf.pagePointSize(0) if self.pdf.pageCount() else None
        return size.width()/size.height() if size and not size.isEmpty() else A4_ASPECT

    def render_thumbnails(self):
        """Render a few page thumbnails per event-loop turn so big PDFs stay responsive."""
        if self.pages is None or not self.thumbnail_queue:
            self.thumbnail_timer.stop()
            return
        edge = self.pages.iconSize()
        for _ in range(THUMBNAILS_PER_TICK):
            if not self.thumbnail_queue:
                break
            page = self.thumbnail_queue.pop(0)
            size = self.pdf.pagePointSize(page)
            if size.isEmpty():
                continue
            scaled = size.toSize().scaled(edge, Qt.AspectRatioMode.KeepAspectRatio)
            image = self.pdf.render(page, scaled, QPdfDocumentRenderOptions())
            if not image.isNull():
                framed = QImage(image.size(), QImage.Format.Format_RGB32)
                framed.fill(QColor("white"))
                painter = QPainter(framed)
                painter.drawImage(0, 0, image)
                painter.end()
                icon = QIcon(QPixmap.fromImage(framed))
                # Keep the selected page untinted; the item background marks it.
                icon.addPixmap(QPixmap.fromImage(framed), QIcon.Mode.Selected)
                self.pages.item(page).setIcon(icon)

    def show_info(self, path):
        """Thumbnail plus properties, as QuickLook's information panel."""
        database = QMimeDatabase()
        mime = database.mimeTypeForFile(str(path))
        info = path.stat()
        lstat = path.lstat()
        panel = QWidget(self.canvas)
        panel.setObjectName("infoPanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(18)
        edge = max(64, min(128, preview_size(self.screen()).height()-110))
        thumbnail = QLabel(panel)
        thumbnail.setFixedSize(edge, edge)
        thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumbnail.setPixmap(self.info_pixmap(path, mime, edge))
        layout.addWidget(thumbnail, 0, Qt.AlignmentFlag.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(6)
        name = ElidedLabel(path.name or str(path), panel)
        name.setObjectName("infoName")
        column.addWidget(name)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(3)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        def row(key, value):
            label = QLabel(key, panel)
            label.setObjectName("infoKey")
            text = ElidedLabel(value, panel)
            form.addRow(label, text)
            return text

        locale = QLocale()

        def when(seconds):
            return locale.toString(QDateTime.fromSecsSinceEpoch(int(seconds)), QLocale.FormatType.ShortFormat)

        row("Type", mime.comment() or mime.name())
        if path.is_dir():
            self.size_value = row("Size", "Calculating…")
            self.start_folder_scan(path)
            usage = shutil.disk_usage(path)
            row("Free space", f"{human_size(usage.free)} of {human_size(usage.total)}")
        else:
            row("Size", f"{human_size(info.st_size)} ({locale.toString(info.st_size)} bytes)")
            details = binary_format(path) if info.st_mode & 0o111 or mime.name().startswith("application/x-") else ""
            if details:
                row("Format", details)
        if stat.S_ISLNK(lstat.st_mode):
            row("Link to", os.readlink(path))
        row("Location", str(path.parent))
        row("Modified", when(info.st_mtime))
        row("Accessed", when(info.st_atime))
        born = QFileInfo(str(path)).birthTime()
        if born.isValid():
            row("Created", locale.toString(born, QLocale.FormatType.ShortFormat))
        mode, owner = permissions(info)
        row("Permissions", mode + ("  (executable)" if path.is_file() and info.st_mode & 0o111 else ""))
        row("Owner", owner)
        column.addLayout(form)
        column.addStretch()
        layout.addLayout(column, 1)
        self.set_content(panel)
        self.ready()

    @staticmethod
    def info_pixmap(path, mime, edge):
        image = cached_thumbnail(path)
        if image is not None:
            return QPixmap.fromImage(image).scaled(edge, edge, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation)
        names = []
        if path.suffix.lower() == ".desktop":
            names.append(desktop_icon_name(path))
        if path.is_file() and os.access(path, os.X_OK) and not mime.name().startswith("text/"):
            names.append("application-x-executable")
        names += [mime.iconName(), mime.genericIconName(), "unknown"]
        for icon_name in names:
            icon = QIcon(icon_name) if icon_name.startswith("/") else QIcon.fromTheme(icon_name)
            if icon_name and not icon.isNull():
                return icon.pixmap(QSize(edge, edge))
        return QPixmap()

    def start_folder_scan(self, path):
        self.generation += 1
        scan = FolderScan(self.generation, str(path))
        scan.signals.done.connect(self.folder_scanned)
        self.folder_scan = scan
        self.folder_pool.start(scan)

    def folder_scanned(self, generation, result):
        if generation != self.generation or self.size_value is None:
            return
        self.folder_scan = None
        prefix = "" if result["complete"] else "at least "
        self.size_value.setText(f"{prefix}{human_size(result['size'])} — "
                                f"{result['files']} files, {result['folders']} folders")

    # Loading -------------------------------------------------------------
    def open_document(self, path):
        self.stop_document()
        self.path, self.phase, self.error = path, "loading", ""
        file = Path(path)
        self.title.setText(file.name)
        self.setWindowTitle(file.name + " — KDEGlance")
        suffix = file.suffix.lower()
        self.tall = file.is_file() and suffix in PDF_EXTENSIONS | OFFICE_EXTENSIONS
        try:
            if not file.exists():
                raise OSError("File not found or not accessible")
            if not file.is_file() or suffix == ".desktop" or (os.access(file, os.X_OK) and suffix not in
                                      PDF_EXTENSIONS | OFFICE_EXTENSIONS | MARKDOWN_EXTENSIONS):
                # Folders, executables and special files: thumbnail and properties.
                self.kind = "folder" if file.is_dir() else "info"
                self.show_info(file)
            elif suffix in PDF_EXTENSIONS:
                self.kind = "pdf"
                self.show_pdf(file)
            elif suffix in OFFICE_EXTENSIONS:
                self.kind = "office"
                self.open_office(file)
            elif suffix in ARCHIVE_EXTENSIONS and (listing := archive_listing(file)) is not None:
                self.kind = "archive"
                self.show_text(listing)
                self.ready()
            elif suffix in ARCHIVE_EXTENSIONS and shutil.which("7z"):
                self.kind = "archive"
                self.run_process("7z", ["l", "-ba", str(file)], self.archive_listed, "Reading archive…")
            elif self.is_text(file, suffix):
                self.kind = "markdown" if suffix in MARKDOWN_EXTENSIONS else "text"
                self.tall = True  # text gets the same tall, page-shaped window as PDFs
                with open(file, "rb") as stream:
                    raw = stream.read(MAX_TEXT_BYTES + 1)
                text = raw[:MAX_TEXT_BYTES].decode("utf-8", "replace")
                if len(raw) > MAX_TEXT_BYTES:
                    text += f"\n\n[… preview truncated at {human_size(MAX_TEXT_BYTES)}]"
                if (self.kind == "text" and highlight.available()
                        and file.stat().st_size <= highlight.MAX_HIGHLIGHT_BYTES):
                    self.kind = "code"
                    self.theme = highlight.choose_theme(QMimeDatabase().mimeTypeForFile(str(file)).name())
                    self.run_process(highlight.TOOL, ["-t", self.theme, str(file)],
                                     lambda ok, output: self.show_code(ok, output, text), "")
                else:
                    self.show_text(text, markdown=self.kind == "markdown")
                    self.ready()
            else:
                self.kind = "info"
                self.show_info(file)
        except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError, KeyError) as error:
            self.fail(str(error))

    @staticmethod
    def is_text(file, suffix):
        if suffix in TEXT_SUFFIXES or suffix in MARKDOWN_EXTENSIONS:
            return True
        mime = QMimeDatabase().mimeTypeForFile(str(file))
        if not mime.inherits("text/plain"):
            return False
        with open(file, "rb") as stream:
            return not looks_binary(stream.read(8192))

    def open_office(self, file):
        stat = file.stat()
        key = hashlib.sha256(f"{file}\0{stat.st_size}\0{stat.st_mtime_ns}".encode()).hexdigest()[:32]
        outdir = cache_root()/"office"/key
        converted = outdir/(file.stem + ".pdf")
        if converted.is_file():
            self.show_pdf(converted)
            return
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            self.office_fallback(file, "LibreOffice is not installed; showing text only.")
            return
        outdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile = QUrl.fromLocalFile(str(cache_root()/"lo-profile")).toString()
        # A separate profile keeps a running LibreOffice from absorbing the job.
        self.run_process(soffice, [f"-env:UserInstallation={profile}", "--headless", "--norestore",
                                   "--convert-to", "pdf", "--outdir", str(outdir), str(file)],
                         lambda ok, _out: self.office_converted(file, converted, ok),
                         "Converting document…")

    def office_converted(self, file, converted, ok):
        if ok and converted.is_file():
            self.show_pdf(converted)
        else:
            self.office_fallback(file, "LibreOffice could not convert this file; showing text only.")

    def office_fallback(self, file, note):
        try:
            text = office_text(file)
        except (zipfile.BadZipFile, KeyError, OSError):
            text = ""
        if text:
            self.show_text(f"[{note}]\n\n{text}")
            self.ready()
        else:
            self.kind = "info"
            self.show_info(file)

    def archive_listed(self, ok, output):
        if ok and output.strip():
            lines = output.splitlines()
            self.show_text(f"{len(lines)} entries\n\n" + "\n".join(lines[:MAX_ARCHIVE_ENTRIES]))
            self.ready()
        else:
            self.kind = "info"
            self.show_info(Path(self.path))

    def run_process(self, program, arguments, finished, message):
        self.show_message(message)
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        path = self.path

        def done(code, status):
            if process is not self.process:
                return
            self.process = None
            self.process_timer.stop()
            output = bytes(process.readAll()).decode("utf-8", "replace")
            process.deleteLater()
            if self.path == path and self.isVisible():
                finished(status == QProcess.ExitStatus.NormalExit and code == 0, output)

        process.finished.connect(done)
        self.process = process
        self.process_timer.start(CONVERT_TIMEOUT_MS)
        process.start(program, arguments)

    def conversion_timeout(self):
        if self.process:
            self.process.kill()

    def ready(self):
        self.phase, self.error = "ready", ""

    def fail(self, error):
        self.phase, self.error = "error", error
        self.show_message(error)

    def stop_document(self):
        process, self.process = self.process, None
        self.process_timer.stop()
        if process:
            process.kill()
            process.waitForFinished(1000)
            process.deleteLater()
        self.generation += 1
        if self.folder_scan:
            self.folder_scan.cancelled.set()
            self.folder_scan = None
        self.size_value = None
        self.thumbnail_timer.stop()
        self.thumbnail_queue = []
        self.pages = self.pdf_view = None
        if self.content is not None:
            self.body.removeWidget(self.content)
            self.content.hide()
            self.content.deleteLater()
            self.content = None
        self.pdf.close()
        self.phase = "idle"

    # Window behaviour ----------------------------------------------------
    def present(self, screen, token=""):
        super().present(screen, token)
        self.resize_document(screen)

    def initial_size(self, screen):
        box = preview_size(screen)
        if not self.tall:
            return box
        # Tall enough that a whole page fits next to the thumbnail sidebar;
        # text documents use the same A4-shaped window.
        area = screen.availableGeometry()
        height = min(int(area.height()*PAGED_HEIGHT), area.height()-32)
        page_height = height - self.title.sizeHint().height() - 2*PAGE_MARGIN
        width = SIDEBAR_WIDTH + int(page_height*self.page_aspect()) + 2*PAGE_MARGIN + 4
        return QSize(min(max(width, box.width()), area.width()-32), max(height, box.height()))

    def resize_document(self, screen):
        box = self.initial_size(screen)
        self.apply_size(box.width(), box.height())

    def handle_key(self, event):
        """Space/Escape close; arrows turn pages, and change file past the first/last page."""
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            if not event.isAutoRepeat():
                self.close_callback()
            return True
        if self.pdf_view is not None:
            back = key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp)
            forward = key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown)
            if back or forward:
                step = -1 if back else 1
                if not self.go_to_page(self.current_page()+step) and not event.isAutoRepeat():
                    self.navigate_callback(step)
                return True
            if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
                self.go_to_page(0 if key == Qt.Key.Key_Home else self.pdf.pageCount()-1)
                return True
            return False
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            bar = self.content.horizontalScrollBar() if isinstance(self.content, QAbstractScrollArea) else None
            if bar is None or not bar.isVisible():
                if not event.isAutoRepeat():
                    self.navigate_callback(-1 if key == Qt.Key.Key_Left else 1)
                return True
        return False

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.NoModifier and self.handle_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def page_wheel(self, event):
        self.wheel_remainder += (event.angleDelta().y() or event.pixelDelta().y()) / 120
        while abs(self.wheel_remainder) >= 1:
            step = -1 if self.wheel_remainder > 0 else 1
            self.wheel_remainder += step
            self.go_to_page(self.current_page()+step)

    def clear_content(self, message):
        pass

    def fit(self):
        pass

    def hideEvent(self, event):
        self.stop_document()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if self.handle_key(event):
                return True
        if (event.type() == QEvent.Type.Wheel and self.pdf_view is not None
                and watched in (self.pdf_view, self.pdf_view.viewport())):
            self.page_wheel(event)
            return True
        if watched is self.title:
            # The title bar moves the frameless window, like other previews.
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self.windowHandle():
                    self.windowHandle().startSystemMove()
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
                self.close_callback()
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        event.accept()

    def snapshot(self):
        return {"phase": self.phase, "error": self.error, "kind": self.kind, "theme": self.theme,
                "sidebar_pages": self.pages.count() if self.pages is not None else 0,
                "current_page": self.current_page(), "sidebar_row": self.pages.currentRow() if self.pages is not None else -1,
                "thumbnails_pending": len(self.thumbnail_queue),
                "folder_size": self.size_value.text() if self.size_value is not None else "",
                "converting": self.process is not None,
                "pages": self.pdf.pageCount() if self.kind in ("pdf", "office") else 0}
