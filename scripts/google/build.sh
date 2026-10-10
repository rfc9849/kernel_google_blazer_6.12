#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Plain-make build of the integrated Pixel 10 Pro 6.12 kernel with SukiSU-Ultra.
set -euo pipefail
cd "$(dirname "$0")/../.."
SRC=$PWD
OUT=${OUT:-out}
JOBS=${JOBS:-$(nproc)}
PREBUILTS=${PREBUILTS:-$SRC/../kernel_pixel_6.12_stock/prebuilts}
LLVM_DIR=${LLVM_DIR:-$PREBUILTS/clang/host/linux-x86/clang-r536225/bin}
RUST_DIR=${RUST_DIR:-$PREBUILTS/rust/linux-x86/1.82.0.p2/bin}
BINDGEN=${BINDGEN:-$PREBUILTS/clang-tools/linux-x86/bin/bindgen}
export PATH="$LLVM_DIR:$RUST_DIR:$PATH"
export LIBCLANG_PATH=${LIBCLANG_PATH:-$(dirname "$LLVM_DIR")/lib}
for tool in clang ld.lld rustc; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
[ -x "$BINDGEN" ] || { echo "Set BINDGEN to the bindgen executable" >&2; exit 1; }
PAHOLE=${PAHOLE:-$HOME/toolchains/pahole-1.27/bin/pahole}
if [ ! -x "$PAHOLE" ]; then
  PAHOLE=$(command -v pahole || true)
fi
[ -n "$PAHOLE" ] || { echo 'Install pahole >= 1.26 or set PAHOLE' >&2; exit 1; }
PAHOLE_VERSION=$($PAHOLE --version | tr -d 'v.')
if [ "$PAHOLE_VERSION" -lt 126 ]; then
  echo 'pahole >= 1.26 is required: 1.25 has a 4096 per-CPU variable limit' >&2
  exit 1
fi
# Use the same pinned submodule/versioning as the 6.6 tree. Never follow the
# moving upstream branch or query GitHub for version metadata during Kbuild.
git submodule sync -q KernelSU
git submodule update -q --init --checkout KernelSU
KSU_TAG=$(git -C KernelSU describe --tags --abbrev=0)
KSU_VER_ARGS=(
  # Linux 6.12 prefixes src with srctree; avoid a second relative prefix in KSU.
  "KSU_KERNEL_DIR=$SRC/KernelSU/kernel"
  "CURL_BIN=true"
  "KSU_GITHUB_VER=${KSU_TAG#v}"
  "GITHUB_COMMITS=$(git -C KernelSU rev-list --count HEAD)"
)
# Stock Kleaf builds pass the ACK AutoFDO profile (collected on Pixel 10);
# plain make needs it explicitly. AUTOFDO=0 builds without it for A/B tests.
AFDO_ARGS=()
if [ "${AUTOFDO:-1}" = 1 ]; then
  AFDO_PROFILE=$SRC/gki/aarch64/afdo/kernel.afdo
  [ -f "$AFDO_PROFILE" ] || { echo "Missing $AFDO_PROFILE" >&2; exit 1; }
  AFDO_ARGS=("CLANG_AUTOFDO_PROFILE=$AFDO_PROFILE")
fi
MAKE=(make O="$OUT" ARCH=arm64 LLVM=1 LLVM_IAS=1 BINDGEN="$BINDGEN" PAHOLE="$PAHOLE" -j"$JOBS" "${KSU_VER_ARGS[@]}" "${AFDO_ARGS[@]}")
if [ "${REGENERATE_CONFIG:-0}" = 1 ]; then
  mkdir -p "$OUT"
  scripts/kconfig/merge_config.sh -m -O "$OUT" \
    arch/arm64/configs/gki_defconfig \
    google-devices/lga/lga_defconfig \
    google-devices/muzel/muzel_defconfig \
    google-modules/ddk.config scripts/google/lga.fragment
  "${MAKE[@]}" olddefconfig
  "${MAKE[@]}" savedefconfig
  cp "$OUT/defconfig" arch/arm64/configs/lga_defconfig
else
  "${MAKE[@]}" lga_defconfig
fi
"${MAKE[@]}" Image.lz4
printf 'Built %s/%s/arch/arm64/boot/Image.lz4\n' "$SRC" "$OUT"
