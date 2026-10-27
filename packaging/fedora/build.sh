#!/bin/bash
# Build the kdeglance RPM from the current git checkout. Run as a normal user.
set -euo pipefail
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
version=$(cat "$repo/VERSION")
rpmdev-setuptree
git -C "$repo" archive --format=tar.gz --prefix="KDEGlance-$version/" \
    -o ~/rpmbuild/SOURCES/"KDEGlance-$version.tar.gz" HEAD
rpmbuild -ba "$repo/packaging/fedora/kdeglance.spec"
ls ~/rpmbuild/RPMS/*/kdeglance-"$version"-*.rpm
