#!/usr/bin/env python3
"""Offline tests for Pi 3B+ OS hygiene, cgroup guardrails, sudoers, and device/os_apply.py.

Run: python3 tools/test-os-hygiene.py
"""
import sys

sys.dont_write_bytecode = True  # before any import

import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DEVICE_DIR = os.path.join(ROOT, "device")
FILES_DIR = os.path.join(DEVICE_DIR, "files")
OS_APPLY_PY = os.path.join(DEVICE_DIR, "os_apply.py")
BOOTSTRAP_SH = os.path.join(DEVICE_DIR, "bootstrap.sh")

ZRAM_CONF = os.path.join(FILES_DIR, "etc", "systemd", "zram-generator.conf")
SYSCTL_VM_CONF = os.path.join(FILES_DIR, "etc", "sysctl.d", "90-media-stick-vm.conf")
JOURNALD_CONF = os.path.join(FILES_DIR, "etc", "systemd", "journald.conf.d", "media-stick.conf")
SUDOERS_FILE = os.path.join(FILES_DIR, "etc", "sudoers.d", "media-stick")
WEBAPP_STOP_BIN = os.path.join(FILES_DIR, "usr", "local", "sbin", "media-stick-webapp-stop")
WEBAPP_BIN = os.path.join(FILES_DIR, "usr", "local", "bin", "web-app")
TMPFILES_CONF = os.path.join(FILES_DIR, "etc", "tmpfiles.d", "media-stick.conf")

