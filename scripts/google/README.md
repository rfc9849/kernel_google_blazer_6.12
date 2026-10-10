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
management, thermal drivers, Binder, and memory management. There is no KernelSU
or other root implementation, CASS, SBalance, Simple LMK, or performance tuning.

`CONFIG_INTEGRATE_MODULES=y` compiles selected modules into `vmlinux` while
retaining their module names and delayed initialization. When Android loads its
stock `.ko`, the kernel initializes the corresponding integrated driver instead
of loading the stock machine code. Pixel's SMMUv3 EL2 driver is built directly
into the nVHE hypervisor. Rust Binder has the same delayed-initialization
support as integrated C modules.

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

`OUT` and `JOBS` are optional. The result is `out/arch/arm64/boot/Image.lz4`.
Only this repository's source is compiled. Neither Bazel nor a `repo` workspace
is required.

## Regeneration and checks

```sh
python3 scripts/google/ddk2kbuild.py
python3 scripts/google/test_ddk2kbuild.py
REGENERATE_CONFIG=1 scripts/google/build.sh
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

## Boot verification

Compilation and runtime bring-up are distinct milestones. Before testing, keep
the exact beta's original `boot.img` and use its stock `vendor_kernel_boot`,
`vendor_dlkm`, `system_dlkm`, DTBO, firmware and userspace. Packing/flashing must
preserve the stock boot header and ramdisk. Do not flash generated DTBs or vendor
partitions merely because they exist in the source tree.

After a test boot, verify pKVM/SMMU initialization, early module loading, Binder,
display/touch, storage, WLAN, modem, audio, cameras, TPU/GXP, and thermal HAL.
A successful compile is not evidence that the device has booted successfully.
