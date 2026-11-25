#!/usr/bin/env python3
"""Offline lint and test runner for media-stick.

Usage:
    python3 tools/check.py          # run lint then test
    python3 tools/check.py --lint   # run shellcheck, xmllint, py_compile
    python3 tools/check.py --test   # run tools/test-*.py
"""
import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import glob  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

SHELL_SCRIPT_DIRS = (
    os.path.join(ROOT, "device", "files", "usr", "local", "bin"),
    os.path.join(ROOT, "tools"),
    os.path.join(ROOT, "provisioning"),
)
SKIP_DIRS = {".git", "__pycache__", ".state"}


def _read_first_line(path):
    try:
        with open(path, "rb") as f:
            return f.readline(256).decode("utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _walk_files(base_dir):
    for dirpath, dirnames, filenames in os.walk(base_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def _find_shell_scripts():
    found = set()
    for path in _walk_files(ROOT):
        if path.endswith(".sh"):
            found.add(path)
    for base in SHELL_SCRIPT_DIRS:
        if not os.path.isdir(base):
            continue
        for path in _walk_files(base):
            if path in found:
                continue
            first = _read_first_line(path)
            if (
                first.startswith("#!/bin/bash")
                or first.startswith("#!/bin/sh")
                or first.startswith("#!/usr/bin/env bash")
                or first.startswith("#!/usr/bin/env sh")
            ):
                found.add(path)
    return sorted(found)


def _find_xml_files():
    device_dir = os.path.join(ROOT, "device")
    if not os.path.isdir(device_dir):
        return []
    return sorted(p for p in _walk_files(device_dir) if p.endswith(".xml"))


def _find_python_files():
    found = set()
    for sub in ("device", "tools"):
        base = os.path.join(ROOT, sub)
        if not os.path.isdir(base):
            continue
        for path in _walk_files(base):
            if path.endswith(".py"):
                found.add(path)
                continue
            first = _read_first_line(path)
            if first.startswith("#!") and "python" in first:
                found.add(path)
    return sorted(found)


def _rel(path):
    return os.path.relpath(path, ROOT)


def run_lint():
    failures = []

    shell_files = _find_shell_scripts()
    print(f"[lint] shellcheck -S error ({len(shell_files)} files)")
    if shell_files:
        proc = subprocess.run(["shellcheck", "-S", "error", *[_rel(p) for p in shell_files]], cwd=ROOT)
        if proc.returncode != 0:
            failures.append("shellcheck")

    xml_files = _find_xml_files()
    print(f"[lint] xmllint --noout ({len(xml_files)} files)")
    if xml_files:
        proc = subprocess.run(["xmllint", "--noout", *[_rel(p) for p in xml_files]], cwd=ROOT)
        if proc.returncode != 0:
            failures.append("xmllint")

    py_files = _find_python_files()
    print(f"[lint] python3 -m py_compile ({len(py_files)} files)")
    if py_files:
        with tempfile.TemporaryDirectory(prefix="media-stick-pycache-") as tmpdir:
            env = os.environ.copy()
            env["PYTHONPYCACHEPREFIX"] = tmpdir
            proc = subprocess.run([sys.executable, "-m", "py_compile", *[_rel(p) for p in py_files]], cwd=ROOT, env=env)
            if proc.returncode != 0:
                failures.append("py_compile")

    if failures:
        print(f"[lint] FAIL: {chr(44).join(failures)}")
        return 1
    print("[lint] PASS")
    return 0


def run_test():
    test_files = sorted(glob.glob(os.path.join(ROOT, "tools", "test-*.py")))
    if not test_files:
        print("[test] FAIL: no tools/test-*.py files found")
        return 1
    passed = 0
    failed = []
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for path in test_files:
        rel = _rel(path)
        print(f"[test] === {rel} ===")
        proc = subprocess.run([sys.executable, "-B", rel], cwd=ROOT, env=env)
        if proc.returncode == 0:
            passed += 1
        else:
            failed.append(rel)
    total = len(test_files)
    print(f"[test] summary: {passed}/{total} passed, {len(failed)} failed")
    if failed:
        for rel in failed:
            print(f"[test] FAIL: {rel}")
        return 1
    print("[test] PASS")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run offline lint and tests.")
    parser.add_argument("--lint", action="store_true", help="Run shellcheck, xmllint, and py_compile")
    parser.add_argument("--test", action="store_true", help="Run all tools/test-*.py suites")
    args = parser.parse_args(argv)
    run_both = not args.lint and not args.test
    rc = 0
    if args.lint or run_both:
        rc = run_lint()
        if rc != 0:
            return rc
    if args.test or run_both:
        rc = run_test()
    return rc


if __name__ == "__main__":
    sys.exit(main())
