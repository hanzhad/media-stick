#!/usr/bin/env python3
"""Offline hygiene tests for Makefile, GitHub Actions CI, deploy.sh, and Dockerfiles.

Run: python3 tools/test-deploy-hygiene.py
"""
import sys

sys.dont_write_bytecode = True  # before any import

import os  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DEPLOY_SH = os.path.join(ROOT, "tools", "deploy.sh")
EMU_DOCKERFILE = os.path.join(ROOT, "tools", "emulator", "Dockerfile")
EMU_RUN_SH = os.path.join(ROOT, "tools", "emulator", "run.sh")
CHECK_PY = os.path.join(ROOT, "tools", "check.py")
MAKEFILE = os.path.join(ROOT, "Makefile")
CI_YML = os.path.join(ROOT, "docs", "ci-workflow.yml")


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _extract_rsync_excludes(deploy_text):
    """Extract --exclude patterns from the --local) case branch in tools/deploy.sh."""
    m = re.search(r"^\s*--local\)(.*?)^\s*;;", deploy_text, re.MULTILINE | re.DOTALL)
    if not m:
        return None, ""
    block = _strip_comments(m.group(1))
    # Join backslash-continued lines before tokenizing
    joined = re.sub(r"\\\r?\n", " ", block)
    rsync_lines = [ln for ln in joined.splitlines() if re.search(r"\brsync\b", ln)]
    if not rsync_lines:
        return [], block
    excludes = []
    for ln in rsync_lines:
        tokens = shlex.split(ln)
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "--exclude" and i + 1 < len(tokens):
                excludes.append(tokens[i + 1])
                i += 2
                continue
            if tok.startswith("--exclude="):
                excludes.append(tok.split("=", 1)[1])
            i += 1
    return excludes, block


def _extract_exposed_ports(dockerfile_text):
    ports = []
    for line in _strip_comments(dockerfile_text).splitlines():
        m = re.match(r"^\s*EXPOSE\s+(.+)$", line, re.IGNORECASE)
        if not m:
            continue
        for tok in m.group(1).split():
            ports.append(tok.split("/")[0])
    return ports


class TestDeployRsyncExclusions(unittest.TestCase):
    """Verify tools/deploy.sh --local excludes dev/agent/cache artifacts."""

    REQUIRED_EXCLUDES = (
        ".git",
        "*.local",
        "secrets.env",
        "__pycache__/",
        "*.pyc",
        ".devcontainer/",
        ".claude/",
        "project.env",
        "tools/emulator/.state/",
        ".github/",
    )

    def test_deploy_sh_local_excludes_all_required_patterns(self):
        self.assertTrue(os.path.exists(DEPLOY_SH), f"missing {DEPLOY_SH}")
        excludes, block = _extract_rsync_excludes(_read_text(DEPLOY_SH))
        self.assertIsNotNone(excludes, "--local) branch not found in tools/deploy.sh")
        self.assertIn("--delete", block, "--local rsync must retain --delete")
        for pattern in self.REQUIRED_EXCLUDES:
            with self.subTest(exclude=pattern):
                self.assertIn(
                    pattern,
                    excludes,
                    f"tools/deploy.sh --local rsync missing --exclude {pattern!r}; got {excludes}",
                )


class TestEmulatorDockerfile(unittest.TestCase):
    """Verify tools/emulator/Dockerfile exposes PANEL_PORT (18080) and Kodi ports."""

    def test_emulator_dockerfile_exposes_18080_and_kodi_ports(self):
        self.assertTrue(os.path.exists(EMU_DOCKERFILE), f"missing {EMU_DOCKERFILE}")
        ports = _extract_exposed_ports(_read_text(EMU_DOCKERFILE))
        for required_port in ("18080", "8080", "9090"):
            with self.subTest(port=required_port):
                self.assertIn(
                    required_port,
                    ports,
                    f"tools/emulator/Dockerfile EXPOSE missing {required_port}; got {ports}",
                )

    def test_emulator_dockerfile_matches_run_sh_default_panel_port(self):
        self.assertTrue(os.path.exists(EMU_RUN_SH), f"missing {EMU_RUN_SH}")
        run_text = _read_text(EMU_RUN_SH)
        m = re.search(r"PANEL_PORT=\$\{PANEL_PORT:-(\d+)\}", run_text)
        self.assertIsNotNone(m, "PANEL_PORT default not found in tools/emulator/run.sh")
        default_port = m.group(1)
        ports = _extract_exposed_ports(_read_text(EMU_DOCKERFILE))
        self.assertIn(
            default_port,
            ports,
            f"Dockerfile must expose run.sh default PANEL_PORT={default_port}; got {ports}",
        )


