# Pixel 10 Pro / Pro XL: integrated 6.12 bring-up

This is a standalone, plain-`make` kernel tree for Pixel 10 Pro (`blazer`)
and Pro XL (`mustang`), Tensor G5 (`laguna/lga`). It follows the layout and
integrated-module bring-up of `kernel_google_blazer` 6.6, but imports the new
Google drivers instead of porting old 6.6 drivers forward.

## Provenance

- ACK base: `4a1a020d156e5b64d2fca8d2b7d413cae55f51ec`, Linux 6.12.81,
  `android16-6.12`, KMI generation 6 (the `base` branch).
- Vendor/device sources: GrapheneOS's unmodified Google source mirror,
  `kernel_pixel_6.12`, branch `17-qpr2-base`, revision
  `8cd9a3d027dd6b0b93f32c31ae27e37a3e0cf543`.
- Release label: `CP41.260831.007.A3-CP41.260831.011`, build `16396410`,
  `muzel` / `rango`; this tree targets the `muzel` / laguna family.
- Every GKI source blob was compared with the recorded ACK revision before
  importing. The Google tarball drops `.gitignore` / `.gitattributes` files
  and executable bits on seven selftest scripts; ACK retains these metadata.
- Google device trees live in `google-devices/`, drivers in `google-modules/`.
  Imports and subsequent bring-up adaptations are separate signed-off commits.

## Scope

The configuration keeps Google's scheduler and vendor scheduler hooks, power
management, thermal drivers, Binder, and memory management. SukiSU-Ultra is
built in, matching the pinned integration in our 6.6 tree. There is no CASS,
SBalance, Simple LMK, SUSFS, KPM, or additional performance tuning.

SukiSU-Ultra lives in the `KernelSU/` submodule at
`223897c72cc5c23b6fea84d6542aa8ef24459998` (v4.2.0-72), with
`drivers/kernelsu` pointing to its kernel sources. It uses the upstream
kprobe/tracepoint hooks with `CONFIG_KSU=y` and manual-su support; manager
signature verification and per-app authorization remain enabled. No 6.6
kprobe backports are needed: 6.12 already supports kprobes without loadable
modules. No framework or vendor partitions are replaced.

`CONFIG_INTEGRATE_MODULES=y` compiles selected modules into `vmlinux` while
retaining their module names and delayed initialization. When Android loads its
stock `.ko`, the kernel initializes the corresponding integrated driver instead
of loading the stock machine code. Pixel's SMMUv3 EL2 driver is built directly
into the nVHE hypervisor. Rust Binder has the same delayed-initialization
support as integrated C modules. Both Binder implementations and `binder.impl`
are retained. Rust uses the stock `binder` tracefs namespace; the C fallback's
tracepoints are namespaced as `binder_c` to avoid collisions in a single image.
Android vendor hooks are not disabled. Default command-line parameters of
integrated C modules are parsed at the first initcall level, not in
`start_kernel()` before the slab allocator exists. This preserves allocating
callbacks such as `samsung_dma_heap.gcma_skip_heaps`; genuine built-in parameters
and explicit parameter levels keep their original timing.

This removes binary KMI coupling for integrated drivers, **not** the need to
match the vendor userspace, firmware, device trees, module names and module
parameters of the target Android release. Do not use this 6.12 kernel as a
replacement for the old 6.6 firmware stack.

## Build (Linux only)

Known bring-up host: `ssh aosp`, x86_64 Linux, 32 threads / 125 GiB RAM.
Source path: `/home/builder/kernel_google_blazer_6.12`.

```sh
scripts/google/build.sh
```

The script initializes/checks out the recorded SukiSU submodule revision. A
fresh checkout needs network access for this step (or use `git clone
--recurse-submodules`). Version metadata is derived from the pinned commit,
not a moving GitHub release or commit-count API, so subsequent Kbuild runs
need no network access for SukiSU. The pinned revision reports version 40971.

The script uses the release's Android Clang `r536225` (Clang 19), Android Rust
`1.82.0.p2`, and bindgen. By default it looks for toolchains in the sibling
`kernel_pixel_6.12_stock/prebuilts` checkout used to import the release. That
checkout is only a **toolchain source**, not an external kernel/driver build
dependency. Toolchains can be installed separately:

```sh
LLVM_DIR=/path/to/clang/bin \
RUST_DIR=/path/to/rust/bin \
BINDGEN=/path/to/bindgen \
LIBCLANG_PATH=/path/to/clang/lib \
scripts/google/build.sh
```

`OUT` and `JOBS` are optional. `PAHOLE` can select the BTF encoder; use >= 1.26
(the bring-up host uses 1.27). Version 1.25 has a fixed 4096 per-CPU variable
limit and cannot encode this integrated image reliably. BTF remains enabled.
The result is `out/arch/arm64/boot/Image.lz4`.
Only this repository's source is compiled. Neither Bazel nor a `repo` workspace
is required. The macOS checkout is for inspection only: a case-insensitive APFS
volume cannot represent several Linux filename pairs faithfully (for example
`xt_DSCP.c` / `xt_dscp.c`). Build and authoritative verification stay on Linux.

## Regeneration and checks

