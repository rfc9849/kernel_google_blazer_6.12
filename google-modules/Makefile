# SPDX-License-Identifier: GPL-2.0

# The modules are written to be compiled externally against a kernel tree
# located at $(KERNEL_SRC) with output at $(OUT_DIR), and to find other Google
# modules via $(ROOT_DIR)/private/google-modules, which resolves through the
# `private` symlink in the root source directory.
export KERNEL_SRC := $(srctree)
export ROOT_DIR := $(srctree)
export OUT_DIR := $(abspath $(objtree))

# Kernel-internal include directories that kleaf makes available to all DDK
# modules via //common:all_headers_aarch64. These follow module-private
# headers, matching the 6.12 DDK unsafe-header include precedence.
export GOOGLE_DDK_INTERNAL_INCLUDES := \
	-I$(srctree)/drivers/dma-buf \
	-I$(srctree)/drivers/dma \
	-I$(srctree)/drivers/extcon \
	-I$(srctree)/drivers/pci/controller/dwc \
	-I$(srctree)/drivers/thermal \
	-I$(srctree)/drivers/ufs \
	-I$(srctree)/drivers/usb \
	-I$(srctree)/drivers/usb/host \
	-I$(srctree)/drivers/usb/dwc3 \
	-I$(srctree)/drivers/usb/gadget \
	-I$(srctree)/drivers/usb/gadget/function \
	-I$(srctree)/drivers/devfreq \
	-I$(srctree)/drivers/pinctrl \
	-I$(srctree)/arch/arm64/kvm/hyp/include \
	-I$(srctree)/sound/usb \
	-I$(srctree)/drivers/ufs/core \
	-I$(srctree)/drivers/ufs/host \
	-I$(srctree)/drivers/spi \
	-I$(srctree)/drivers/android \
	-I$(srctree)/kernel/sched \
	-I$(srctree)

ifdef CONFIG_SOC_LGA
# Modules built with hand-written Kbuild files (kleaf kernel_module() targets)
obj-y += wlan/bcmdhd/bcm4390/

# Modules built with Kbuild files generated from kleaf ddk_module() targets
include $(src)/Makefile.ddk
endif
