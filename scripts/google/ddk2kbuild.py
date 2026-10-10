#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
Convert Google's Kleaf/DDK module definitions (BUILD.bazel) into regular
Kbuild files so that google-modules can be compiled in-tree with plain make.

Google's Pixel 10 (laguna/lga) kernel builds most vendor drivers as Bazel
ddk_module() targets that have no Kbuild/Makefile at all. This script
evaluates the Starlark BUILD files with a tiny Kleaf emulation, computes the
set of modules that the given device actually ships, and generates:

  - a Kbuild file in every package directory containing ddk_module()s,
  - google-modules/Kconfig.ddk which sources all module-local Kconfigs,
  - google-modules/ddk.config, the merged module-local defconfigs,
  - google-modules/Makefile.ddk, listing all package directories to build.

Usage: scripts/google/ddk2kbuild.py [--device muzel]
"""

import argparse
import fnmatch
import os
import sys
from types import SimpleNamespace
from pathlib import Path

TREE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Build settings normally passed through device.bazelrc for lga/muzel.
FLAG_VALUES = {
    "google-devices/common:soc": "laguna",
    "google-modules/perf/core/gs_perf_mon:enable_gs_perf_mon": "true",
    "google-modules/perf/core/lat_govs:enable_lat_govs": "true",
    "google-modules/video/cnm:google_ra": "true",
    "google-modules/amplifiers/cs40l26:version": "v14.5.0+v4.1.1",
    "google-modules/soc/gs:gs_soc_module": "google-devices/lga:gs_soc",
    "google-modules/soc/rdo:rdo_soc_module": "google-devices/lga:lga_soc",
    "google-modules/soc/rdo/pci:google-pcie":
        "google-modules/soc/rdo/pci:google-pcie-v1",
    "google-modules/radio/common/metrics_collection:metrics_collection":
        "google-modules/radio/common/metrics_collection:metrics_collection_enabled",
    "google-modules/soc/gs/drivers/soc/google/eh:ip_idle": "google_ip_idle",
    "google-modules/touch/common:touch_udfps_notification": "enabled",
}

# config_setting()s that aren't defined in any of the imported packages.
EXTERNAL_CONDITIONS = {
    "google-devices/common:soc_is_laguna_or_later": True,
    "google-devices/common:soc_is_laguna": True,
    "google-devices/common:soc_is_malibu": False,
    "google-devices/common:soc_is_zumapro": False,
    "google-devices/common:soc_is_zuma": False,
    "google-devices/common:soc_is_gs201": False,
    "google-devices/common:soc_is_gs101": False,
    "google-devices/common:soc_is_zumapro_or_before": False,
    "google-devices/common:soc_is_zuma_or_zumapro": False,
    "google-devices/common:soc_is_gs201_or_before": False,
    "google-devices/common:factory_build": False,
    "common:kernel_package_is_gki": True,
    "common:kernel_package_is_ack": False,
    "google-modules/wlan/linux:nl80211_testmode_enabled": False,
    "//conditions:default": None,
}

# Extra compiler flags for some modules, needed to integrate all modules into
# a single image without symbol name conflicts.
EXTRA_FLAGS = {
    # Edge TPU and GXP each have their own copy of GCIP with the same global
    # symbol names. Prefix the global symbols of the Edge TPU copy, and
    # disable its tracepoints which have the same names as GXP's.
    "google-modules/edgetpu/buenos/drivers/edgetpu:edgetpu.buenos": [
        "-include $(srctree)/google-modules/edgetpu/buenos/drivers/edgetpu/gcip-symbol-prefix.h",
        "-DNOTRACE",
    ],
    # DRM core has a function with the same name
    "google-modules/display/vsi-drm/verisilicon:vs_drm": [
        "-Ddrm_get_colorspace_name=vs_drm_get_colorspace_name",
    ],
}
# The charger drivers each have global debug variables with the same names
for _m in ("google-cpm", "hl7132", "ln8411", "pca9468"):
    _p = _m.replace("-", "_")
    EXTRA_FLAGS["google-modules/bms:" + _m] = [
        "-Ddebug_printk_prlog=%s_debug_printk_prlog" % _p,
        "-Ddebug_no_logbuffer=%s_debug_no_logbuffer" % _p,
    ]

# Modules shipped for muzel which aren't used by blazer/mustang (Pixel 10 Pro
# and Pro XL). They're frankel-only (Pixel 10) and conflict when integrated.
EXCLUDE = {
    "google-modules/touch/focaltech/ft3683u:focal_touch",
    "google-modules/wlan/bcmdhd/bcm4383:bcmdhd4383",
}

# Legacy Broadcom's chip configuration still comes from its handwritten Kbuild.
HANDWRITTEN = {"google-modules/wlan/bcmdhd/bcm4390"}

EXTRA_FLAGS.update({
    "google-modules/soc/rdo/drivers/pinctrl/google:pinctrl": [
        "-I$(srctree)/drivers/pinctrl",
    ],
    "google-modules/soc/gs/drivers/soc/google/vh/kernel/sched:vh_sched": [
        "-Dcpu_util_cfs=vh_cpu_util_cfs",
        "-D___update_load_avg=vh____update_load_avg",
        "-Dentity_eligible=vh_entity_eligible",
        "-Dset_cluster_enabled_cb=vh_set_cluster_enabled_cb",
    ],
    "google-modules/soc/gs/drivers/soc/google/vh/kernel/metrics:pixel_metrics": [
        "-Dvh_sched_switch_pixel_mod=vh_metrics_sched_switch_pixel_mod",
    ],
    "google-modules/soc/rdo/phy:google-usb-phy": ["-Dphy_fw_patch=usb_phy_fw_patch"],
    "google-modules/soc/rdo/drivers/tty/serial/8250:google_8250_base": [
        "-Dearly_serial_setup=google_early_serial_setup",
    ],
    "google-modules/soc/gs/drivers/soc/google/gnssif_spi:gnssif": [
        "-Dcreate_link_device=gnss_create_link_device",
    ],
})

GEN_HEADER = "# SPDX-License-Identifier: GPL-2.0\n" \
             "# Generated by scripts/google/ddk2kbuild.py from BUILD.bazel. " \
             "Do not edit.\n"


def norm(label, pkg):
    """Normalize a Bazel label to 'pkg:name' form, relative to the tree."""
    label = label.strip()
    if label.startswith("@"):
        return "external:" + label
    if label.startswith("//"):
        label = label[2:]
        if label.startswith("private/"):
            label = label[len("private/"):]
        if label.startswith("devices/google/"):
            label = "google-devices/" + label[len("devices/google/"):]
        if ":" not in label:
            label = label + ":" + label.rsplit("/", 1)[-1]
        return label
    if label.startswith(":"):
        return pkg + label
    # Plain file name relative to the package
    return pkg + ":" + label


class Target:
    def __init__(self, kind, pkg, attrs):
        self.kind = kind
        self.pkg = pkg
        self.attrs = attrs
        self.name = attrs.get("name")

    @property
    def label(self):
        return "%s:%s" % (self.pkg, self.name)


# Google 8250's core/platform copy must not bind to the generic 8250 globals.
SERIAL_PRIVATE_GLOBALS = (
    "early_serial_setup", "nr_uarts", "serial8250_isa_config", "serial8250_isa_devs",
    "serial8250_isa_init_ports", "serial8250_reg", "serial8250_register_ports",
    "share_irqs", "skip_txen_test", "univ8250_port_base_ops", "univ8250_port_ops",
)
for target in ("google_8250", "google_8250_base", "google_8250_dw"):
    EXTRA_FLAGS["google-modules/soc/rdo/drivers/tty/serial/8250:" + target] = [
        "-D%s=google_%s" % (name, name) for name in SERIAL_PRIVATE_GLOBALS
    ]


class Select:
    def __init__(self, d):
        self.d = d

    # list + select() / select() + list: keep it lazy inside a list, which
    # Workspace.resolve() flattens.
    def __radd__(self, other):
        return list(other) + [self]

    def __add__(self, other):
        return [self] + list(other)


class Workspace:
    def __init__(self):
        self.targets = {}
        self.pkgs = set()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def scan(self, roots):
        for root in roots:
            for dirpath, dirnames, filenames in os.walk(os.path.join(TREE, root)):
                dirnames[:] = sorted(d for d in dirnames if d not in ("tests", "test"))
                if "BUILD.bazel" in filenames:
                    self.pkgs.add(os.path.relpath(dirpath, TREE))
        for pkg in sorted(self.pkgs):
            self.load_pkg(pkg)

    def glob(self, pkg, include, exclude=(), allow_empty=True,
             exclude_directories=1):
        base = os.path.join(TREE, pkg)
        out = []
        for dirpath, dirnames, filenames in os.walk(base):
            rel = os.path.relpath(dirpath, base)
            # Don't descend into subpackages
            if rel != "." and os.path.exists(os.path.join(dirpath, "BUILD.bazel")):
                dirnames[:] = []
                continue
            for f in filenames:
                p = f if rel == "." else os.path.join(rel, f)
                if any(self.match(p, pat) for pat in include) and \
                   not any(self.match(p, pat) for pat in exclude):
                    out.append(p)
        return sorted(out)

    @staticmethod
    def match(path, pat):
        # Translate Bazel's ** semantics into fnmatch on path components.
        if pat.startswith("**/"):
            return fnmatch.fnmatch(path, pat[3:]) or fnmatch.fnmatch(path, pat)
        if "**" in pat:
            pre, post = pat.split("**", 1)
            return path.startswith(pre) and fnmatch.fnmatch(
                path[len(pre):], "*" + post.lstrip("/")) or \
                fnmatch.fnmatch(path, pre + post.lstrip("/"))
        if "/" not in pat and "/" in path:
            return False
        return fnmatch.fnmatch(path, pat)

    def bzl_symbols(self, pkg, label):
        lab = norm(label, pkg)
        if lab.startswith("external:") or lab.startswith("common:"):
            return None
        p, f = lab.split(":", 1)
        path = os.path.join(TREE, p, f)
        if not os.path.exists(path):
            return None
        env = self.make_env(p)
        exec(compile(Path(path).read_text(), path, "exec"), env)
        return env

    def make_env(self, pkg):
        ws = self

        def rule(kind):
            def fn(*args, **kwargs):
                if "name" in kwargs:
                    t = Target(kind, pkg, kwargs)
                    ws.targets[t.label] = t
                return None
            return fn

        env = {}

        def load(label, *syms, **aliases):
            mod = ws.bzl_symbols(pkg, label)
            for s in syms:
                if s in ("gki_module", "intree_module"):
                    env[s] = lambda path: "//common:" + path
                else:
                    env[s] = mod[s] if mod and s in mod else rule(s)
            for a, s in aliases.items():
                env[a] = mod[s] if mod and s in mod else rule(s)

        env.update({
            "native": SimpleNamespace(**{k: rule(k) for k in
                ("config_setting", "filegroup", "alias", "genrule", "cc_library")}),
            "struct": lambda **kw: SimpleNamespace(**kw),
            "load": load,
            "glob": lambda include, exclude=(), **kw: ws.glob(pkg, include, exclude),
            "select": lambda d, **kw: Select(d),
            "package": lambda **kw: None,
            "exports_files": lambda *a, **kw: None,
            "licenses": lambda *a, **kw: None,
            "package_name": lambda: pkg,
            "Label": lambda s: s,
        })
        for kind in ("ddk_module", "ddk_headers", "filegroup", "kernel_module",
                     "kernel_module_group", "ddk_uapi_headers", "alias",
                     "config_setting", "label_flag", "string_flag", "bool_flag",
                     "device_build", "ddk_library", "checkpatch", "checkpatch_strict",
                     "genrule", "ddk_config", "ddk_submodule", "cc_library"):
            env[kind] = rule(kind)
        return env

    def load_pkg(self, pkg):
        path = os.path.join(TREE, pkg, "BUILD.bazel")
        env = self.make_env(pkg)
        try:
            exec(compile(Path(path).read_text(), path, "exec"), env)
        except Exception as e:  # pragma: no cover
            print("warning: failed to evaluate %s: %s" % (path, e), file=sys.stderr)

    # ------------------------------------------------------------------
    # Evaluation helpers
    # ------------------------------------------------------------------
    def condition(self, key, pkg):
        if key == "//conditions:default":
            return None
        lab = norm(key, pkg)
        if lab in EXTERNAL_CONDITIONS:
            return EXTERNAL_CONDITIONS[lab]
        t = self.targets.get(lab)
        if t is None or t.kind != "config_setting":
            print("warning: unknown condition %s (assuming false)" % lab,
                  file=sys.stderr)
            return False
        for flag, want in t.attrs.get("flag_values", {}).items():
            flab = norm(flag, t.pkg)
            have = self.flag_value(flab)
            if str(have).lower() not in (str(want).lower(),
                                         {"1": "true", "0": "false"}.get(str(want), str(want))):
                return False
        return True

    def flag_value(self, flab):
        if flab in FLAG_VALUES:
            return FLAG_VALUES[flab]
        f = self.targets.get(flab)
        if f is None:
            return None
        v = f.attrs.get("build_setting_default")
        if isinstance(v, bool):
            return "true" if v else "false"
        return v

    def resolve(self, value, pkg):
        """Resolve select()s inside lists (lists may be concatenations)."""
        if isinstance(value, Select):
            default = None
            for k, v in value.d.items():
                c = self.condition(k, pkg)
                if c is None:
                    default = v
                elif c:
                    return self.resolve(v, pkg)
            return self.resolve(default, pkg) if default is not None else []
        if isinstance(value, list):
            out = []
            for v in value:
                r = self.resolve(v, pkg)
                if isinstance(r, list):
                    out.extend(r)
                else:
                    out.append(r)
            return out
        if isinstance(value, dict):
            return {k: self.resolve(v, pkg) for k, v in value.items()}
        return value

    def attr(self, t, name, default=None):
        v = t.attrs.get(name, default)
        return self.resolve(v, t.pkg) if v is not None else default

    def follow(self, lab):
        """Follow aliases and label_flags."""
        seen = set()
        while lab not in seen:
            seen.add(lab)
            t = self.targets.get(lab)
            if t is None:
                return lab
            if t.kind == "alias":
                lab = norm(self.attr(t, "actual"), t.pkg)
            elif t.kind == "label_flag":
                lab = FLAG_VALUES.get(lab) or norm(t.attrs["build_setting_default"], t.pkg)
            else:
                return lab
        return lab

    def files(self, labels, pkg, seen=None):
        """Expand srcs/hdrs labels into (pkg-relative-to-tree) file paths."""
        seen = seen if seen is not None else set()
        out = []
        for l in labels:
            if l is None:
                continue
            lab = self.follow(norm(l, pkg))
            if lab in seen:
                continue
            seen.add(lab)
            t = self.targets.get(lab)
            if t is not None and t.kind in ("filegroup", "ddk_headers"):
                key = "srcs" if t.kind == "filegroup" else "hdrs"
                out.extend(self.files(self.attr(t, key, []), t.pkg, seen))
                if t.kind == "ddk_headers":
                    out.extend(self.files(self.attr(t, "textual_hdrs", []), t.pkg, seen))
                continue
            if t is not None:
                continue
            p, f = lab.split(":", 1)
            if p.startswith("external:") or p == "common":
                continue
            out.append(os.path.normpath(os.path.join(p, f)))
        return out

    def exported_includes(self, lab, seen):
        """Include dirs exported by a dependency (transitively)."""
        lab = self.follow(lab)
        if lab in seen:
            return []
        seen.add(lab)
        t = self.targets.get(lab)
        if t is None:
            return []
        out = []
        if t.kind in ("ddk_headers", "ddk_module"):
            for inc in self.attr(t, "includes", []) or []:
                out.append(os.path.normpath(os.path.join(t.pkg, inc)))
            for inc in self.attr(t, "linux_includes", []) or []:
                out.append(os.path.normpath(os.path.join(t.pkg, inc)))
            sub = self.attr(t, "hdrs", []) or []
            if t.kind == "ddk_module":
                sub = sub + (self.attr(t, "deps", []) or [])
            for d in sub:
                out.extend(self.exported_includes(norm(d, t.pkg), seen))
        elif t.kind == "filegroup":
            for d in self.attr(t, "srcs", []) or []:
                out.extend(self.exported_includes(norm(d, t.pkg), seen))
        elif t.kind == "kernel_module_group":
            for d in self.attr(t, "srcs", []) or []:
                out.extend(self.exported_includes(norm(d, t.pkg), seen))
        return out

    def configuration_inputs(self, lab, seen):
        """Collect Kconfig/defconfig inputs exported through DDK header deps."""
        lab = self.follow(lab)
        if lab in seen:
            return [], []
        seen.add(lab)
        t = self.targets.get(lab)
        if t is None:
            return [], []
        kc = self.files(self.attr(t, "kconfigs", []), t.pkg)
        dc = self.files(self.attr(t, "defconfigs", []), t.pkg)
        for attr, result in (("kconfig", kc), ("defconfig", dc)):
            value = self.attr(t, attr)
            if value:
                result.extend(self.files([value], t.pkg))
        deps = self.attr(t, "hdrs", []) + self.attr(t, "deps", [])
        if self.attr(t, "config"):
            deps = deps + [self.attr(t, "config")]
        for dep in deps:
            child_kc, child_dc = self.configuration_inputs(norm(dep, t.pkg), seen)
            kc.extend(child_kc)
            dc.extend(child_dc)
        return kc, dc

    # ------------------------------------------------------------------
    # Module closure
    # ------------------------------------------------------------------
    def closure(self, device_labels):
        mods = {}
        kmods = {}
        kconfigs = []
        work = []
        for dl in device_labels:
            dev = self.targets[dl]
            for attr in ("ext_modules", "vendor_ramdisk_modules", "vendor_dlkm_modules",
                         "vendor_dlkm_modules_blocklisted"):
                work.extend(norm(m, dev.pkg) for m in self.attr(dev, attr, []))
            kconfigs.extend(self.files(self.attr(dev, "kconfigs", []), dev.pkg))
            base = dev.attrs.get("base_device")
            if base:
                pass
        while work:
            lab = self.follow(work.pop())
            if lab in mods or lab in kmods or lab in EXCLUDE:
                continue
            t = self.targets.get(lab)
            if t is None:
                if not lab.startswith("common:"):
                    print("warning: unknown module %s" % lab, file=sys.stderr)
                continue
            if t.kind == "ddk_module":
                mods[lab] = t
                for d in self.attr(t, "deps", []):
                    dl = self.follow(norm(d, t.pkg))
                    dt = self.targets.get(dl)
                    if dt is not None and dt.kind in ("ddk_module", "kernel_module",
                                                      "kernel_module_group"):
                        work.append(dl)
            elif t.kind == "kernel_module":
                kmods[lab] = t
                for d in self.attr(t, "deps", []):
                    work.append(norm(d, t.pkg))
            elif t.kind == "kernel_module_group":
                for d in self.attr(t, "srcs", []):
                    work.append(norm(d, t.pkg))
        return mods, kmods, kconfigs


def objname(path):
    root, ext = os.path.splitext(path)
    return root + ".o"


def gen(ws, device_labels, write=True):
    mods, kmods, dev_kconfigs = ws.closure(device_labels)
    bypkg = {}
    for lab, t in sorted(mods.items()):
        bypkg.setdefault(t.pkg, []).append(t)

    # device_build kconfigs are only inputs for the Kconfig.ext files
    kconfigs = []
    defconfigs = []
    config_seen = set()
    for label in sorted(mods):
        kc, dc = ws.configuration_inputs(label, config_seen)
        kconfigs.extend(kc)
        defconfigs.extend(dc)
    generated = []
    for pkg, targets in sorted(bypkg.items()):
        if pkg in HANDWRITTEN:
            # A hand-written Kbuild (or a Makefile which takes precedence via
            # KBUILD_OPTIONS) exists; leave it alone.
            print("warning: %s has its own Kbuild/Makefile, skipping %s" %
                  (pkg, [t.name for t in targets]), file=sys.stderr)
            continue
        lines = [GEN_HEADER]
        for t in targets:
            out = t.attrs["out"]
            modname = os.path.splitext(os.path.basename(out))[0]
            # ddk_module outs may live in subdirectories
            outdir = os.path.dirname(out)
            srcs = ws.files(ws.attr(t, "srcs", []), t.pkg)
            objs = []
            wrappers = []
            pkgdir = pkg + "/"
            for s in srcs:
                if not s.endswith((".c", ".S")):
                    continue
                if s.startswith(pkgdir):
                    objs.append(objname(s[len(pkgdir):]))
                else:
                    wrappers.append(s)
            # Sources outside the package are compiled via a wrapper that
            # #includes them, since Kbuild can't build objects outside $(obj).
            for s in wrappers:
                w = "ddk-ext-" + os.path.basename(s)
                if write:
                    with open(os.path.join(TREE, pkg, w), "w") as f:
                        f.write("// SPDX-License-Identifier: GPL-2.0\n"
                                "/* Generated by scripts/google/ddk2kbuild.py */\n"
                                "#include \"%s\"\n" % os.path.relpath(
                                    os.path.join(TREE, s), os.path.join(TREE, pkg)))
                generated.append(os.path.join(pkg, w))
                objs.append(objname(w))
            cond = ws.attr(t, "conditional_srcs", {}) or {}
            condobjs = []
            for cfg, branches in sorted(cond.items()):
                for val, files in branches.items():
                    fl = [objname(f[len(pkgdir):]) for f in ws.files(files, t.pkg)
                          if f.endswith((".c", ".S")) and f.startswith(pkgdir)]
                    if fl:
                        condobjs.append((cfg, bool(val), fl))

            full = os.path.join(outdir, modname) if outdir else modname
            all_objs = objs + [o for _, _, fl in condobjs for o in fl]
            # Kbuild can't have a composite object that contains a source
            # with the same name as the module, so rename via a wrapper.
            if full + ".o" in all_objs and (len(all_objs) > 1 or condobjs):
                src = None
                for ext in (".c", ".S"):
                    if os.path.exists(os.path.join(TREE, pkg, full + ext)):
                        src = full + ext
                w = full + "-main" + os.path.splitext(src)[1]
                if write:
                    with open(os.path.join(TREE, pkg, w), "w") as f:
                        f.write("// SPDX-License-Identifier: GPL-2.0\n"
                                "/* Generated by scripts/google/ddk2kbuild.py */\n"
                                "#include \"%s\"\n" % os.path.basename(src))
                generated.append(os.path.join(pkg, w))
                objs = [w[:-2] + ".o" if o == full + ".o" else o for o in objs]
                condobjs = [(c, v, [w[:-2] + ".o" if o == full + ".o" else o for o in fl])
                            for c, v, fl in condobjs]

            lines.append("\n# %s (%s)\n" % (t.name, out))
            if not objs and len(condobjs) == 1 and condobjs[0][1]:
                # Preserve a sole Kconfig gate, including =y for the EL2 driver.
                lines.append("obj-$(%s) += %s.o\n" % (condobjs[0][0], full))
            else:
                lines.append("obj-m += %s.o\n" % full)
            simple = objs == [full + ".o"] and not condobjs
            if not simple:
                for o in objs:
                    lines.append("%s-y += %s\n" % (full, o))
                for cfg, val, fl in condobjs:
                    if val:
                        for o in fl:
                            lines.append("%s-$(%s) += %s\n" % (full, cfg, o))
                    else:
                        lines.append("ifndef %s\n" % cfg)
                        for o in fl:
                            lines.append("%s-y += %s\n" % (full, o))
                        lines.append("endif\n")
            # Compiler flags
            incs = []
            seen = set()
            for inc in ws.attr(t, "includes", []) or []:
                incs.append(os.path.normpath(os.path.join(pkg, inc)))
            for d in ws.attr(t, "hdrs", []) or []:
                incs.extend(ws.exported_includes(norm(d, pkg), seen))
            for d in ws.attr(t, "deps", []) or []:
                incs.extend(ws.exported_includes(norm(d, pkg), seen))
            uniq = []
            for i in [pkg] + incs:
                if i not in uniq:
                    uniq.append(i)
            flags = ["-I$(srctree)/%s" % i for i in uniq]
            # Escape quotes so string defines survive the shell
            flags += ["-D%s" % d.replace('"', '\\"')
                      for d in ws.attr(t, "local_defines", []) or []]
            # -Werror is left to CONFIG_WERROR
            for c in ws.attr(t, "copts", []) or []:
                if c == "-Werror":
                    continue
                if "$(location " in c:
                    label = c[len("$(location "):-1]
                    files = ws.files([label], pkg)
                    if len(files) != 1:
                        raise ValueError("Expected one location input: %s" % label)
                    c = "$(srctree)/" + files[0]
                flags.append(c.replace('"', '\\"'))
            flags += EXTRA_FLAGS.get(t.label, [])
            flags.append("$(GOOGLE_DDK_INTERNAL_INCLUDES)")
            # The display drivers and lwis have tracepoints with the same
            # names (e.g. dsi_tx, msleep and tracing_mark_write); disable them.
            if pkg.startswith(("google-modules/display/", "google-modules/lwis")):
                flags.append("-DNOTRACE")
            var = "ddk-flags-" + full.replace("/", "-")
            lines.append("%s := %s\n" % (var, " \\\n\t".join(flags)))
            objlist = objs + [o for _, _, fl in condobjs for o in fl]
            if simple:
                objlist = [full + ".o"]
            for o in objlist:
                fv = "AFLAGS" if os.path.exists(os.path.join(TREE, pkg, o[:-2] + ".S")) else "CFLAGS"
                lines.append("%s_%s += $(%s)\n" % (fv, o, var))

            kc = ws.attr(t, "kconfig")
            if kc:
                kconfigs.extend(ws.files([kc], pkg))
            dc = ws.attr(t, "defconfig")
            if dc:
                defconfigs.extend(ws.files([dc], pkg))

        if write:
            with open(os.path.join(TREE, pkg, "Kbuild"), "w") as f:
                f.write("".join(lines))
        generated.append(os.path.join(pkg, "Kbuild"))

    # Kconfigs already sourced by the device Kconfig.ext files
    ext_sourced = set()
    for ext in ("google-devices/lga/Kconfig.ext.lga",
                "google-devices/muzel/Kconfig.ext.muzel"):
        for line in Path(TREE, ext).read_text().splitlines():
            line = line.strip()
            if line.startswith("source"):
                p = line.split('"')[1]
                p = p.replace("$(KCONFIG_EXT_MODULES_PREFIX)private/", "")
                p = p.replace("$(KCONFIG_SOC_GS_PREFIX)", "google-modules/soc/gs/")
                p = p.replace("$(KCONFIG_SOC_RDO_PREFIX)", "google-modules/soc/rdo/")
                ext_sourced.add(os.path.normpath(p))
    kc_out = []
    for k in kconfigs:
        if k not in ext_sourced and k not in kc_out:
            kc_out.append(k)
    dc_out = []
    for d in defconfigs:
        if d not in dc_out:
            dc_out.append(d)

    if write:
        with open(os.path.join(TREE, "google-modules", "Kconfig.ddk"), "w") as f:
            f.write(GEN_HEADER.replace("#", "#", 1))
            for k in kc_out:
                f.write('source "%s"\n' % k)
        with open(os.path.join(TREE, "google-modules", "ddk.config"), "w") as f:
            f.write(GEN_HEADER)
            for d in dc_out:
                f.write("\n# %s\n" % d)
                f.write(Path(TREE, d).read_text().rstrip("\n") + "\n")
        with open(os.path.join(TREE, "google-modules", "Makefile.ddk"), "w") as f:
            f.write(GEN_HEADER)
            for pkg in sorted(bypkg):
                if os.path.join(pkg, "Kbuild") in generated:
                    f.write("obj-y += %s/\n" % os.path.relpath(pkg, "google-modules"))

    print("ddk modules: %d in %d packages" % (len(mods), len(bypkg)))
    print("kernel_module targets (hand-written Makefiles):")
    for lab, t in sorted(kmods.items()):
        print("  %s" % lab)
    return mods, kmods


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="muzel")
    ap.add_argument("--list", action="store_true", help="only list modules")
    args = ap.parse_args()
    ws = Workspace()
    ws.scan(["google-modules", "google-devices"])
    devices = ["google-devices/%s:%s" % (args.device, args.device),
               "google-devices/lga:lga_base"]
    mods, kmods = gen(ws, devices, write=not args.list)
    if args.list:
        for lab, t in sorted(mods.items()):
            print(lab, t.attrs.get("out"))


if __name__ == "__main__":
    main()
