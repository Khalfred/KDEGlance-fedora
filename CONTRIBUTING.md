# Contributing

This is the unofficial Fedora KDE port of KDEGlance. Report problems and send
changes here, not to the upstream project.

## Environment

Use a current Fedora KDE (or Fedora-based, e.g. Ultramarine) Plasma 6 Wayland
session. Read [packaging/fedora/FEDORA-INSTALL.md](packaging/fedora/FEDORA-INSTALL.md)
first. Build dependencies:

```bash
sudo dnf install rpm-build rpmdevtools gcc-c++ qt6-qtbase-devel \
    kf6-kwindowsystem-devel desktop-file-utils python3
```

Changes are GPL-3.0-or-later unless an existing third-party file carries its own
compatible license; retain all third-party notices.

## Testing a change without reinstalling

Stop the packaged service and run the checkout's daemon in its place. The
installed `kdeglance` command and Dolphin's Space action then talk to your copy:

```bash
cd kdeglance
g++ -O2 -std=c++20 -fPIC -shared native.cpp -o libkdeglance_native.so \
    $(pkg-config --cflags --libs 'Qt6Gui >= 6.8' 'KF6WindowSystem >= 6.0')
systemctl --user stop kdeglance2.service
systemd-run --user --unit=kdeglance-dev -E QT_QPA_PLATFORM=wayland \
    -E WAYLAND_DISPLAY="$WAYLAND_DISPLAY" -E XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
    /usr/bin/python3 -B "$PWD/daemon.py"
kdeglance open -- /path/to/file && kdeglance state
journalctl --user -u kdeglance-dev -f            # logs
systemctl --user stop kdeglance-dev               # when done; restart with:
systemctl --user reset-failed kdeglance-dev; systemctl --user start kdeglance2.service
```

Changes to the Dolphin action (`packaging/aur/kdeglance-space-probe.desktop`)
only take effect from the installed package, followed by
`kbuildsycoca6 --noincremental` and a full Dolphin restart.

## Building the package

```bash
bash packaging/fedora/build.sh
sudo dnf install ~/rpmbuild/RPMS/x86_64/kdeglance-1.0.1-*.x86_64.rpm
systemctl --user restart kdeglance2.service
```

Bump `Release:` and add a `%changelog` entry in `packaging/fedora/kdeglance.spec`
for every package you hand out. New Python modules must be added to the
`%install` module list, or they are silently left out of the RPM.

## Code guidelines

Keep decoding and media access off the GUI thread. Preserve cancellation and
request-generation checks. Every preview window is sized before it is shown
(`initial_size`), because KWin centers a window only when it first appears;
do not resize a visible window. Existing D-Bus, desktop-action and service
identities need a migration plan if changed: users may have saved Space bindings.
User-visible messages are in English.

Report native Wayland/Dolphin/manual checks separately from offscreen tests.
The upstream test suite (TESTING.md) targets Arch/CachyOS and has not been
adapted to or run on Fedora; do not claim it passes here without a real run.

Use original or explicitly licensed fixtures. Never commit personal media,
credentials, logs, absolute developer-home paths, generated .so files, or .work/.
Include build/OS versions in bug reports, but remove private paths/server names.
No public CI badge or clean-machine compatibility claim should be added without
an actual corresponding run.
