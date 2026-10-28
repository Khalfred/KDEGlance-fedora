# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent video preview with the accepted music controls, left unchanged."""
import json
from pathlib import Path
import subprocess
from PyQt6.QtCore import Qt, QPointF, QUrl, QRectF, QSize, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QFont
from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink, QVideoFrame
from interactions import ActionButton
from window import fill_scale, fit_box, preview_size
from audio import Artwork, MediaWindow



PORTRAIT_FACTOR = 1.15
# Fixed, not the controls' minimumSizeHint(): that reports 318 px before polish and
# varies with the time labels, which made visible windows widen unpredictably.
MIN_VIDEO_WINDOW = QSize(220, 120)


def probe_size(path):
    """Displayed video size via ffprobe (pixel aspect and rotation applied), or None."""
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                 "stream=width,height,sample_aspect_ratio:stream_side_data=rotation:"
                                 "stream_tags=rotate", "-of", "json", path],
                                capture_output=True, text=True, timeout=3)
        stream = json.loads(result.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        return None
    try:
        num, den = (int(part) for part in stream.get("sample_aspect_ratio", "1:1").split(":"))
        if num > 0 and den > 0:
            width = round(width*num/den)
    except ValueError:
        pass
    rotation = stream.get("tags", {}).get("rotate", 0)
    for data in stream.get("side_data_list", []):
        rotation = data.get("rotation", rotation)
    try:
        if round(float(rotation)) % 180:
            width, height = height, width
    except ValueError:
        pass
    return QSize(width, height) if width > 0 and height > 0 else None

class VideoCanvas(Artwork):
    zoomChanged = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = QVideoFrame()
        self.zoom, self.base_scale, self.pan = 1.0, 1.0, QPointF()
        self.dimensions = QSize()
        self.last = None
        self.manual_rotation = 0
        self.paint_options = QVideoFrame.PaintOptions()
        self.paint_options.aspectRatioMode = Qt.AspectRatioMode.KeepAspectRatio
        self.paint_options.backgroundColor = QColor("#0b1017")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.paint_options.backgroundColor)
        if self.frame.isValid():
            rect = self.image_rect()
            painter.save()
            painter.translate(rect.center())
            painter.rotate(self.manual_rotation)
            width, height = rect.width(), rect.height()
            if self.manual_rotation % 180:
                width, height = height, width
            self.frame.paint(painter, QRectF(-width/2,-height/2,width,height), self.paint_options)
            painter.restore()
        elif not self.error:
            painter.setPen(QColor("#8793a2"))
            painter.setFont(QFont("sans-serif", 13))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Loading video…")
        shade = QLinearGradient(0, self.height()-104, 0, self.height())
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        opacity = getattr(self, "controls_opacity", 1)
        shade.setColorAt(.45, QColor(8, 12, 19, round(95*opacity)))
        shade.setColorAt(1, QColor(8, 12, 19, round(205*opacity)))
        painter.fillRect(self.rect(), shade)
        if self.error:
            painter.fillRect(self.rect(), QColor(10, 16, 24, 170))
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("sans-serif", 10))
            painter.drawText(self.rect().adjusted(18, 18, -18, -self.controls_height-12),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.error)


    def image_rect(self):
        width = self.dimensions.width()*self.base_scale*self.zoom
        height = self.dimensions.height()*self.base_scale*self.zoom
        return QRectF((self.width()-width)/2+self.pan.x(), (self.height()-height)/2+self.pan.y(), width, height)

    def clamp_pan(self):
        rect = self.image_rect()
        x, y = max(0,(rect.width()-self.width())/2), max(0,(rect.height()-self.height())/2)
        self.pan = QPointF(max(-x,min(x,self.pan.x())),max(-y,min(y,self.pan.y())))

    def zoom_wheel(self, event):
        if not self.frame.isValid():
            return
        delta = event.angleDelta().y() or event.pixelDelta().y()
        old = self.image_rect()
        zoom = max(1.0,min(32.0,self.zoom*(1.15**(delta/120))))
        top = event.position()-(event.position()-old.topLeft())*(zoom/self.zoom)
        self.zoom = zoom
        self.pan += top-self.image_rect().topLeft()
        self.zoomChanged.emit()
        self.clamp_pan()
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        self.last = QPointF(event.position())
        super().mousePressEvent(event)

    def update_gesture(self, position):
        super().update_gesture(position)
        if self.dragged and self.zoom > 1 and self.last is not None:
            self.pan += position-self.last
            self.clamp_pan()
            self.update()
        self.last = QPointF(position)


