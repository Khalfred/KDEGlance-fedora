# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared protocol and lossless local-path handling (no GUI required)."""
import os
from pathlib import Path
import re
from PyQt6.QtCore import QUrl

VERSION = "1.0.1"
BUS = "io.github.KDEGlance2"
OBJECT = "/io/github/KDEGlance2/Preview"
INTERFACE = BUS + ".Preview1"
RAW_EXTENSIONS = {".cr2", ".cr3", ".crw", ".dng", ".nef", ".nrw", ".arw", ".sr2", ".srf", ".orf",
                  ".rw2", ".raf", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".kdc", ".mrw"}
EXTENSIONS = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".gif", ".heic", ".heif",
              ".avif", ".jxl", ".tif", ".tiff", ".ico", ".cur", ".icns", ".svg", ".svgz", ".tga",
              ".psd", ".exr", ".hdr", ".qoi", ".jp2", ".kra", ".ora", ".xcf", ".dds", ".pcx",
              ".ppm", ".pgm", ".pbm", ".xpm"} | RAW_EXTENSIONS
AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".wav", ".m4a", ".aac", ".opus", ".oga", ".aiff",
                    ".aif", ".aifc", ".wma", ".ape", ".wv", ".mka", ".m4b", ".amr", ".ac3", ".dsf"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpeg", ".mpg", ".ts", ".mts", ".m2ts", ".ogv", ".3gp", ".wmv", ".flv", ".rmvb"}
MEDIA_EXTENSIONS = EXTENSIONS | AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
PDF_EXTENSIONS = {".pdf"}
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp"}
ARCHIVE_EXTENSIONS = {".zip", ".jar", ".apk", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".zst", ".7z", ".rar", ".cbz"}


class AllFiles:
    """Extension filter that accepts every regular file (any-type document mode)."""
    def __contains__(self, suffix):
        return True


ALL_FILES = AllFiles()


def media_kind(path):
    if os.path.isdir(path):
        return "document"
    suffix = Path(path).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return "image" if suffix in EXTENSIONS else "document"


def local_path(value):
    if not value or "\0" in value:
        raise ValueError("Пустой путь или недопустимый нулевой символ")
    if value.startswith("file:"):
        url = QUrl(value)
        if not url.isLocalFile() or url.host() not in ("", "localhost"):
            raise ValueError("Поддерживаются только локальные файлы")
        value = url.toLocalFile()
    elif not os.path.isabs(value) and "://" in value:
        raise ValueError("Поддерживаются только локальные файлы")
    # Literal percent signs and leading/trailing whitespace are preserved.
    return os.path.abspath(value)


def natural_key(path):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r"(\d+)", Path(path).name))


def neighbours(path, cancelled, extensions=EXTENSIONS):
    result = []
    try:
        with os.scandir(os.path.dirname(path)) as entries:
            for entry in entries:
                if cancelled.is_set():
                    return [path]
                if (Path(entry.name).suffix.lower() in extensions and entry.is_file()
                        and not (extensions is ALL_FILES and entry.name.startswith("."))):
                    result.append(entry.path)
    except OSError:
        return [path]
    result.sort(key=natural_key)
    return result if path in result else [path]

