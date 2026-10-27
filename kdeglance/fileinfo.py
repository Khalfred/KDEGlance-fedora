# SPDX-License-Identifier: GPL-3.0-or-later
"""File properties for the information panel (no GUI widgets here)."""
import grp
import hashlib
import os
from pathlib import Path
import pwd
import stat
import struct
import threading
import time
from PyQt6.QtCore import QObject, QRunnable, QUrl, pyqtSignal
from PyQt6.QtGui import QImage

FOLDER_SCAN_LIMIT = 200_000
FOLDER_SCAN_SECONDS = 8.0
ELF_TYPES = {1: "object", 2: "executable", 3: "PIE / shared", 4: "core dump"}
ELF_MACHINES = {3: "x86", 8: "MIPS", 20: "PowerPC", 21: "PowerPC64", 40: "ARM", 62: "x86-64",
                183: "AArch64", 243: "RISC-V", 258: "LoongArch"}
PE_MACHINES = {0x14c: "x86", 0x8664: "x86-64", 0xaa64: "ARM64", 0x1c4: "ARM"}


def cached_thumbnail(path):
    """Largest valid freedesktop thumbnail (as written by Dolphin/KIO), or None."""
    uri = QUrl.fromLocalFile(str(path)).toString(QUrl.ComponentFormattingOption.FullyEncoded)
    name = hashlib.md5(uri.encode()).hexdigest() + ".png"
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home()/".cache")/"thumbnails"
    try:
        mtime = str(int(Path(path).stat().st_mtime))
    except OSError:
        return None
    for size in ("xx-large", "x-large", "large", "normal"):
        candidate = root/size/name
        if candidate.is_file():
            image = QImage(str(candidate))
            stamp = image.text("Thumb::MTime")
            if not image.isNull() and (not stamp or stamp == mtime):
                return image
    return None


def desktop_icon_name(path):
    """Icon= of a .desktop launcher, so apps show their own icon."""
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            for line in stream.read(65536).splitlines():
                if line.startswith("Icon="):
                    return line[5:].strip()
    except OSError:
        pass
    return ""


def binary_format(path):
    """Short description of executables: ELF/AppImage, Windows PE, or script interpreter."""
    try:
        with open(path, "rb") as stream:
            head = stream.read(4096)
    except OSError:
        return ""
    if head[:4] == b"\x7fELF" and len(head) >= 20:
        bits = {1: "32-bit", 2: "64-bit"}.get(head[4], "")
        endian = "<" if head[5] == 1 else ">"
        kind, machine = struct.unpack(endian + "HH", head[16:20])
        text = f"ELF {bits} {ELF_TYPES.get(kind, 'file')}, {ELF_MACHINES.get(machine, f'machine {machine}')}"
        if head[8:11] == b"AI\x02":
            text = "AppImage (type 2) — " + text
        return text
    if head[:2] == b"MZ" and len(head) >= 64:
        offset = struct.unpack("<I", head[60:64])[0]
        if offset + 6 <= len(head) and head[offset:offset+4] == b"PE\0\0":
            machine = struct.unpack("<H", head[offset+4:offset+6])[0]
            return f"Windows PE executable, {PE_MACHINES.get(machine, hex(machine))}"
        return "DOS/Windows executable"
    if head[:2] == b"#!":
        return "Script for " + head[2:].split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    return ""


def permissions(info):
    mode = stat.filemode(info.st_mode)
    try:
        owner = pwd.getpwuid(info.st_uid).pw_name
    except KeyError:
        owner = str(info.st_uid)
    try:
        group = grp.getgrgid(info.st_gid).gr_name
    except KeyError:
        group = str(info.st_gid)
    return mode, f"{owner} : {group}"


class FolderSignals(QObject):
    done = pyqtSignal(int, object)


class FolderScan(QRunnable):
    """Recursive size/count of a folder; never follows symlinks, bounded in time and entries."""
    def __init__(self, generation, path):
        super().__init__()
        self.generation, self.path = generation, path
        self.cancelled = threading.Event()
        self.signals = FolderSignals()

    def run(self):
        files = folders = size = 0
        complete = True
        deadline = time.monotonic() + FOLDER_SCAN_SECONDS
        pending = [self.path]
        while pending:
            if self.cancelled.is_set():
                return
            if files + folders > FOLDER_SCAN_LIMIT or time.monotonic() > deadline:
                complete = False
                break
            try:
                with os.scandir(pending.pop()) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                folders += 1
                                pending.append(entry.path)
                            else:
                                files += 1
                                size += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
            except OSError:
                pass
        self.signals.done.emit(self.generation, {"files": files, "folders": folders,
                                                 "size": size, "complete": complete})