SYSTEMD_DIR = os.path.join(FILES_DIR, "etc", "systemd", "system")
KODI_SERVICE = os.path.join(SYSTEMD_DIR, "kodi.service")
WEBAPP_SERVICE = os.path.join(SYSTEMD_DIR, "web-app@.service")
PANEL_SERVICE = os.path.join(SYSTEMD_DIR, "panel.service")
AIRPLAY_SERVICE = os.path.join(SYSTEMD_DIR, "airplay.service")
MIRACAST_SERVICE = os.path.join(SYSTEMD_DIR, "miracast.service")


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _load_os_apply(testcase):
    testcase.assertTrue(os.path.exists(OS_APPLY_PY), f"missing {OS_APPLY_PY}")
    spec = importlib.util.spec_from_file_location("os_apply", OS_APPLY_PY)
    testcase.assertIsNotNone(spec, f"could not load spec for {OS_APPLY_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _spec_path(spec):
    for attr in ("rel_path", "path", "rel", "dest"):
        if hasattr(spec, attr):
            return getattr(spec, attr)
    if isinstance(spec, tuple) and spec:
        return spec[0]
    raise AssertionError(f"FileSpec {spec!r} has no recognizable path attribute")


def _spec_mode(spec):
    if hasattr(spec, "mode"):
        return spec.mode
    if isinstance(spec, tuple) and len(spec) >= 2:
        return spec[1]
    raise AssertionError(f"FileSpec {spec!r} has no recognizable mode attribute")


class TestZramSysctlJournaldTmpfiles(unittest.TestCase):
    """Verify zram, sysctl VM tuning, volatile journald, and tmpfiles.d configs."""

    def test_zram_generator_conf(self):
        self.assertTrue(os.path.exists(ZRAM_CONF), f"missing {ZRAM_CONF}")
        text = _strip_comments(_read_text(ZRAM_CONF))
        self.assertIn("[zram0]", text)
        self.assertRegex(text, r"(?m)^zram-size\s*=\s*384\b")
        self.assertRegex(text, r"(?m)^compression-algorithm\s*=\s*zstd\b")
        self.assertRegex(text, r"(?m)^swap-priority\s*=\s*100\b")

    def test_sysctl_vm_conf(self):
        self.assertTrue(os.path.exists(SYSCTL_VM_CONF), f"missing {SYSCTL_VM_CONF}")
        text = _strip_comments(_read_text(SYSCTL_VM_CONF))
        self.assertRegex(text, r"(?m)^vm\.swappiness\s*=\s*100\b")
        self.assertRegex(text, r"(?m)^vm\.page-cluster\s*=\s*0\b")
        self.assertRegex(text, r"(?m)^vm\.vfs_cache_pressure\s*=\s*100\b")

    def test_journald_volatile_conf(self):
        self.assertTrue(os.path.exists(JOURNALD_CONF), f"missing {JOURNALD_CONF}")
        text = _strip_comments(_read_text(JOURNALD_CONF))
        self.assertIn("[Journal]", text)
        self.assertRegex(text, r"(?m)^Storage\s*=\s*volatile\b")
        self.assertRegex(text, r"(?m)^RuntimeMaxUse\s*=\s*16M\b")

    def test_tmpfiles_conf_includes_runtime_and_browser_cache(self):
        self.assertTrue(os.path.exists(TMPFILES_CONF), f"missing {TMPFILES_CONF}")
        text = _strip_comments(_read_text(TMPFILES_CONF))
        for path in (
            "/run/media-stick/resume",
            "/run/media-stick/page-cache",
            "/tmp/chromium-cache",
        ):
            with self.subTest(path=path):
                self.assertIn(path, text)


class TestSudoersAndWebappStop(unittest.TestCase):
    """Verify least-privilege sudoers allowlist and media-stick-webapp-stop."""

    REQUIRED_ALLOWS = (
        "/usr/bin/systemctl restart kodi.service",
        "/usr/bin/systemctl reboot",
        "/usr/bin/systemctl poweroff",
        "/usr/bin/systemctl start --no-block media-stick-update.service",
        "/usr/bin/systemctl start --no-block web-app@netflix.service",
        "/usr/bin/systemctl start --no-block web-app@disney.service",
        "/usr/bin/systemctl start --no-block web-app@prime.service",
        "/usr/bin/systemctl start --no-block web-app@max.service",
        "/usr/bin/systemctl start --no-block web-app@youtube.service",
        "/usr/local/sbin/media-stick-webapp-stop",
        "/usr/local/bin/wifi-setup scan",
        "/usr/local/bin/wifi-setup connect",
        "/usr/local/bin/media-stick-https set",
        "/usr/local/bin/media-stick-https status",
        "/usr/local/bin/media-stick-https clear",
    )

    def test_sudoers_media_stick_least_privilege(self):
        self.assertTrue(os.path.exists(SUDOERS_FILE), f"missing {SUDOERS_FILE}")
        text = _strip_comments(_read_text(SUDOERS_FILE))
        self.assertNotRegex(text, r"NOPASSWD:\s*ALL\b", "media sudoers must not grant NOPASSWD: ALL")
        self.assertNotIn("web-app@*", text, "sudoers must enumerate web-app services without wildcards")
        for cmd in self.REQUIRED_ALLOWS:
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, text)

    def test_webapp_stop_wrapper_exists_and_executable(self):
        self.assertTrue(os.path.exists(WEBAPP_STOP_BIN), f"missing {WEBAPP_STOP_BIN}")
        self.assertTrue(os.access(WEBAPP_STOP_BIN, os.X_OK), f"{WEBAPP_STOP_BIN} must be executable")
        text = _read_text(WEBAPP_STOP_BIN)
        self.assertIn("web-app@", text)
        self.assertIn("systemctl", text)


class TestSystemdGuardrailsAndWebApp(unittest.TestCase):
    """Verify systemd memory limits, OOMScoreAdjust, boot ordering, and web-app flags."""

    def test_kodi_service_boot_and_cgroup_guardrails(self):
        text = _strip_comments(_read_text(KODI_SERVICE))
        self.assertNotIn("network-online.target", text, "kodi.service must not wait for network-online.target")
        self.assertRegex(text, r"(?m)^MemoryHigh=380M\b")
        self.assertRegex(text, r"(?m)^MemoryMax=480M\b")
        self.assertRegex(text, r"(?m)^OOMScoreAdjust=200\b")

    def test_webapp_service_cgroup_guardrails(self):
        text = _strip_comments(_read_text(WEBAPP_SERVICE))
        self.assertRegex(text, r"(?m)^MemoryHigh=450M\b")
        self.assertRegex(text, r"(?m)^MemoryMax=580M\b")
        self.assertRegex(text, r"(?m)^OOMScoreAdjust=500\b")

    def test_critical_daemons_oom_score_adjust(self):
        for svc in (PANEL_SERVICE, AIRPLAY_SERVICE, MIRACAST_SERVICE):
            with self.subTest(service=os.path.basename(svc)):
                text = _strip_comments(_read_text(svc))
                self.assertRegex(text, r"(?m)^OOMScoreAdjust=-200\b")

    def test_webapp_script_chromium_cache_and_no_cage_debug(self):
        text = _strip_comments(_read_text(WEBAPP_BIN))
        self.assertIn("--disk-cache-dir=/tmp/chromium-cache", text)
        self.assertIn("--disk-cache-size=33554432", text)
        self.assertNotRegex(text, r"\bcage\s+-d\b", "cage must not run with -d debug flag")