class TestCheckRunner(unittest.TestCase):
    """Verify tools/check.py exists, is executable, and supports --lint and --test."""

    def test_check_py_exists_and_is_executable(self):
        self.assertTrue(os.path.exists(CHECK_PY), f"missing {CHECK_PY}")
        self.assertTrue(os.access(CHECK_PY, os.X_OK), f"{CHECK_PY} must be executable")

    def test_check_py_supports_lint_and_test_flags(self):
        self.assertTrue(os.path.exists(CHECK_PY), f"missing {CHECK_PY}")
        p = subprocess.run([sys.executable, CHECK_PY, "--help"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, f"check.py --help failed: {p.stderr}")
        self.assertIn("--lint", p.stdout, "check.py must support --lint")
        self.assertIn("--test", p.stdout, "check.py must support --test")


class TestMakefile(unittest.TestCase):
    """Verify Makefile defines lint, test, and check targets delegating to tools/check.py."""

    def test_makefile_exists_and_defines_targets(self):
        self.assertTrue(os.path.exists(MAKEFILE), f"missing {MAKEFILE}")
        text = _strip_comments(_read_text(MAKEFILE))
        targets = set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:", text, re.MULTILINE))
        for target in ("lint", "test", "check"):
            with self.subTest(target=target):
                self.assertIn(target, targets, f"Makefile missing target {target!r}")

    def test_makefile_delegates_to_check_py(self):
        self.assertTrue(os.path.exists(MAKEFILE), f"missing {MAKEFILE}")
        text = _strip_comments(_read_text(MAKEFILE))
        self.assertIn("tools/check.py --lint", text, "Makefile lint must invoke tools/check.py --lint")
        self.assertIn("tools/check.py --test", text, "Makefile test must invoke tools/check.py --test")
        self.assertRegex(text, re.compile(r"^check\s*:.*?tools/check\.py\b", re.MULTILINE | re.DOTALL), "Makefile check target must invoke tools/check.py")
        if shutil.which("make"):
            for target in ("lint", "test", "check"):
                with self.subTest(dry_run=target):
                    p = subprocess.run(["make", "-n", target], cwd=ROOT, capture_output=True, text=True, timeout=10)
                    self.assertEqual(p.returncode, 0, f"make -n {target} failed: {p.stderr}")


class TestGitHubActionsCI(unittest.TestCase):
    """Verify docs/ci-workflow.yml triggers, packages, and runs make check offline."""

    REQUIRED_PACKAGES = (
        "shellcheck",
        "libxml2-utils",
        "python3-pil",
        "python3-numpy",
        "jq",
        "fonts-roboto-unhinted",
    )

    def test_ci_workflow_exists_and_runs_make_check(self):
        self.assertTrue(os.path.exists(CI_YML), f"missing {CI_YML}")
        text = _strip_comments(_read_text(CI_YML))
        self.assertRegex(text, r"\bpull_request\b", "docs/ci-workflow.yml must trigger on pull_request")
        self.assertRegex(text, r"\bpush\b", "docs/ci-workflow.yml must trigger on push")
        self.assertRegex(text, r"\bmain\b", "docs/ci-workflow.yml must target main branch")
        self.assertRegex(text, r"\bubuntu-latest\b", "docs/ci-workflow.yml must run on ubuntu-latest")
        self.assertRegex(text, r"\b(make\s+check|python3\s+tools/check\.py)\b", "docs/ci-workflow.yml must run make check or python3 tools/check.py")
        self.assertNotIn("deploy.sh", text, "docs/ci-workflow.yml must stay offline and never invoke deploy.sh")
        self.assertNotIn("mediastick.local", text, "docs/ci-workflow.yml must never touch a physical Pi")
        for pkg in self.REQUIRED_PACKAGES:
            with self.subTest(package=pkg):
                self.assertIn(pkg, text, f"docs/ci-workflow.yml must install {pkg}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