```sh
python3 scripts/google/ddk2kbuild.py
python3 scripts/google/test_ddk2kbuild.py
REGENERATE_CONFIG=1 scripts/google/build.sh
python3 scripts/google/check_image.py
# Optional Linux/QEMU regression; no Pixel devices or rootfs are emulated:
bash scripts/google/test_early_boot.sh
scripts/google/package.sh
```

The generator evaluates the `muzel` and `lga` BUILD definitions with laguna's
stock build settings. It includes boot-critical, vendor and manually loaded
blocklisted modules, excludes frankel-only touch/WLAN modules, and generates
Kbuild files plus module-local Kconfig/defconfig inputs. Broadcom 4390 retains
its handwritten build. EL2 library objects are linked by the nVHE Makefile.
`--list` does not write generated files.

`arch/arm64/configs/lga_defconfig` is generated from the new GKI, lga, muzel and
DDK fragments, followed by the minimal integration overrides in
`scripts/google/lga.fragment`.

## Packaging

`package.sh` creates an AnyKernel3 ZIP from the completed `Image.lz4`. It pins
AnyKernel3 revision `020dfeccf9d7e962a48400fc94d3e451df92eead` and the arm64
packing tools from Magisk v31.0 with a SHA-256 check. Those are installer tools;
**no Magisk payload is added to the boot ramdisk**. SukiSU root support is
compiled into the kernel itself. The installer
only targets blazer/mustang and refuses installation while running a 6.6 kernel.
It does not replace vendor partitions.

On the bring-up server, avoid downloads by reusing existing read-only caches:

```sh
AK3_SOURCE=/home/builder/kernel_google_blazer/out/AnyKernel3 \
MAGISK_APK=/home/builder/kernel_google_blazer/out/Magisk-v31.0.apk \
scripts/google/package.sh
```

Neither build nor packaging scripts flash a phone.

## Boot verification

Compilation and runtime bring-up are distinct milestones. Before testing, keep
the exact beta's original `boot.img` and use its stock `vendor_kernel_boot`,
`vendor_dlkm`, `system_dlkm`, DTBO, firmware and userspace. Packing/flashing must
preserve the stock boot header and ramdisk. Do not flash generated DTBs or vendor
partitions merely because they exist in the source tree.

After a test boot, verify pKVM/SMMU initialization, early module loading, Binder,
display/touch, storage, WLAN, modem, audio, cameras, TPU/GXP, and thermal HAL.
A successful compile is not evidence that the device has booted successfully.

### Verified SukiSU bring-up: CP41.260831.016

The pinned SukiSU integration built successfully on `aosp`, passed the image
checks and QEMU early-boot regression, and completed a temporary hardware boot
on Pixel 10 Pro with `sys.boot_completed=1`. The user confirmed SukiSU works.
The tested kernel is `6.12.81-4k-g49babe9d2dda-dirty`, build #6,
2026-10-10 22:07:41 UTC; SukiSU/manager version is 40971. No partitions were
flashed. ADB shell root was not automatically granted as part of this test.

Tested compressed kernel SHA-256:
`c93988e4093bf1069a6c3de1fad94a57f772415b7777aff4d9caeb0c3f4f0201`.
The temporary image is `out/boot-test-CP41.260831.016/test-boot-sukisu.img`;
the corresponding AnyKernel archive ends in `20261010-220846.zip`.
The packaged installer itself has not been flash-tested.

### Verified pre-SukiSU bring-up: CP41.260831.016

This baseline predates the SukiSU integration; it is not a root-enabled build.
On 2026-10-10 UTC (2026-10-11 local), Pixel 10 Pro completed Android boot via
`fastboot boot` with `6.12.81-4k-gad6707edd425-dirty`, build #5. The device
reported `sys.boot_completed=1`; it did not fall back to the stock kernel.
No partitions were flashed. An ordinary reboot returns to the installed stock
boot image.

Two integration defects were fixed:

- GCMA's allocating parameter callback ran before slab initialization. The
  pre-fix Image reproduces the panic in QEMU with the stock `gcma_skip_heaps`
  argument; the fixed Image reaches root mounting. See `test_early_boot.sh`.
- Preprocessor renaming changed the public `google_8250.nr_uarts` parameter.
  Parameter-backed UART globals now use assembler symbol names instead, keeping
  the stock parameter keys. The final device log registers `ttyS2` successfully.

The final bugreport confirms protected hVHE/pKVM, SMMU and Rust Binder startup
without panic/Oops/BUG. Display/GPU, touchscreen registration, thermal HAL and
camera enumeration were checked. This is a boot/smoke-test milestone, not a
claim of full camera, audio, cellular, Wi-Fi or suspend validation. The
`device_link_del` warnings, GEM probe error and UART DMA fallback also occur in
the captured stock-beta log; the stock log additionally has a scheduler deadline
warning. They are not being hidden or patched as part of these integration fixes.

Tested compressed kernel SHA-256:
`7b5212c37b752af429b19e067cbecbceeaee296868bafd167d46969c2f94597a`.
The matching temporary boot image is
`out/boot-test-CP41.260831.016/test-boot-param-uart-fix.img`; the final AnyKernel
archive ends in `20261010-211133.zip`. The successful final bugreport ends in
`2026-10-10-21-12-07.zip` under that boot-test directory's `bugreports/`.
