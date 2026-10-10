#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Sanity checks for the selected stock blazer DDK graph (no generated writes)."""
import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
import warnings

SPEC = importlib.util.spec_from_file_location('ddk2kbuild',
                                             Path(__file__).with_name('ddk2kbuild.py'))
ddk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ddk)


class BlazerGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = ddk.Workspace()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), warnings.catch_warnings():
            # Starlark strings use escapes Python warns about; they are data,
            # not unknown BUILD rules or incomplete module graph diagnostics.
            warnings.simplefilter('ignore', DeprecationWarning)
            warnings.simplefilter('ignore', SyntaxWarning)
            cls.ws.scan(['google-modules', 'google-devices'])
            cls.mods, cls.legacy, _ = cls.ws.closure([
                'google-devices/muzel:muzel', 'google-devices/lga:lga_base'])
        cls.errors = errors.getvalue()

    def test_graph_evaluates_without_unknown_targets(self):
        self.assertEqual(self.errors, '')
        self.assertGreater(len(self.mods), 250)

    def test_core_blazer_drivers_are_selected(self):
        outputs = {target.attrs['out'] for target in self.mods.values()}
        for name in ('pvrsrvkm.ko', 'arm_smmu_v3_kvm.ko', 'bcmdhd4390.ko',
                     'syna_touch.ko', 'aoc_core.ko', 'vh_sched.ko', 'pixel_metrics.ko'):
            with self.subTest(module=name):
                self.assertIn(name, outputs)
        self.assertNotIn('bcmdhd4383.ko', outputs)
        self.assertNotIn('focal_touch.ko', outputs)

    def test_build_settings_match_stock_laguna(self):
        self.assertTrue(self.ws.condition('//private/devices/google/common:soc_is_laguna', ''))
        self.assertTrue(self.ws.condition(':lga_production', 'google-modules/powervr'))
        self.assertFalse(self.ws.condition(':mbu_production', 'google-modules/powervr'))
        self.assertEqual(self.ws.flag_value('google-devices/common:soc'), 'laguna')

    def test_transitive_header_kconfigs_are_preserved(self):
        kc, dc = self.ws.configuration_inputs(
            'google-modules/perf/core/google_pm_qos:google_pm_qos_real', set())
        self.assertIn('google-modules/perf/core/google_pm_qos/google_pm_qos_Kconfig', kc)
        self.assertIn('google-modules/perf/core/google_pm_qos/google_pm_qos_enabled_defconfig', dc)

    def test_stock_zram_config_target_is_preserved(self):
        kc, dc = self.ws.configuration_inputs(
            'google-modules/soc/gs/drivers/block/zram:zcomp_cpu', set())
        self.assertIn('google-modules/soc/gs/drivers/block/zram/Kconfig', kc)
        self.assertIn('google-modules/soc/gs/drivers/block/zram/defconfig', dc)

    def test_selected_source_files_exist(self):
        for target in self.mods.values():
            sources = self.ws.files(self.ws.attr(target, 'srcs', []), target.pkg)
            for branches in self.ws.attr(target, 'conditional_srcs', {}).values():
                for files in branches.values():
                    sources.extend(self.ws.files(files, target.pkg))
            for source in sources:
                if source.endswith(('.c', '.S')):
                    with self.subTest(target=target.label, source=source):
                        self.assertTrue((Path(ddk.TREE) / source).is_file())


if __name__ == '__main__':
    unittest.main()
