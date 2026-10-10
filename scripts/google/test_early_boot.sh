#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Exercise the integrated GCMA parameter before testing on real hardware.
# No rootfs is supplied: reaching mount_root is the expected end of this test.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=${OUT:-out}
QEMU=${QEMU:-qemu-system-aarch64}
LOG="$OUT/early-boot-regression.log"
command -v "$QEMU" >/dev/null
command -v timeout >/dev/null
set +e
timeout 90s "$QEMU" -machine virt,gic-version=3,virtualization=on \
  -cpu max -smp 2 -m 2048 -nographic -net none -no-reboot \
  -kernel "$OUT/arch/arm64/boot/Image" \
  -append 'earlycon=pl011,0x9000000 console=ttyAMA0 nokaslr panic=-1 android_arch_task_struct_size=784 samsung_dma_heap.gcma_skip_heaps=gcma_camera_internal' \
  >"$LOG" 2>&1
status=$?
set -e
if [ "$status" -ne 0 ] || \
   ! grep -q 'Kernel panic - not syncing: VFS: Unable to mount root fs' "$LOG" || \
   grep -Eq 'Oops:|BUG:|WARNING:|param_set_skip_heaps\+' "$LOG"; then
  printf 'Early boot regression FAILED (qemu status %s): %s\n' "$status" "$LOG" >&2
  exit 1
fi
printf 'Early boot regression: OK (reached root mount with the GCMA parameter).\nLog: %s\n' "$LOG"
printf 'This is not Pixel hardware boot verification.\n'
