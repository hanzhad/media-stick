#!/usr/bin/env python3
"""Offline tests for v2 operational tools, cross-platform provisioning, and docs.

Run: python3 tools/test-v2-ops.py
"""
import sys

sys.dont_write_bytecode = True  # before any import

import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

PREPARE_BOOTFS = os.path.join(ROOT, "provisioning", "prepare-bootfs.sh")
DOCTOR_SH = os.path.join(ROOT, "tools", "doctor.sh")
EMU_RUN_SH = os.path.join(ROOT, "tools", "emulator", "run.sh")
SHARE_SRC = os.path.join(ROOT, "device", "files", "usr", "local", "share", "media-stick")
ARCH_DOC = os.path.join(ROOT, "docs", "architecture.md")
AGENTS_MD = os.path.join(ROOT, "AGENTS.md")
README_MD = os.path.join(ROOT, "README.md")
HANDOFF_MD = os.path.join(ROOT, "HANDOFF.md")


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


class TestPrepareBootfs(unittest.TestCase):
    """Verify provisioning/prepare-bootfs.sh works portably on Linux/WSL and idempotently."""

    def test_no_macos_only_sed_in_place(self):
        text = _strip_comments(_read_text(PREPARE_BOOTFS))
        self.assertNotRegex(
            text,
            r"\bsed\s+-i\s+(['\"])\1",
            "prepare-bootfs.sh must not use macOS-only sed -i ''",
        )

    def test_runs_cleanly_on_linux_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="test-bootfs-") as tmp:
            boot = os.path.join(tmp, "bootfs")
            os.makedirs(boot)
            cmdline = os.path.join(boot, "cmdline.txt")
            metadata = os.path.join(boot, "meta-data")
            pubkey = os.path.join(tmp, "mediastick.pub")

            with open(cmdline, "w", encoding="utf-8") as f:
                f.write("console=serial0,115200 console=tty1 root=PARTUUID=1234-02 rootfstype=ext4\n")
            with open(metadata, "w", encoding="utf-8") as f:
                f.write("instance-id: media-stick-test\n")
            test_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForPrepareBootfs test@example"
            with open(pubkey, "w", encoding="utf-8") as f:
                f.write(test_key + "\n")

            proc1 = subprocess.run(
                ["bash", PREPARE_BOOTFS, boot, pubkey],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(proc1.returncode, 0, f"prepare-bootfs.sh failed:\n{proc1.stdout}\n{proc1.stderr}")

            cmdline_text = _read_text(cmdline)
            self.assertIn("video=HDMI-A-1:1920x1080@60D", cmdline_text)
            self.assertEqual(cmdline_text.count("video=HDMI-A-1:1920x1080@60D"), 1)

            user_data = _read_text(os.path.join(boot, "user-data"))
            self.assertIn(test_key, user_data)
            self.assertNotIn("@SSH_PUBKEY@", user_data)
            self.assertTrue(os.path.exists(os.path.join(boot, "network-config")))
            self.assertTrue(os.path.exists(os.path.join(boot, "ssh")))
            self.assertTrue(os.path.exists(os.path.join(boot, "media-stick", "firstboot.sh")))
            self.assertTrue(os.path.exists(os.path.join(boot, "media-stick", "wifi-setup")))

            # Second run must be idempotent
            proc2 = subprocess.run(
                ["bash", PREPARE_BOOTFS, boot, pubkey],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(proc2.returncode, 0, f"second run failed:\n{proc2.stdout}\n{proc2.stderr}")
            self.assertEqual(
                _read_text(cmdline).count("video=HDMI-A-1:1920x1080@60D"),
                1,
                "prepare-bootfs.sh duplicated video=HDMI-A-1 on re-run",
            )

    def test_existing_hdmi_mode_not_duplicated_and_missing_metadata_fails(self):
        with tempfile.TemporaryDirectory(prefix="test-bootfs-edge-") as tmp:
            boot = os.path.join(tmp, "bootfs")
            os.makedirs(boot)
            cmdline = os.path.join(boot, "cmdline.txt")
            pubkey = os.path.join(tmp, "mediastick.pub")
            with open(cmdline, "w", encoding="utf-8") as f:
                f.write("console=tty1 video=HDMI-A-1:1280x720@60D\n")
            with open(pubkey, "w", encoding="utf-8") as f:
                f.write("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest test@example\n")

            # Missing meta-data must fail cleanly
            proc_bad = subprocess.run(
                ["bash", PREPARE_BOOTFS, boot, pubkey],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(proc_bad.returncode, 0, "must fail when meta-data is missing")

            # With meta-data, existing video=HDMI-A-1 must not be appended again
            with open(os.path.join(boot, "meta-data"), "w", encoding="utf-8") as f:
                f.write("")
            proc_ok = subprocess.run(
                ["bash", PREPARE_BOOTFS, boot, pubkey],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(proc_ok.returncode, 0, f"failed with existing video=HDMI-A-1: {proc_ok.stderr}")
            self.assertEqual(_read_text(cmdline).count("video=HDMI-A-1"), 1)


class TestEmulatorRunStaging(unittest.TestCase):
    """Verify tools/emulator/run.sh stages Panel v2 static PWA assets."""

    def test_emulator_run_stages_usr_local_share_media_stick(self):
        self.assertTrue(os.path.isdir(os.path.join(SHARE_SRC, "web")), "missing Panel v2 web assets dir")
        self.assertTrue(os.path.exists(os.path.join(SHARE_SRC, "web", "manifest.webmanifest")))
        text = _strip_comments(_read_text(EMU_RUN_SH))
        self.assertIn("device/files/usr/local/share/media-stick", text)
        self.assertIn("/usr/local/share/media-stick", text)


class TestDoctorV2Checks(unittest.TestCase):
    """Verify tools/doctor.sh includes v2 health checks."""

    def test_doctor_checks_v2_services_and_endpoints(self):
        text = _strip_comments(_read_text(DOCTOR_SH))
        self.assertIn("mediastick-displayd.service", text)
        self.assertIn("skin.media-stick", text)
        self.assertIn("kodi-rpc", text)
        self.assertIn("zram0", text)
        self.assertIn("media-stick-healthcheck", text)
        self.assertIn("/manifest.webmanifest", text)


class TestV2Documentation(unittest.TestCase):
    """Verify v2 docs alignment: architecture.md, AGENTS.md, README.md, and HANDOFF.md removal."""

    def test_handoff_md_deleted(self):
        self.assertFalse(os.path.exists(HANDOFF_MD), "stale HANDOFF.md must be deleted")

    def test_architecture_doc_exists_and_covers_v2(self):
        self.assertTrue(os.path.exists(ARCH_DOC), f"missing {ARCH_DOC}")
        text = _read_text(ARCH_DOC)
        self.assertGreater(len(text.strip()), 200, "docs/architecture.md must not be empty")
        required_topics = (
            "mediastick-displayd",
            "PipeWire",
            "AirPlay",
            "mediastick_store",
            "skin.media-stick",
            "panel_core",
            "/ws",
            "uinput",
            "os_apply.py",
            "zram",
            "media-stick-healthcheck",
            "docs/ci-workflow.yml",
            "msadmin",
        )
        for topic in required_topics:
            with self.subTest(topic=topic):
                self.assertIn(topic, text, f"docs/architecture.md missing v2 topic {topic!r}")

    def test_agents_md_updated_for_v2_and_drops_skin_ftv(self):
        text = _read_text(AGENTS_MD)
        self.assertNotIn("skin.ftv", text, "AGENTS.md must remove outdated skin.ftv notes")
        for topic in (
            "tools/check.py",
            "skin.media-stick",
            "mediastick-displayd",
            "mediastick_store",
            "panel_core",
            "os_apply.py",
        ):
            with self.subTest(topic=topic):
                self.assertIn(topic, text, f"AGENTS.md missing v2 topic {topic!r}")

    def test_readme_md_links_architecture_and_v2_highlights(self):
        text = _read_text(README_MD)
        self.assertIn("docs/architecture.md", text, "README.md must link to docs/architecture.md")
        self.assertNotIn("skin.ftv", text, "README.md must not reference retired skin.ftv")
        for topic in ("Quick Resume", "make check", "AirPlay", "PipeWire", "CEC"):
            with self.subTest(topic=topic):
                self.assertIn(topic, text, f"README.md missing v2 highlight {topic!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
