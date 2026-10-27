# Fedora KDE package for the unofficial KDEGlance Fedora port, adapted from
# upstream's packaging/aur/PKGBUILD. The launchers, units and helpers under
# packaging/aur are reused; only the documentation pointer is retargeted in %%prep.
# Build with packaging/fedora/build.sh (source tarball comes from git archive).
# Paths stay under /usr/lib/kdeglance because the shipped launchers, D-Bus and
# systemd files hard-code them.

Name:           kdeglance
Version:        1.0.1
Release:        7%{?dist}
Summary:        Quick Look-style file preview for KDE Plasma and Dolphin
License:        GPL-3.0-or-later
URL:            https://github.com/AlexGraveler/KDEGlance
# Upstream: https://github.com/AlexGraveler/KDEGlance (GPL-3.0-or-later).
Source0:        KDEGlance-%{version}.tar.gz

ExclusiveArch:  x86_64 aarch64

BuildRequires:  gcc-c++
BuildRequires:  pkgconfig(Qt6Gui) >= 6.8
BuildRequires:  pkgconfig(KF6WindowSystem) >= 6.0
BuildRequires:  python3
BuildRequires:  desktop-file-utils

Requires:       python3 >= 3.10
Requires:       python3-pyqt6 >= 6.8
Requires:       qt6-qtpdf >= 6.8
Requires:       python3-gobject
Requires:       python3-mutagen
Requires:       qt6-qtbase >= 6.8
Requires:       qt6-qtmultimedia >= 6.8
Requires:       qt6-qtwayland >= 6.8
Requires:       qt6-qtimageformats
Requires:       qt6-qtsvg
Requires:       kf6-kimageformats
Requires:       kf6-kwindowsystem
Requires:       kf6-kservice
Requires:       dolphin >= 24.02
Requires:       kio-fuse
Requires:       kio-extras
Requires:       at-spi2-core
Requires:       glib2
Requires:       dbus
Requires:       systemd
Requires:       plasma-workspace >= 6
# Office documents are converted to PDF; without it only their text is shown.
Recommends:     libreoffice-core
Recommends:     libreoffice-writer
# Code previews use Kate's highlighting engine; plain text without it.
Recommends:     kf6-syntax-highlighting
# 7z/RAR archive listings; ZIP and tar work without it.
Recommends:     7zip

# Private Python modules are not site-packages; keep rpm's generators quiet.
%global __requires_exclude_from ^%{_prefix}/lib/kdeglance/.*\\.py$

%description
KDEGlance opens a borderless preview of the file selected in Dolphin: images
(including animated GIF, HEIC, AVIF, JXL and camera RAW), audio with embedded
covers, video, PDF, text/Markdown, office documents and archive listings, with
an information card for any other file,
with zoom, rotation, seeking and mixed-folder navigation kept in sync with
Dolphin's selection. Installation does not assign shortcuts, start services or
modify user files; per-user Dolphin setup is explicit via kdeglance-setup.

%prep
%autosetup -n KDEGlance-%{version}
sed -i 's|/usr/share/doc/kdeglance/AUR-INSTALL.md|%{_docdir}/%{name}/FEDORA-INSTALL.md|' \
    packaging/aur/package_support.py
cp -p packaging/fedora/FEDORA-INSTALL.md .

%build
cd kdeglance
# Honor Fedora hardening/optimization/link flags; no prebuilt developer .so.
%{__cxx} %{build_cxxflags} -std=c++20 -fPIC -shared native.cpp \
    %{build_ldflags} -o libkdeglance_native.so \
    $(pkg-config --cflags --libs 'Qt6Gui >= 6.8' 'KF6WindowSystem >= 6.0')

%install
pkglib=%{buildroot}%{_prefix}/lib/kdeglance
for module in core loader window daemon client audio audio_metadata dolphin_order \
    dolphin_order_worker video interactions remote animation visuals legacy document fileinfo highlight; do
  install -Dpm644 kdeglance/$module.py $pkglib/$module.py
done
install -Dpm755 kdeglance/libkdeglance_native.so $pkglib/libkdeglance_native.so
for module in package_launch package_support user_setup; do
  install -Dpm644 packaging/aur/$module.py $pkglib/$module.py
