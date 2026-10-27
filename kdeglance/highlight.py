# SPDX-License-Identifier: GPL-3.0-or-later
"""Code colors from KSyntaxHighlighting, the engine behind Kate/KWrite/KDevelop."""
import configparser
import functools
import html
import os
from pathlib import Path
import re
import shutil
import subprocess

TOOL = "ksyntaxhighlighter6"
MAX_HIGHLIGHT_BYTES = 512 * 1024
KATE_APPS = ("org.kde.kate", "org.kde.kwrite", "org.kde.kdevelop")
VSCODE_APPS = ("code", "codium", "vscodium", "com.visualstudio.code")


def config_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home()/".config")


def read_key(file, group, key):
    parser = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",))
    parser.optionxform = str
    try:
        parser.read(config_dir()/file, encoding="utf-8")
        return parser.get(group, key, fallback="").strip()
    except (OSError, configparser.Error):
        return ""


def available():
    return shutil.which(TOOL) is not None


@functools.lru_cache(maxsize=1)
def themes():
    try:
        output = subprocess.run([TOOL, "--list-themes"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ()
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def default_app(mime):
    try:
        return subprocess.run(["xdg-mime", "query", "default", mime], capture_output=True,
                              text=True, timeout=2).stdout.strip().removesuffix(".desktop")
    except (OSError, subprocess.SubprocessError):
        return ""


def system_is_dark():
    rgb = read_key("kdeglobals", "Colors:Window", "BackgroundNormal").split(",")
    try:
        r, g, b = (int(part) for part in rgb[:3])
    except ValueError:
        return True
    return 0.299*r + 0.587*g + 0.114*b < 128


def choose_theme(mime):
    """Theme of the file's default editor where it can be matched, else the desktop's."""
    known = themes()
    wanted = [read_key("kdeglance2/window.ini", "code", "theme")]
    app = default_app(mime).lower()
    if app.startswith(KATE_APPS):
        # Kate/KWrite use this same engine; an empty setting means "follow the desktop".
        wanted.append(read_key("katerc", "KTextEditor Renderer", "Color Theme"))
    elif app.startswith(VSCODE_APPS):
        wanted.append("VSCodium Dark" if system_is_dark() else "GitHub Light")
    wanted.append("Breeze Dark" if system_is_dark() else "Breeze Light")
    for theme in wanted:
        if theme and (not known or theme in known):
            return theme
    return "Breeze Dark"


def with_line_numbers(document):
    """Body of the tool's HTML <pre> plus a dimmed line-number gutter, and its colors."""
    body = re.search(r'<body style="background-color:(#[0-9a-fA-F]{6});color:(#[0-9a-fA-F]{6})"><pre>\n?(.*)</pre>',
                     document, re.S)
    if not body:
        return None
    background, foreground, code = body.groups()
    lines = code.rstrip("\n").split("\n")
    dim = "#" + "".join(f"{(int(background[i:i+2], 16) + int(foreground[i:i+2], 16)) // 2:02x}" for i in (1, 3, 5))
    width = len(str(len(lines)))
    numbered = "\n".join(f'<span style="color:{dim}">{html.escape(str(n).rjust(width))}  </span>{line}'
                         for n, line in enumerate(lines, 1))
    return background, foreground, numbered
