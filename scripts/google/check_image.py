#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check compiled image structure and critical integrated-driver entrypoints.

These are build checks, not a substitute for booting the matching beta firmware.
"""
import hashlib
import os
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / os.environ.get('OUT', 'out')
config = {}
for line in (OUT / '.config').read_text().splitlines():
    if line.startswith('CONFIG_') and '=' in line:
        key, value = line.split('=', 1)
        config[key] = value
for key, value in {'CONFIG_INTEGRATE_MODULES': 'y', 'CONFIG_ARM64_4K_PAGES': 'y',
                   'CONFIG_ARM_SMMU_V3_PKVM_PIXEL': 'y', 'CONFIG_RUST': 'y',
                   'CONFIG_ANDROID_BINDER_IPC_RUST': 'm', 'CONFIG_VH_SCHED': 'm',
                   'CONFIG_ZRAM_GS': 'm', 'CONFIG_ZRAM_GS_BACKEND_LZO': 'y'}.items():
    if config.get(key) != value:
        raise SystemExit(f'{key}: expected {value}, got {config.get(key)}')
for key in ('CONFIG_MODULES', 'CONFIG_ARM_SMMU_V3_PIXEL', 'CONFIG_KSU',
            'CONFIG_SCHED_CASS', 'CONFIG_SBALANCE', 'CONFIG_ANDROID_SIMPLE_LMK'):
    if config.get(key) in ('y', 'm'):
        raise SystemExit(f'Unexpected enabled option: {key}')

image = OUT / 'arch/arm64/boot/Image'
compressed = image.with_suffix('.lz4')
header = image.open('rb')
with header:
    data = header.read(64)
if data[56:60] != b'ARM\x64':
    raise SystemExit('Invalid arm64 Image magic')
if (struct.unpack_from('<Q', data, 24)[0] >> 1) & 3 != 1:
    raise SystemExit('Image is not built for 4 KiB pages')
with (OUT / 'vmlinux').open('rb') as elf:
    data = elf.read(64)
if data[:4] != b'\x7fELF' or struct.unpack_from('<H', data, 18)[0] != 183:
    raise SystemExit('vmlinux is not an AArch64 ELF')

symbol_addresses = {line.split()[-1]: int(line.split()[0], 16)
                    for line in (OUT / 'System.map').read_text().splitlines()}
symbols = set(symbol_addresses)

# AArch64 struct kernel_param is 40 bytes; level is the signed byte at +26.
# Check the linked descriptors, not just the macro that generated them: an
# integrated allocating callback must not execute before mm_core_init(), while
# genuine built-in parameters must retain their original boot-time semantics.
expected_levels = {'samsung_dma_heap.gcma_skip_heaps': 0,
                   'loop.max_part': -1, 'arm_smmu_v3_kvm.atomic_pages': -1,
                   'google_8250.nr_uarts': 0, 'google_8250.share_irqs': 0,
                   'google_8250.skip_txen_test': 0}
seen = set()
base = symbol_addresses['_text']
with image.open('rb') as source:
    for address in range(symbol_addresses['__start___param'],
                         symbol_addresses['__stop___param'], 40):
        source.seek(address - base)
        descriptor = source.read(40)
        name_address = struct.unpack_from('<Q', descriptor)[0]
        source.seek(name_address - base)
        name = source.read(256).split(b'\0', 1)[0].decode()
        if name in expected_levels:
            level = struct.unpack_from('<b', descriptor, 26)[0]
            if level != expected_levels[name]:
                raise SystemExit(f'{name}: unexpected parameter level {level}')
            seen.add(name)
if seen != expected_levels.keys():
    raise SystemExit('Missing parameter descriptors: ' +
                     ', '.join(sorted(expected_levels.keys() - seen)))
print('Integrated and built-in parameter levels: OK')

required = {'__kvm_nvhe_smmu_ops', '__kvm_nvhe_pkvm_ptw_hvc_call', '__rust_binder_init'}
for module in ('rust_binder', 'buenos', 'gxp', 'aoc_core', 'syna_touch',
               'bcmdhd4390', 'pvrsrvkm', 'vh_sched', 'zram_gs'):
    required.update({f'__initcall__kmod_{module}__', f'__initdone__kmod_{module}__'})
missing = sorted(required - symbols)
if missing:
    raise SystemExit('Missing integrated driver / EL2 symbols: ' + ', '.join(missing))
subprocess.run(['lz4', '-t', str(compressed)], check=True)
for path in (image, compressed):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    print(f'{h.hexdigest()}  {path} ({path.stat().st_size} bytes)')
print('Image structure, stock config and critical integrated entrypoints: OK')
