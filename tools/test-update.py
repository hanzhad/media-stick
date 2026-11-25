#!/usr/bin/env python3
"""Offline tests for media-stick-healthcheck (Pure Core + Thin I/O Shell) and
media-stick-update (bad-commit skip guard, airplay/miracast pause guards,
post-update healthcheck gate, rollback logging, and env overrides).

Run: python3 tools/test-update.py
"""
import sys

sys.dont_write_bytecode = True  # before any import

import http.server  # noqa: E402
import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import socketserver  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HEALTHCHECK = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "media-stick-healthcheck")
UPDATE = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "media-stick-update")

CUR_SHA = "aaaaaaa111111111111111111111111111111111"
NEW_SHA = "bbbbbbb222222222222222222222222222222222"
OTHER_SHA = "ccccccc333333333333333333333333333333333"


def load_healthcheck(testcase):
    testcase.assertTrue(os.path.exists(HEALTHCHECK), f"missing {HEALTHCHECK}")
    loader = importlib.machinery.SourceFileLoader("media_stick_healthcheck", HEALTHCHECK)
    spec = importlib.util.spec_from_loader("media_stick_healthcheck", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class _PanelHandler(http.server.BaseHTTPRequestHandler):
    """Configurable local /api/status handler for Thin I/O Shell tests."""

    def do_GET(self):
        if self.path != "/api/status":
            self.send_response(404)
            self.end_headers()
            return
        codes = self.server.status_sequence
        code = codes.pop(0) if len(codes) > 1 else codes[0]
        self.server.requests += 1
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": code == 200}).encode("utf-8"))

    def log_message(self, format, *args):
        pass


class _ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


# --- Pure Core: media-stick-healthcheck ---------------------------------------------------------


class TestHealthcheckCore(unittest.TestCase):
    """Pure Core logic in media-stick-healthcheck (zero I/O)."""

    def setUp(self):
        self.hc = load_healthcheck(self)

    def test_detect_screen_owner_truth_table(self):
        for airplay in (False, True):
            for miracast in (False, True):
                for webapp in (False, True):
                    with self.subTest(airplay=airplay, miracast=miracast, webapp=webapp):
                        owner = self.hc.detect_screen_owner(airplay, miracast, webapp)
                        if not (airplay or miracast or webapp):
                            self.assertEqual(owner, "")
                        elif airplay and not miracast and not webapp:
                            self.assertEqual(owner, "airplay")
                        elif miracast and not airplay and not webapp:
                            self.assertEqual(owner, "miracast")
                        elif webapp and not airplay and not miracast:
                            self.assertEqual(owner, "web-app")
                        else:
                            self.assertIn(owner, ("airplay", "miracast", "web-app"))

    def test_evaluate_health_passes_when_kodi_active_and_all_checks_ok(self):
        ok, reasons = self.hc.evaluate_health([], 200, "", True, True)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_evaluate_health_fails_on_any_failed_unit(self):
        for units in (
            ["kodi.service"],
            ["panel.service"],
            ["airplay.service"],
            ["miracast.service"],
            ["kodi.service", "panel.service"],
        ):
            with self.subTest(units=units):
                ok, reasons = self.hc.evaluate_health(units, 200, "", True, True)
                self.assertFalse(ok)
                self.assertTrue(reasons)
                joined = " ".join(reasons)
                for u in units:
                    self.assertIn(u, joined)

    def test_evaluate_health_panel_status_boundaries(self):
        ok_200, reasons_200 = self.hc.evaluate_health([], 200, "", True, True)
        self.assertTrue(ok_200)
        self.assertEqual(reasons_200, [])

        for bad_code in (None, 0, 204, 301, 404, 500, 502, 503):
            with self.subTest(code=bad_code):
                ok, reasons = self.hc.evaluate_health([], bad_code, "", True, True)
                self.assertFalse(ok)
                self.assertTrue(reasons)

    def test_evaluate_health_kodi_checks_enforced_when_no_screen_owner(self):
        for ping_ok, launcher_ok in ((False, True), (True, False), (False, False)):
            with self.subTest(ping_ok=ping_ok, launcher_ok=launcher_ok):
                ok, reasons = self.hc.evaluate_health([], 200, "", ping_ok, launcher_ok)
                self.assertFalse(ok)
                self.assertTrue(reasons)

    def test_evaluate_health_skips_kodi_checks_when_screen_owner_active(self):
        for owner in ("airplay", "miracast", "web-app"):
            for ping_ok in (False, True):
                for launcher_ok in (False, True):
                    with self.subTest(owner=owner, ping_ok=ping_ok, launcher_ok=launcher_ok):
                        ok, reasons = self.hc.evaluate_health(
                            [], 200, owner, ping_ok, launcher_ok
                        )
                        self.assertTrue(ok, reasons)
                        self.assertEqual(reasons, [])

            # Still fails if panel is down or a managed unit failed
            ok_panel, _ = self.hc.evaluate_health([], 503, owner, True, True)
            self.assertFalse(ok_panel)
            ok_unit, _ = self.hc.evaluate_health(["panel.service"], 200, owner, True, True)
            self.assertFalse(ok_unit)


# --- Thin I/O Shell: media-stick-healthcheck ----------------------------------------------------


class TestHealthcheckShell(unittest.TestCase):
    """Thin I/O Shell for media-stick-healthcheck with local HTTP server and stub binaries."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir, exist_ok=True)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin, exist_ok=True)
        self.kodi_log = os.path.join(self.tmp, "kodi-rpc.log")

        self.systemctl_bin = os.path.join(self.bin, "systemctl")
        self._write_exec(
            self.systemctl_bin,
            """#!/bin/bash
if [ "${1:-}" = "is-active" ]; then
  [ "${STUB_WEBAPP_ACTIVE:-0}" = "1" ] && exit 0
  exit 3
fi
if [ "${1:-}" = "is-failed" ]; then
  shift
  failed=0
  for arg in "$@"; do
    case "$arg" in
      -q|--quiet) continue ;;
    esac
    case " ${STUB_FAILED_UNITS:-} " in
      *" $arg "*) echo "failed"; failed=1 ;;
      *) echo "active" ;;
    esac
  done
  [ "$failed" -eq 1 ] && exit 0
  exit 1