done
install -Dpm755 packaging/aur/kdeglance %{buildroot}%{_bindir}/kdeglance
ln -s kdeglance %{buildroot}%{_bindir}/kdeglance2
install -Dpm755 packaging/aur/kdeglance-setup %{buildroot}%{_bindir}/kdeglance-setup
install -Dpm644 packaging/aur/kdeglance2.service %{buildroot}%{_userunitdir}/kdeglance2.service
install -Dpm644 packaging/aur/io.github.KDEGlance2.service \
    %{buildroot}%{_datadir}/dbus-1/services/io.github.KDEGlance2.service
install -Dpm644 packaging/aur/io.github.KDEGlance2.desktop \
    %{buildroot}%{_datadir}/applications/io.github.KDEGlance2.desktop
install -Dpm644 packaging/aur/kdeglance-space-probe.desktop \
    %{buildroot}%{_datadir}/kio/servicemenus/kdeglance-space-probe.desktop

%check
# Upstream's check expects <root>/KDEGlance-<ver> beside the helper templates.
ln -sfn ../.. packaging/aur/KDEGlance-%{version}
%{python3} -B packaging/aur/check_package.py packaging/aur
rm packaging/aur/KDEGlance-%{version}
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.KDEGlance2.desktop
sh -n %{buildroot}%{_bindir}/kdeglance %{buildroot}%{_bindir}/kdeglance-setup
grep -q '%{_docdir}/%{name}/FEDORA-INSTALL.md' %{buildroot}%{_prefix}/lib/kdeglance/package_support.py

%files
%license LICENSE packaging/aur/NOTICES.md
%doc FEDORA-INSTALL.md
%{_bindir}/kdeglance
%{_bindir}/kdeglance2
%{_bindir}/kdeglance-setup
%{_prefix}/lib/kdeglance/
%{_userunitdir}/kdeglance2.service
%{_datadir}/dbus-1/services/io.github.KDEGlance2.service
%{_datadir}/applications/io.github.KDEGlance2.desktop
%{_datadir}/kio/servicemenus/kdeglance-space-probe.desktop

%changelog
* Tue Oct 27 2026 Khalfred <238867466+Khalfred@users.noreply.github.com> - 1.0.1-7
- Syntax-highlighted code previews with line numbers (KSyntaxHighlighting),
  using Kate's theme when Kate/KWrite is the file's default editor

* Tue Oct 27 2026 Khalfred <238867466+Khalfred@users.noreply.github.com> - 1.0.1-6
- Build from the fedora branch via git archive instead of a patch (no functional change)

* Tue Oct 27 2026 Khalfred <238867466+Khalfred@users.noreply.github.com> - 1.0.1-5
- Text, Markdown, JSON and code previews use the tall page-shaped window
- Image and video windows are 25% larger (audio and info panels unchanged)

* Tue Oct 27 2026 Khalfred <238867466+Khalfred@users.noreply.github.com> - 1.0.1-4
- Paged documents show one whole page; arrows/PageUp/PageDown/wheel turn pages,
  Home/End jump, and past the first/last page the arrows change file
- Paged documents get a taller window (90% of screen height) sized to the page

* Tue Oct 27 2026 Khalfred <238867466+Khalfred@users.noreply.github.com> - 1.0.1-3
- Information panel with thumbnail and properties for folders, executables,
  launchers and other files (folder size/counts computed in the background)
- PDF and office previews show a page-thumbnail sidebar next to the pages

* Tue Oct 27 2026 Khalfred <238867466+Khalfred@users.noreply.github.com> - 1.0.1-2
- Preview PDF, text, Markdown, office documents and archives; info card for other files
- Add AVIF/JXL/TIFF/SVG/PSD/RAW images and Opus/AIFF/WMA/APE/WavPack audio
- Fixed preview size: half of Dolphin's saved window size (window.ini scale)
- Offer the Dolphin action for every file type

* Tue Oct 27 2026 Khalfred <238867466+Khalfred@users.noreply.github.com> - 1.0.1-1
- Port of upstream packaging/aur PKGBUILD 1.0.1-1 to Fedora KDE
