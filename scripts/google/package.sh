#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Package a completed build; never flashes a device or modifies the 6.6 tree.
set -euo pipefail
cd "$(dirname "$0")/../.."
SRC=$PWD
OUT=${OUT:-out}
OUT=$(realpath "$OUT")
AK3_REV=020dfeccf9d7e962a48400fc94d3e451df92eead
AK3_SOURCE=${AK3_SOURCE:-https://github.com/osm0sis/AnyKernel3.git}
MAGISK_VER=v31.0
MAGISK_SHA256=2c8a488b9a5293e578e95ae4f07e3c57aba4feec4a52ca4dd852a2692d6dd4e8
MAGISK_APK=${MAGISK_APK:-$OUT/Magisk-$MAGISK_VER.apk}
[ -s "$OUT/arch/arm64/boot/Image.lz4" ] || { echo 'Build Image.lz4 first' >&2; exit 1; }
CACHE="$OUT/anykernel.git"
if [ ! -d "$CACHE" ]; then
  git init -q --bare "$CACHE"
fi
if ! git --git-dir="$CACHE" cat-file -e "$AK3_REV^{commit}" 2>/dev/null; then
  git --git-dir="$CACHE" fetch -q "$AK3_SOURCE" "$AK3_REV"
fi
if ! echo "$MAGISK_SHA256  $MAGISK_APK" | sha256sum -c --status 2>/dev/null; then
  if [ "$MAGISK_APK" != "$OUT/Magisk-$MAGISK_VER.apk" ]; then
    echo 'Provided Magisk APK fails the pinned checksum' >&2
    exit 1
  fi
  curl -fsSL -o "$MAGISK_APK" \
    "https://github.com/topjohnwu/Magisk/releases/download/$MAGISK_VER/Magisk-$MAGISK_VER.apk"
fi
echo "$MAGISK_SHA256  $MAGISK_APK" | sha256sum -c --quiet
STAGING=$(mktemp -d "$OUT/ak3.XXXXXX")
trap 'rm -rf -- "$STAGING"' EXIT
git --git-dir="$CACHE" archive "$AK3_REV" | tar -xf - -C "$STAGING"
cp scripts/google/anykernel/anykernel.sh "$STAGING/anykernel.sh"
cp "$OUT/arch/arm64/boot/Image.lz4" "$STAGING/Image.lz4"
# Tensor G5 cannot execute AnyKernel3's AArch32 tools. Use pinned arm64 tools.
for tool in busybox magiskboot magiskpolicy; do
  unzip -p "$MAGISK_APK" "lib/arm64-v8a/lib$tool.so" > "$STAGING/tools/$tool"
  chmod 755 "$STAGING/tools/$tool"
done
rm -f "$STAGING"/tools/{fec,httools_static,lptools_static,snapshotupdater_static}
KVER=$(<"$OUT/include/config/kernel.release")
HEAD=$(git rev-parse --short=12 HEAD)
ZIP="$OUT/kernel_google_blazer_6.12-$KVER-$HEAD-$(date +%Y%m%d-%H%M%S).zip"
(cd "$STAGING" && zip -qr9 "$ZIP" . -x '.git*' 'README.md' '*placeholder')
unzip -tq "$ZIP"
sha256sum "$ZIP"
echo "Created $ZIP"