fi
if [ "${1:-}" = "list-units" ]; then
  for u in ${STUB_FAILED_UNITS:-}; do
    echo "$u loaded failed failed $u"
  done
  exit 0
fi
if [ "${1:-}" = "show" ]; then
  unit="${@: -1}"
  case " ${STUB_FAILED_UNITS:-} " in
    *" $unit "*) echo "failed" ;;
    *) echo "active" ;;
  esac
  exit 0
fi
exit 0
""",
        )

        self.kodi_rpc_bin = os.path.join(self.bin, "kodi-rpc")
        self._write_exec(
            self.kodi_rpc_bin,
            """#!/bin/bash
echo "$*" >> "$STUB_KODI_LOG"
case "$*" in
  *JSONRPC.Ping*)
    if [ "${STUB_KODI_PING_OK:-1}" = "1" ]; then
      echo '"pong"'
      exit 0
    fi
    echo 'error'
    exit 1
    ;;
  *Addons.GetAddonDetails*)
    if [ "${STUB_LAUNCHER_ENABLED:-1}" = "1" ]; then
      echo '{"addon":{"addonid":"script.media-stick.home","enabled":true}}'
    else
      echo '{"addon":{"addonid":"script.media-stick.home","enabled":false}}'
    fi
    exit 0
    ;;