class TestOsApplyPureCore(unittest.TestCase):
    """In-memory unit tests for device/os_apply.py Pure Core functions."""

    def test_plan_file_ops_modes_and_orphans(self):
        mod = _load_os_apply(self)
        cases = [
            (
                "standard_modes_and_orphan",
                [
                    "usr/local/bin/web-app",
                    "usr/local/sbin/media-stick-webapp-stop",
                    "etc/sudoers.d/media-stick",
                    "etc/systemd/system/kodi.service",
                    "etc/sysctl.d/90-media-stick-vm.conf",
                ],
                [
                    "usr/local/bin/web-app",
                    "etc/systemd/system/old-removed.service",
                ],
                {
                    "usr/local/bin/web-app": 0o755,
                    "usr/local/sbin/media-stick-webapp-stop": 0o755,
                    "etc/sudoers.d/media-stick": 0o440,
                    "etc/systemd/system/kodi.service": 0o644,
                    "etc/sysctl.d/90-media-stick-vm.conf": 0o644,
                },
                ["etc/systemd/system/old-removed.service"],
            ),
            (
                "adjacent_prefix_boundaries_get_0644",
                [
                    "usr/local/binary/tool",
                    "usr/bin/other",
                    "etc/sudoers.d.bak/media-stick",
                    "usr/local/bin/nested/helper",
                ],
                [],
                {
                    "usr/local/binary/tool": 0o644,
                    "usr/bin/other": 0o644,
                    "etc/sudoers.d.bak/media-stick": 0o644,
                    "usr/local/bin/nested/helper": 0o644,
                },
                [],
            ),
            (
                "empty_src_prunes_all_prev_managed",
                [],
                ["etc/a.conf", "usr/local/bin/b"],
                {},
                ["etc/a.conf", "usr/local/bin/b"],
            ),
        ]
        for name, src_files, prev_managed, expected_modes, expected_orphans in cases:
            with self.subTest(case=name):
                specs, orphans = mod.plan_file_ops(src_files, prev_managed)
                got_modes = {_spec_path(s): _spec_mode(s) for s in specs}
                self.assertEqual(got_modes, expected_modes)
                self.assertEqual(sorted(orphans), sorted(expected_orphans))

    def test_reconcile_fstab_lines_table(self):
        mod = _load_os_apply(self)
        tmpfs_entry = "tmpfs /home/media/.kodi/temp tmpfs nosuid,nodev,noexec,size=16M,uid=1000,gid=1000,mode=0755 0 0"

        cases = [
            (
                "adds_noatime_commit60_and_tmpfs",
                [
                    "PARTUUID=1234-01  /boot/firmware  vfat    defaults          0       2",
                    "PARTUUID=1234-02  /               ext4    defaults          0       1",
                ],
                True,
            ),
            (
                "preserves_existing_noatime_adds_commit60",
                [
                    "PARTUUID=1234-02  /               ext4    defaults,noatime  0       1",
                ],
                True,
            ),
            (
                "already_reconciled_is_noop",
                [
                    "PARTUUID=1234-01  /boot/firmware  vfat    defaults          0       2",
                    "PARTUUID=1234-02  /               ext4    defaults,noatime,commit=60  0       1",
                    tmpfs_entry,
                ],
                False,
            ),
            (
                "comments_not_treated_as_mounts",
                [
                    "# PARTUUID=1234-02 / ext4 defaults,noatime,commit=60 0 1",
                    "# tmpfs /home/media/.kodi/temp tmpfs defaults 0 0",
                    "/dev/mmcblk0p2 / ext4 defaults 0 1",
                ],
                True,
            ),
        ]
        for name, existing, expect_changed in cases:
            with self.subTest(case=name):
                lines1, changed1 = mod.reconcile_fstab_lines(list(existing))
                self.assertEqual(changed1, expect_changed)
                joined = "\n".join(lines1)
                self.assertIn("noatime", joined)
                self.assertIn("commit=60", joined)
                self.assertIn("/home/media/.kodi/temp", joined)
                self.assertIn("size=16M", joined)
                # /boot/firmware must not get commit=60
                for ln in lines1:
                    if "/boot/firmware" in ln and not ln.lstrip().startswith("#"):
                        self.assertNotIn("commit=60", ln)
                # Idempotence: second run must report changed == False and zero diff
                lines2, changed2 = mod.reconcile_fstab_lines(lines1)
                self.assertFalse(changed2, f"{name}: second run must be idempotent")
                self.assertEqual(lines2, lines1)

    def test_extract_changed_units(self):
        mod = _load_os_apply(self)
        existing = {"kodi.service", "panel.service"}
        updated = [
            "etc/systemd/system/kodi.service",
            "etc/systemd/system/airplay.service",
            "etc/sysctl.d/90-media-stick-vm.conf",
            "usr/local/bin/web-app",
        ]
        units = mod.extract_changed_units(updated, existing)
        self.assertIn("kodi.service", units)
        self.assertNotIn("airplay.service", units)
        self.assertNotIn("90-media-stick-vm.conf", units)
        self.assertNotIn("web-app", units)
        self.assertEqual(mod.extract_changed_units([], existing), [])