class VideoWindow(MediaWindow):
    canvas_class = VideoCanvas
    settings_file = "video.ini"
    error_text = "Could not play video"

    def __init__(self, close_callback, navigate_callback=None):
        super().__init__(close_callback, navigate_callback)
        self.canvas.zoomChanged.connect(self.resize_for_video_zoom)
        self.frames_received = 0
        self.video_dimensions = QSize()
        self.manual_rotation = 0
        self.video_sink = QVideoSink(self)
        self.player.setVideoSink(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self.frame_changed)

    def add_controls(self, layout):
        self.rotate_button = ActionButton("rotate", self.controls)
        self.fullscreen_button = ActionButton("fullscreen", self.controls)
        self.rotate_button.clicked.connect(self.rotate_video)
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        layout.addWidget(self.rotate_button)
        layout.addWidget(self.fullscreen_button)

    def present(self, screen, token=""):
        if not self.isVisible() and self.isFullScreen():
            self.setWindowState(Qt.WindowState.WindowNoState)
        super().present(screen, token)
        self.resize_video(screen)

    def fitted_size(self, screen, content):
        # Vertical videos get a 15% larger box; the width never drops below the controls.
        portrait = content is not None and content.height() > content.width()
        box = preview_size(screen, self.size_factor*(PORTRAIT_FACTOR if portrait else 1.0))
        return fit_box(box, content, MIN_VIDEO_WINDOW)

    def resize_video(self, screen):
        if self.isFullScreen():
            self.layout().activate()
            self.update_video_scale()
            return
        # The window keeps the size chosen when shown (from ffprobe, before mapping).
        box = self.initial_size(screen)
        self.apply_size(box.width(), box.height())
        size = self.video_dimensions
        if size.isEmpty():
            return
        self.canvas.base_scale = fill_scale(box, size)
        if self.canvas.zoom > 1:
            self.resize_for_video_zoom()

    def update_video_scale(self):
        if not self.video_dimensions.isEmpty() and self.canvas.zoom == 1:
            scale = min(self.canvas.width()/self.video_dimensions.width(), self.canvas.height()/self.video_dimensions.height())
            self.canvas.base_scale = scale if self.isFullScreen() else min(1.0,scale)

    @pyqtSlot()
    def resize_for_video_zoom(self):
        if self.isFullScreen():
            return
        # Zoom stays inside the fixed window; resizing would undo KWin centering.
        self.canvas.clamp_pan()
        self.canvas.update()

    @pyqtSlot()
    def rotate_video(self):
        self.manual_rotation = (self.manual_rotation-90) % 360
        self.canvas.manual_rotation = self.manual_rotation
        if self.canvas.frame.isValid():
            self.video_dimensions = self.display_size(self.canvas.frame)
            if self.manual_rotation % 180:
                self.video_dimensions.transpose()
            self.canvas.dimensions = self.video_dimensions
            self.fit()

    @pyqtSlot()
    def toggle_fullscreen(self):
        self.canvas.zoom, self.canvas.pan = 1.0, QPointF()
        self.target_size = None
        self.size_timer.stop()
        self.setMinimumSize(1,1)
        self.setMaximumSize(16777215,16777215)
        if self.isFullScreen():
            self.showNormal()
            self.resize_video(self.screen())
        else:
            self.showFullScreen()
        self.layout().activate()
        self.update_video_scale()
        self.canvas.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key.Key_F:
            self.toggle_fullscreen()
            event.accept()
        else:
            super().keyPressEvent(event)

    @staticmethod
    def display_size(frame):
        size = frame.surfaceFormat().viewport().size()
        if size.isEmpty():
            size = frame.size()
        rotation = frame.rotation().value + frame.surfaceFormat().rotation().value
        if rotation % 180:
            size.transpose()
        return size

    def open_video(self, path):
        self.stop_video()
        self.reset_controls(path)
        self.canvas.frame = QVideoFrame()
        self.frames_received = 0
        self.video_dimensions = QSize()
        self.manual_rotation = 0
        self.canvas.manual_rotation = 0
        self.canvas.zoom, self.canvas.pan = 1.0, QPointF()
        self.canvas.update()
        if not Path(path).is_file():
            self.content_size = None
            self.player_error(None, "File not found or not accessible")
            return
        self.content_size = probe_size(path)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    @pyqtSlot(QVideoFrame)
    def frame_changed(self, frame):
        if self.phase == "idle" or self.player.source().isEmpty():
            return
        if frame.isValid():
            # Keep just the newest frame; Qt paints rotation/aspect correctly.
            self.canvas.frame = QVideoFrame(frame)
            size = self.display_size(self.canvas.frame)
            if self.manual_rotation % 180:
                size.transpose()
            self.canvas.dimensions = size
            if size != self.video_dimensions:
                self.video_dimensions = size
                self.resize_video(self.screen())
            self.frames_received += 1
            self.canvas.update()

    def stop_video(self):
        self.stop_player()
        self.canvas.frame = QVideoFrame()
        self.canvas.update()

    def hideEvent(self, event):
        if hasattr(self, "video_sink"):
            self.stop_video()
        super().hideEvent(event)

    @pyqtSlot(QMediaPlayer.MediaStatus)
    def status_changed(self, status):
        if (status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia)
                and not self.player.hasVideo()):
            self.player_error(None, "The file has no video track")
        else:
            super().status_changed(status)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "video_sink"):
            # Keep the same controls usable on native-size portrait videos.
            compact = self.width() < 340
            self.controls.layout().setContentsMargins(6 if compact else 12, 10, 6 if compact else 12, 10)
            self.controls.layout().setSpacing(4 if compact else 7)
            self.play_button.setFixedSize(36 if compact else 42, 36 if compact else 42)
            self.elapsed.setVisible(not compact)
            self.rotate_button.setFixedWidth(24 if compact else 30)
            self.fullscreen_button.setFixedWidth(24 if compact else 30)
            self.speaker_slot.setFixedWidth(36 if compact else 56)
            self.volume_panel.setFixedWidth(36 if compact else 56)
            self.seek_bar.setMinimumWidth(16 if compact else 44)
            self.volume_panel.layout().setContentsMargins(2 if compact else 9, 12, 2 if compact else 9, 72)
            self.position_volume_panel()
            self.layout().activate()
            self.update_video_scale()
            self.canvas.clamp_pan()

    def canvas_wheel(self, event):
        self.canvas.zoom_wheel(event)

    def fit(self):
        self.canvas.zoom, self.canvas.pan = 1.0, QPointF()
        self.resize_video(self.screen())
        self.canvas.update()

    def snapshot(self):
        return {**super().snapshot(), "has_frame": self.canvas.frame.isValid(),
                "frames_received": self.frames_received,
                "has_video": self.player.hasVideo(), "has_audio": self.player.hasAudio(),
                "frame_size": [self.canvas.frame.width(), self.canvas.frame.height()],
                "display_size": [self.video_dimensions.width(), self.video_dimensions.height()],
                "zoom": self.canvas.zoom, "rotation": self.manual_rotation}