esac
exit 1
""",
        )

        self.server = _ReusableTCPServer(("127.0.0.1", 0), _PanelHandler)
        self.server.status_sequence = [200]
        self.server.requests = 0
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()

    def _write_exec(self, path, content):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(path, 0o755)

    def run_hc(self, **env_extra):
        self.assertTrue(os.path.exists(HEALTHCHECK), f"missing {HEALTHCHECK}")
        env = dict(
            os.environ,
            PANEL_PORT=str(self.port),
            PANEL_URL=f"http://127.0.0.1:{self.port}/api/status",
            RUN_DIR=self.run_dir,
            HEALTH_TIMEOUT_S="1.0",
            HEALTH_INTERVAL_S="0.05",
            SYSTEMCTL_BIN=self.systemctl_bin,
            KODI_RPC_BIN=self.kodi_rpc_bin,
            STUB_KODI_LOG=self.kodi_log,
            STUB_FAILED_UNITS="",
            STUB_WEBAPP_ACTIVE="0",
            STUB_KODI_PING_OK="1",
            STUB_LAUNCHER_ENABLED="1",
        )
        env.update(env_extra)
        p = subprocess.run(
            [sys.executable, HEALTHCHECK],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return p.returncode, p.stdout, p.stderr

    def test_healthcheck_passes_with_ok_diagnostics_when_all_healthy(self):
        rc, out, err = self.run_hc()
        self.assertEqual(rc, 0, out + err)
        self.assertIn("OK", out)
        self.assertNotIn("FAIL", out)

    def test_healthcheck_fails_when_managed_unit_is_failed(self):
        rc, out, err = self.run_hc(STUB_FAILED_UNITS="panel.service")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("FAIL", out + err)
        self.assertIn("panel.service", out + err)

    def test_healthcheck_retries_panel_until_200_within_timeout(self):
        self.server.status_sequence = [503, 503, 200]
        rc, out, err = self.run_hc(HEALTH_TIMEOUT_S="2.0", HEALTH_INTERVAL_S="0.05")
        self.assertEqual(rc, 0, out + err)
        self.assertGreaterEqual(self.server.requests, 3)

    def test_healthcheck_fails_when_panel_never_returns_200(self):
        self.server.status_sequence = [503]
        rc, out, err = self.run_hc(HEALTH_TIMEOUT_S="0.2", HEALTH_INTERVAL_S="0.05")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("FAIL", out + err)

    def test_healthcheck_fails_when_kodi_ping_or_launcher_disabled(self):
        rc_ping, out_ping, err_ping = self.run_hc(
            STUB_KODI_PING_OK="0", HEALTH_TIMEOUT_S="0.2", HEALTH_INTERVAL_S="0.05"
        )
        self.assertEqual(rc_ping, 1, out_ping + err_ping)
        self.assertIn("FAIL", out_ping + err_ping)

        rc_addon, out_addon, err_addon = self.run_hc(
            STUB_LAUNCHER_ENABLED="0", HEALTH_TIMEOUT_S="0.2", HEALTH_INTERVAL_S="0.05"
        )
        self.assertEqual(rc_addon, 1, out_addon + err_addon)
        self.assertIn("FAIL", out_addon + err_addon)

    def test_healthcheck_skips_kodi_rpc_when_screen_owner_active(self):
        for case in ("airplay", "miracast", "web-app"):
            with self.subTest(owner=case):
                for flag in ("airplay", "miracast"):
                    p = os.path.join(self.run_dir, flag)
                    if os.path.exists(p):
                        os.unlink(p)
                if os.path.exists(self.kodi_log):
                    os.unlink(self.kodi_log)

                extra = {
                    "STUB_KODI_PING_OK": "0",
                    "STUB_LAUNCHER_ENABLED": "0",
                    "STUB_WEBAPP_ACTIVE": "1" if case == "web-app" else "0",
                }
                if case in ("airplay", "miracast"):
                    with open(os.path.join(self.run_dir, case), "w", encoding="utf-8") as f:
                        f.write("1")

                rc, out, err = self.run_hc(**extra)
                self.assertEqual(rc, 0, out + err)
                self.assertFalse(
                    os.path.exists(self.kodi_log),
                    f"kodi-rpc should be skipped when {case} owns the screen",
                )

    def test_healthcheck_fails_with_screen_owner_if_panel_down_or_unit_failed(self):
        with open(os.path.join(self.run_dir, "airplay"), "w", encoding="utf-8") as f:
            f.write("1")
        self.server.status_sequence = [503]
        rc, out, err = self.run_hc(HEALTH_TIMEOUT_S="0.2", HEALTH_INTERVAL_S="0.05")
        self.assertEqual(rc, 1, out + err)

        self.server.status_sequence = [200]
        rc_unit, out_unit, err_unit = self.run_hc(STUB_FAILED_UNITS="airplay.service")
        self.assertEqual(rc_unit, 1, out_unit + err_unit)


# --- media-stick-update -------------------------------------------------------------------------


class TestMediaStickUpdate(unittest.TestCase):
    """Subprocess tests for media-stick-update using its env overrides (no file patching)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

        self.repo = os.path.join(self.tmp, "repo")
        self.state_dir = os.path.join(self.tmp, "state")
        self.run_dir = os.path.join(self.tmp, "run")
        self.lock_file = os.path.join(self.tmp, "update.lock")
        self.bin = os.path.join(self.tmp, "bin")
        self.log = os.path.join(self.tmp, "calls.log")

        for d in (os.path.join(self.repo, "device"), self.state_dir, self.run_dir, self.bin):
            os.makedirs(d, exist_ok=True)

        self.git_wrapper = os.path.join(self.bin, "git-user-wrapper")
        self._write_exec(
            self.git_wrapper,
            """#!/bin/bash
if [ "${1:-}" = "git" ]; then shift; fi
exec git "$@"
""",
        )

        self._write_exec(
            os.path.join(self.bin, "git"),
            f"""#!/bin/bash
echo "git $*" >> "$STUB_LOG"
case "$*" in
  *"rev-parse HEAD"*) echo "{CUR_SHA}" ;;
  *"rev-parse origin/main"*) echo "{NEW_SHA}" ;;
  *" log "*) echo "feat: test subject" ;;
esac
exit 0
""",
        )

        self.kodi_rpc_bin = os.path.join(self.bin, "kodi-rpc")
        self._write_exec(self.kodi_rpc_bin, "#!/bin/bash\necho '[]'\n")

        self.systemctl_bin = os.path.join(self.bin, "systemctl")
        self._write_exec(
            self.systemctl_bin,
            '#!/bin/bash\necho "systemctl $*" >> "$STUB_LOG"\nexit 1\n',
        )

        self.lease_bin = os.path.join(self.bin, "media-stick-lease")
        self._write_exec(self.lease_bin, "#!/bin/bash\nexit 0\n")

        self.signin_bin = os.path.join(self.tmp, "mediastick_signin.py")
        with open(self.signin_bin, "w", encoding="utf-8") as f:
            f.write("import sys; sys.exit(0)\n")

        self.healthcheck_bin = os.path.join(self.bin, "media-stick-healthcheck")
        self._write_exec(
            self.healthcheck_bin,
            """#!/bin/bash
echo "healthcheck" >> "$STUB_LOG"
if [ "${STUB_HEALTHCHECK_RC:-0}" -ne 0 ]; then
  echo "FAIL: healthcheck stub failed"
  exit "${STUB_HEALTHCHECK_RC}"
fi
echo "OK: healthcheck stub passed"
exit 0
""",
        )

        self.bootstrap_bin = os.path.join(self.repo, "device", "bootstrap.sh")
        self._write_exec(
            self.bootstrap_bin,
            """#!/bin/bash
echo "bootstrap" >> "$STUB_LOG"
if [ "${STUB_BOOTSTRAP_FAIL:-0}" = "1" ] && [ ! -f "$STUB_LOG.rolled" ]; then
  touch "$STUB_LOG.rolled"
  echo "[bootstrap] broken step"
  exit 1
fi
if [ -f "$STUB_LOG.rolled" ] || [ "${STUB_HEALTHCHECK_RC:-0}" != "0" ]; then
  echo "[bootstrap] rollback-output-marker"
fi
echo "[bootstrap] done"
exit 0
""",
        )

    def _write_exec(self, path, content):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(path, 0o755)

    def run_update(self, *args, **env_extra):
        env = dict(
            os.environ,
            PATH=self.bin + os.pathsep + os.environ["PATH"],
            REPO=self.repo,
            STATE_DIR=self.state_dir,
            RUN_DIR=self.run_dir,
            LOCK_FILE=self.lock_file,
            HEALTHCHECK_BIN=self.healthcheck_bin,
            KODI_RPC_BIN=self.kodi_rpc_bin,
            LEASE_BIN=self.lease_bin,
            SIGNIN_BIN=self.signin_bin,
            SYSTEMCTL_BIN=self.systemctl_bin,
            GIT_USER_WRAPPER=self.git_wrapper,
            STUB_LOG=self.log,
            STUB_HEALTHCHECK_RC="0",
            STUB_BOOTSTRAP_FAIL="0",
        )
        env.update(env_extra)
        p = subprocess.run(
            ["bash", UPDATE, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return p.returncode, p.stdout, p.stderr

    def calls(self):
        if not os.path.exists(self.log):
            return ""
        with open(self.log, encoding="utf-8") as f:
            return f.read()

    def bad_commit_path(self):
        return os.path.join(self.state_dir, "bad-commit")

    def test_env_overrides_work_without_touching_system_paths(self):
        rc, out, err = self.run_update()
        self.assertEqual(rc, 0, out + err)
        self.assertIn(f"updated to {NEW_SHA[:7]}", out)
        self.assertIn("bootstrap", self.calls())
        self.assertIn("healthcheck", self.calls())

    def test_bad_commit_skip_guard_skips_matching_commit_and_force_overrides(self):
        with open(self.bad_commit_path(), "w", encoding="utf-8") as f:
            f.write(f"  {NEW_SHA}  \n")

        rc, out, err = self.run_update()
        self.assertEqual(rc, 0, out + err)
        self.assertIn(f"skipping known bad commit {NEW_SHA[:7]}", out)
        self.assertNotIn("bootstrap", self.calls())
        self.assertNotIn("reset", self.calls())

        # --force overrides the skip and cleans bad-commit on pass
        rc_force, out_force, err_force = self.run_update("--force")
        self.assertEqual(rc_force, 0, out_force + err_force)
        self.assertIn("bootstrap", self.calls())
        self.assertFalse(os.path.exists(self.bad_commit_path()))

    def test_bad_commit_with_different_sha_does_not_skip(self):
        with open(self.bad_commit_path(), "w", encoding="utf-8") as f:
            f.write(OTHER_SHA + "\n")

        rc, out, err = self.run_update()
        self.assertEqual(rc, 0, out + err)
        self.assertIn(f"updated to {NEW_SHA[:7]}", out)
        self.assertFalse(os.path.exists(self.bad_commit_path()))

    def test_airplay_and_miracast_flags_postpone_update_unless_force(self):
        for flag in ("airplay", "miracast"):
            with self.subTest(flag=flag):
                if os.path.exists(self.log):
                    os.unlink(self.log)
                flag_path = os.path.join(self.run_dir, flag)
                with open(flag_path, "w", encoding="utf-8") as f:
                    f.write("1")

                rc, out, err = self.run_update()
                self.assertEqual(rc, 0, out + err)
                self.assertIn(f"update to {NEW_SHA[:7]} postponed", out)
                self.assertIn(flag, out.lower())
                self.assertNotIn("bootstrap", self.calls())
                self.assertNotIn("reset", self.calls())

                rc_force, out_force, err_force = self.run_update("--force")
                self.assertEqual(rc_force, 0, out_force + err_force)
                self.assertIn("bootstrap", self.calls())
                os.unlink(flag_path)

    def test_healthcheck_failure_after_bootstrap_triggers_rollback_and_records_bad_commit(self):
        rc, out, err = self.run_update(STUB_HEALTHCHECK_RC="1")
        self.assertEqual(rc, 1, out + err)
        calls = self.calls()
        self.assertIn(f"reset -q --hard {NEW_SHA}", calls)
        self.assertIn(f"reset -q --hard {CUR_SHA}", calls)
        self.assertLess(
            calls.index(f"reset -q --hard {NEW_SHA}"),
            calls.index(f"reset -q --hard {CUR_SHA}"),
        )
        self.assertEqual(calls.count("bootstrap"), 2)
        self.assertIn("rollback-output-marker", out + err)
        self.assertTrue(os.path.exists(self.bad_commit_path()))
        with open(self.bad_commit_path(), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), NEW_SHA)

    def test_bootstrap_failure_rollback_logs_output_and_records_bad_commit(self):
        rc, out, err = self.run_update(STUB_BOOTSTRAP_FAIL="1")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("rollback-output-marker", out + err)
        self.assertIn(f"reset -q --hard {CUR_SHA}", self.calls())
        self.assertTrue(os.path.exists(self.bad_commit_path()))
        with open(self.bad_commit_path(), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), NEW_SHA)

    def test_clean_update_removes_stale_bad_commit_and_exits_0(self):
        with open(self.bad_commit_path(), "w", encoding="utf-8") as f:
            f.write(OTHER_SHA + "\n")

        rc, out, err = self.run_update()
        self.assertEqual(rc, 0, out + err)
        self.assertFalse(os.path.exists(self.bad_commit_path()))

    def test_update_passes_bash_syntax_and_shellcheck(self):
        p_bash = subprocess.run(["bash", "-n", UPDATE], capture_output=True, text=True)
        self.assertEqual(p_bash.returncode, 0, p_bash.stderr)
        if shutil.which("shellcheck"):
            p_sc = subprocess.run(
                ["shellcheck", "-S", "error", UPDATE],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_sc.returncode, 0, p_sc.stdout + p_sc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
