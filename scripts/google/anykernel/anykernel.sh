# SPDX-License-Identifier: GPL-2.0-only
# AnyKernel3 installation script: integrated Pixel 10 Pro / Pro XL 6.12.
properties() { '
kernel.string=Stock bring-up 6.12 for Pixel 10 Pro / Pro XL (blazer/mustang)
do.devicecheck=1
do.modules=0
do.systemless=1
do.cleanup=1
do.cleanuponabort=0
device.name1=blazer
device.name2=mustang
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; }

BLOCK=boot
IS_SLOT_DEVICE=1
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto
. tools/ak3-core.sh

# In-app installers must be running the beta's 6.12 stack, not the old 6.6 OS.
case "$(uname -r)" in
  6.12.*) ;;
  *) abort "This kernel requires the Pixel beta firmware with Linux 6.12." ;;
esac

# Preserve the matching stock boot header; first-stage ramdisk is in init_boot.
split_boot
flash_boot