class TestOsApplyThinShell(unittest.TestCase):
    """Thin I/O shell tests for device/os_apply.py using temporary --root and --repo."""

    def test_os_apply_syncs_files_with_modes_and_prunes_orphans(self):
        self.assertTrue(os.path.exists(OS_APPLY_PY), f"missing {OS_APPLY_PY}")
        with tempfile.TemporaryDirectory(prefix="test-os-apply-") as tmp:
            repo = os.path.join(tmp, "repo")
            root = os.path.join(tmp, "root")
            os.makedirs(os.path.join(repo, "device", "files", "usr", "local", "bin"))
            os.makedirs(os.path.join(repo, "device", "files", "usr", "local", "sbin"))
            os.makedirs(os.path.join(repo, "device", "files", "etc", "sudoers.d"))
            os.makedirs(os.path.join(repo, "device", "files", "etc", "sysctl.d"))
            os.makedirs(os.path.join(root, "etc"))

            with open(os.path.join(root, "etc", "fstab"), "w", encoding="utf-8") as f:
                f.write("PARTUUID=1234-02 / ext4 defaults 0 1\n")

            files = {
                "usr/local/bin/demo": "echo hi\n",
                "usr/local/sbin/demo-admin": "echo admin\n",
                "etc/sudoers.d/media-stick": "media ALL=(ALL) NOPASSWD: /usr/bin/systemctl reboot\n",
                "etc/sysctl.d/90-demo.conf": "vm.swappiness = 100\n",
            }
            for rel, content in files.items():
                p = os.path.join(repo, "device", "files", rel)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)

            proc = subprocess.run(
                [sys.executable, OS_APPLY_PY, "--repo", repo, "--root", root, "--skip-visudo"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, f"os_apply failed: {proc.stderr}\n{proc.stdout}")

            expected_modes = {
                "usr/local/bin/demo": 0o755,
                "usr/local/sbin/demo-admin": 0o755,
                "etc/sudoers.d/media-stick": 0o440,
                "etc/sysctl.d/90-demo.conf": 0o644,
            }
            for rel, mode in expected_modes.items():
                target = os.path.join(root, rel)
                self.assertTrue(os.path.exists(target), f"missing synced file {target}")
                got_mode = stat.S_IMODE(os.stat(target).st_mode)
                self.assertEqual(got_mode, mode, f"{rel}: expected mode {oct(mode)}, got {oct(got_mode)}")

            managed_json = os.path.join(root, "var", "lib", "media-stick", "managed-files.json")
            self.assertTrue(os.path.exists(managed_json), f"missing {managed_json}")
            with open(managed_json, encoding="utf-8") as f:
                managed = json.load(f)
            self.assertIn("etc/sysctl.d/90-demo.conf", str(managed))

            fstab_text = _read_text(os.path.join(root, "etc", "fstab"))
            self.assertIn("noatime", fstab_text)
            self.assertIn("commit=60", fstab_text)
            self.assertIn("/home/media/.kodi/temp", fstab_text)

            # Remove one source file and re-run: orphan must be pruned from root
            os.remove(os.path.join(repo, "device", "files", "etc", "sysctl.d", "90-demo.conf"))
            proc2 = subprocess.run(
                [sys.executable, OS_APPLY_PY, "--repo", repo, "--root", root, "--skip-visudo"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(proc2.returncode, 0, f"second os_apply failed: {proc2.stderr}")
            self.assertFalse(
                os.path.exists(os.path.join(root, "etc", "sysctl.d", "90-demo.conf")),
                "orphaned file was not pruned from root",
            )

    def test_os_apply_dry_run_makes_no_changes(self):
        self.assertTrue(os.path.exists(OS_APPLY_PY), f"missing {OS_APPLY_PY}")
        with tempfile.TemporaryDirectory(prefix="test-os-apply-dry-") as tmp:
            repo = os.path.join(tmp, "repo")
            root = os.path.join(tmp, "root")
            os.makedirs(os.path.join(repo, "device", "files", "etc", "sysctl.d"))
            os.makedirs(root)
            with open(os.path.join(repo, "device", "files", "etc", "sysctl.d", "90-demo.conf"), "w", encoding="utf-8") as f:
                f.write("vm.swappiness = 100\n")

            proc = subprocess.run(
                [sys.executable, OS_APPLY_PY, "--repo", repo, "--root", root, "--skip-visudo", "--dry-run"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, f"dry-run failed: {proc.stderr}")
            self.assertFalse(os.path.exists(os.path.join(root, "etc", "sysctl.d", "90-demo.conf")))
            self.assertFalse(os.path.exists(os.path.join(root, "var", "lib", "media-stick", "managed-files.json")))

    def test_ensure_msadmin_callable(self):
        mod = _load_os_apply(self)
        self.assertTrue(callable(getattr(mod, "ensure_msadmin", None)), "os_apply.py must define ensure_msadmin")


class TestBootstrapIntegration(unittest.TestCase):
    """Verify device/bootstrap.sh wires zram, os_apply.py, displayd, and Kodi start guard."""

    def test_bootstrap_packages_and_services(self):
        text = _strip_comments(_read_text(BOOTSTRAP_SH))
        self.assertIn("systemd-zram-generator", text)
        self.assertIn("dphys-swapfile", text)
        self.assertIn("mediastick-displayd.service", text)
        self.assertRegex(text, r"python3\s+\"?\$REPO/device/os_apply\.py\"?\s+--repo\s+\"?\$REPO\"?")

    def test_bootstrap_guards_kodi_start_when_media_session_active(self):
        text = _strip_comments(_read_text(BOOTSTRAP_SH))
        m = re.search(r"systemctl start kodi", text)
        self.assertIsNotNone(m, "bootstrap.sh must still contain systemctl start kodi")
        # Guard must appear in the block around systemctl start kodi
        start_idx = max(0, m.start() - 600)
        guard_window = text[start_idx : m.end() + 100]
        self.assertIn("/run/media-stick/airplay", guard_window)
        self.assertIn("/run/media-stick/miracast", guard_window)
        self.assertIn("web-app@", guard_window)


if __name__ == "__main__":
    unittest.main(verbosity=2)
