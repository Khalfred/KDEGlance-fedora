# KDEGlance 1.0.1 — Fedora KDE package

Unofficial Fedora KDE port of KDEGlance, packaged after upstream's Arch package
(packaging/aur). Not affiliated with or endorsed by the upstream author; report
problems with this port here, not upstream.

## Build and install

```bash
sudo dnf install rpm-build rpmdevtools gcc-c++ qt6-qtbase-devel \
    kf6-kwindowsystem-devel desktop-file-utils python3
bash packaging/fedora/build.sh   # lists the built RPMs; the highest release is the new one
sudo dnf install ~/rpmbuild/RPMS/x86_64/kdeglance-<version>-<release>.x86_64.rpm
systemctl --user restart kdeglance2.service   # when upgrading
```

Install the exact new file: older builds stay in `~/rpmbuild/RPMS`, and a `*`
pattern would match them too. On Fedora 44 the RPM can instead be downloaded from
the [latest release](https://github.com/Khalfred/KDEGlance-fedora/releases/latest).

dnf pulls in the runtime dependencies (PyQt6, Qt Multimedia, KIO Fuse, ...).
Installing the package does not touch HOME, keyboard shortcuts or running services.

## First launch and Dolphin setup (as your normal user, not sudo)

```bash
kdeglance-setup --check
systemctl --user daemon-reload
busctl --user call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig
kdeglance-setup --enable-dolphin
kbuildsycoca6 --noincremental
```

`--enable-dolphin` backs up and writes only `~/.local/share/applications/org.kde.dolphin.desktop`
to turn on Qt accessibility (needed for selection/order sync). Fully quit Dolphin
and reopen it. If two Dolphin windows show the same folder with the same file
selected, arrow keys still follow the folder's order, but Dolphin's selection is
not moved, since the window the preview came from cannot be told apart.

Then in Dolphin: **Settings → Configure Keyboard Shortcuts → KDEGlance: Quick Look**
and assign **Space** (review any conflict yourself). D-Bus starts
`kdeglance2.service` on demand.

```bash
kdeglance --version
kdeglance state
systemctl --user status kdeglance2.service
journalctl --user -u kdeglance2.service -b --no-pager -n 50
```

## What this port adds

- Previews for PDF, text/code, Markdown, office documents (DOCX, ODT, XLSX,
  PPTX, … converted to PDF with LibreOffice and cached in ~/.cache/kdeglance2),
  ZIP/tar/7z archive listings. PDFs and office documents open in a taller
  window (90% of screen height) showing one whole page with a page-thumbnail
  sidebar: Up/Down, PageUp/PageDown and the wheel turn pages, Home/End jump
  to the first/last page, and pressing Up/Down past the first/last page moves
  to the previous/next file. Left/Right always move to the previous/next file,
  in every preview. In text and code Up/Down scroll three lines; when
  the text fits without scrolling, and in the information panel, they move to
  the previous/next file. Folders, executables (ELF/AppImage/Windows PE/scripts), launchers and
  any other file show a thumbnail (from Dolphin's cache, else the file icon) and
  properties: type, size, folder contents, location, dates, permissions, owner.
  The Dolphin action is offered for every file and folder.
- More images (AVIF, JXL, TIFF, SVG, PSD, EXR, QOI, camera RAW …) and audio
  (Opus, AIFF, WMA, APE, WavPack, MKA, M4B …).
- Text/Markdown/JSON/code use the same tall window as PDFs. Other previews use
  a fixed window based on half of Dolphin's saved (unmaximized) window size
  (images and video 1.25× that), so KWin keeps it centered. Image windows shrink
  to the image's shape (read from the file header), so there are no black bars;
  HEIC and camera RAW keep the fixed size. Videos are fitted the same way using
  ffprobe (phone rotation and pixel aspect included), and vertical videos get a
  15% larger window. Zoom stays inside the window. Change the ratio in `~/.config/kdeglance2/window.ini`:

  ```ini
  [window]
  scale=0.7
  ```

## Code colors

Code, JSON and other source files are highlighted with line numbers by
KSyntaxHighlighting, the engine Kate/KWrite/KDevelop use. The theme follows the
file's default editor: Kate/KWrite → Kate's configured color theme (exactly
what Kate shows), VS Code/VSCodium → VSCodium Dark, anything else → Breeze
Dark/Light to match the desktop. Pick any theme from
`ksyntaxhighlighter6 --list-themes` instead with:

```ini
# ~/.config/kdeglance2/window.ini
[code]
theme=Tokyo Night
```

## Codecs

Fedora's stock FFmpeg is codec-limited (no H.264/HEVC). For full video playback,
enable RPM Fusion and swap to the full FFmpeg:

```bash
sudo dnf swap ffmpeg-free ffmpeg --allowerasing
```

## Migrating from a manual install.sh install

Package launches refuse to run while a manual per-user install shadows them.
Remove it first with its own manager, keeping preferences:

```bash
~/.local/bin/kdeglance-manage uninstall
hash -r
kdeglance-setup --check
```

## Remove

```bash
kdeglance-setup --restore-dolphin
systemctl --user disable --now kdeglance2.service
sudo dnf remove kdeglance
systemctl --user daemon-reload
kbuildsycoca6 --noincremental
```

Preferences (`~/.config/kdeglance2`) and logs are kept.
