#!/usr/bin/env python3
"""Offline test of tools/smoke-accounts.sh (no device): python3 tools/test-smoke-accounts.py

The script runs from a temporary clone, with `ssh`, `scp` and `curl` replaced by stubs on PATH. The
stubs are this file run as `--stub NAME`: a fake device made of a temp directory (the files it has,
the sign-in state dir, a fake add-on that publishes a code and obeys a cancel), the real lease helper
and the real panel_accounts module answering the API."""
import sys

sys.dont_write_bytecode = True  # before any import

import json  # noqa: E402
import os  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
HELPER = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "media-stick-lease")
SCRIPT = os.path.join(ROOT, "tools", "smoke-accounts.sh")
STUB = os.path.abspath(__file__)
T0 = 1_800_000_000
A, B = "alpha [local_aaa]", "beta [local_bbb]"
SECRET = "ya29.SECRET-ACCESS|1//SECRET-REFRESH|SECRET-VR"
CODE = "ABCD-EFGH"

# what the script compares: repository path -> path on the device (written out here on purpose)
KA = "/home/media/.kodi/addons"
DEPLOYED = {
    "device/files/usr/local/lib/media-stick/mediastick_signin.py": "/usr/local/lib/media-stick/mediastick_signin.py",
    "device/files/usr/local/lib/media-stick/mediastick_signin_guide.py": "/usr/local/lib/media-stick/mediastick_signin_guide.py",
    "device/files/usr/local/lib/media-stick/mediastick_onboarding.py": "/usr/local/lib/media-stick/mediastick_onboarding.py",
    "device/files/usr/local/bin/panel": "/usr/local/bin/panel",
    "device/files/usr/local/lib/media-stick/panel_accounts.py": "/usr/local/lib/media-stick/panel_accounts.py",
    "device/files/usr/local/lib/media-stick/panel_accounts_ui.py": "/usr/local/lib/media-stick/panel_accounts_ui.py",
    "device/files/usr/local/lib/media-stick/mediastick_ytkeys.py": "/usr/local/lib/media-stick/mediastick_ytkeys.py",
    "device/files/usr/local/lib/media-stick/panel_ytkeys.py": "/usr/local/lib/media-stick/panel_ytkeys.py",
    "device/files/usr/local/lib/media-stick/panel_ytkeys_ui.py": "/usr/local/lib/media-stick/panel_ytkeys_ui.py",
    "device/kodi-addons/script.media-stick.home/resources/lib/accounts.py":
        KA + "/script.media-stick.home/resources/lib/accounts.py",
    "device/kodi-addons/script.media-stick.home/resources/lib/signin.py":
        KA + "/script.media-stick.home/resources/lib/signin.py",
    "device/kodi-addons/script.media-stick.home/resources/lib/ytkeys.py":
        KA + "/script.media-stick.home/resources/lib/ytkeys.py",
    "device/kodi-addons/script.media-stick.home/resources/lib/onboarding_app.py":
        KA + "/script.media-stick.home/resources/lib/onboarding_app.py",
    "device/kodi-addons/script.media-stick.home/resources/lib/onboarding_demo.py":
        KA + "/script.media-stick.home/resources/lib/onboarding_demo.py",
    "device/kodi-addons/script.media-stick.home/resources/lib/onboarding_files.py":
        KA + "/script.media-stick.home/resources/lib/onboarding_files.py",
    "device/kodi-addons/script.media-stick.home/resources/lib/onboarding_view.py":
        KA + "/script.media-stick.home/resources/lib/onboarding_view.py",
    "device/kodi-addons/script.media-stick.home/resources/skins/default/1080i/script-media-stick-onboarding.xml":
        KA + "/script.media-stick.home/resources/skins/default/1080i/script-media-stick-onboarding.xml",
    "device/skin-overlay/plugin.video.sweettv/resources/lib/sweettv.py":
        KA + "/plugin.video.sweettv/resources/lib/sweettv.py",
    "device/skin-overlay/plugin.video.youtube/resources/lib/youtube_plugin/kodion/script_actions.py":
        KA + "/plugin.video.youtube/resources/lib/youtube_plugin/kodion/script_actions.py",
    "device/skin-overlay/plugin.video.youtube/resources/lib/youtube_plugin/youtube/helper/yt_login.py":
        KA + "/plugin.video.youtube/resources/lib/youtube_plugin/youtube/helper/yt_login.py",
}
TOOLS_USED = ("common.sh", "smoke-accounts.sh", "screenshot.sh")


# ---- the stubs: `ssh`, `scp` and `curl` as the script sees them -------------------------------

def record(d, line):
    with open(os.path.join(d, "calls.log"), "a") as f:
        f.write(line.replace("\n", "\\n") + "\n")


def scenario(d):
    sc = dict(panel="active", signin_dir_ok=True, curl_exit=0, waits_after=1, ignore_cancel=False,
              body_override=None, kodi_new=[], journal_new=[], screenshot_fails=False, log_unreadable=False,
              signin_http=200, cancel_fail_first=False)
    with open(os.path.join(d, "scenario.json")) as f:
        sc.update(json.load(f))
    return sc


def load_lib(d):
    os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(d, "signin")
    os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(d, "onboarding")
    os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(d, "addon_data")
    sys.path.insert(0, LIB)
    import mediastick_signin as ms
    return ms


def sha256(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def addon_tick(d, sc, ms):
    """The fake SWEET.TV add-on, looked at each time the state is read: it publishes a code once
    `waits_after` reads have passed since the sign-in was started, and obeys a cancel unless told not to."""
    pending = os.path.join(d, "pending")
    if not os.path.exists(pending):
        return
    with open(pending) as f:
        n = int(f.read() or 0) + 1
    with open(pending, "w") as f:
        f.write(str(n))
    if ms.cancel_requested("sweettv") and not sc["ignore_cancel"]:
        ms.clear_cancel("sweettv")
        ms.publish("sweettv", "cancelled")
        os.unlink(pending)
    elif sc["waits_after"] is not None and n >= sc["waits_after"]:
        if (ms.read("sweettv") or {}).get("state") != "waiting":
            ms.publish("sweettv", "waiting", code=CODE, url="https://sweet.tv/addDevice")


def stub_ssh(d, argv):
    sc, cmd = scenario(d), argv[-1]
    stdin = sys.stdin.read() if cmd == "bash -s" else ""
    record(d, "ssh: " + cmd + (" <<< " + stdin if stdin else ""))
    if cmd.startswith("/usr/local/bin/media-stick-lease"):
        return subprocess.run([sys.executable, "-I", HELPER, *shlex.split(cmd)[1:]]).returncode
    if "sha256sum" in cmd:
        for p in cmd.split("for f in ", 1)[1].split(";", 1)[0].split():
            f = os.path.join(d, "dev") + p
            print(("%s  %s" % (sha256(f), p)) if os.path.isfile(f) else "missing  " + p)
        return 0
    if cmd.startswith("test -d"):
        return 0 if sc["signin_dir_ok"] else 1
    if cmd == "systemctl is-active panel.service":
        print(sc["panel"])
        return 0 if sc["panel"] == "active" else 3
    if "mediastick_signin" in cmd:
        ms = load_lib(d)
        addon_tick(d, sc, ms)
        print(json.dumps({n: ms.read(n) for n in ms.SERVICES}))
        return 0
    if cmd.startswith("echo $(wc -l"):
        if sc["log_unreadable"]:
            return 1
        print("100 2026-11-22 10:00:00")
        return 0
    if cmd == "bash -s":
        if sc["log_unreadable"]:
            return 1
        print("\n".join(sc["journal_new"] if "journalctl" in stdin else sc["kodi_new"]))
        return 0
    if "kodi-rpc Input.ExecuteAction" in cmd:
        if sc["screenshot_fails"]:
            return 1
        print("/run/media-stick/shots/x.png")
        return 0
    print("stub ssh: unexpected command", file=sys.stderr)
    return 99


def stub_scp(d, argv):
    record(d, "scp: " + " ".join(argv))
    with open(argv[-1], "wb") as f:
        f.write(b"\x89PNG stub")
    return 0


def stub_curl(d, argv):
    sc = scenario(d)
    headers, body, i = [], None, 0
    while i < len(argv) - 1:
        if argv[i] in ("-H", "-d", "-w", "--max-time"):
            if argv[i] == "-H":
                headers.append(argv[i + 1])
            elif argv[i] == "-d":
                body = argv[i + 1]
            i += 1
        i += 1
    url = argv[-1]
    record(d, "curl: " + json.dumps({"method": "POST" if body is not None else "GET", "url": url,
                                     "headers": headers, "body": body}))
    if sc["curl_exit"]:
        print("curl: (7) Failed to connect", file=sys.stderr)
        return sc["curl_exit"]
    ms = load_lib(d)
    import panel_accounts as pa
    path = "/" + url.split("//", 1)[1].split("/", 1)[1]
    if body is None:
        reply, code = (sc["body_override"] if sc["body_override"] is not None else json.dumps(pa.view())), 200
    elif "X-Panel: 1" not in headers:
        reply, code = "forbidden", 403
    else:
        def rpc(method, params=None, timeout=3):  # the launcher add-on, as the panel's kodi() reaches it
            if params["params"][:2] == ["accounts", "signin"] and not os.path.exists(os.path.join(d, "pending")):
                with open(os.path.join(d, "pending"), "w") as f:
                    f.write("0")
                ms.begin("sweettv")
        reply_obj, code = pa.post(path, json.loads(body), rpc)
        reply = json.dumps(reply_obj)
        if path.endswith("/signin") and sc["signin_http"] != 200:
            reply, code = "{}", sc["signin_http"]
        if path.endswith("/cancel") and sc["cancel_fail_first"]:
            with open(os.path.join(d, "calls.log")) as f:
                if f.read().count("/api/accounts/cancel") == 1:
                    reply, code = "{}", 500
                    ms.clear_cancel("sweettv")   # the refused cancel left nothing behind
    sys.stdout.write("%s\n%d" % (reply, code))
    return 0


def stub_main(name, argv):
    d = os.environ["STUB_DIR"]
    return {"ssh": stub_ssh, "scp": stub_scp, "curl": stub_curl}[name](d, argv)


# ---- the tests --------------------------------------------------------------------------------

GIT_ENV = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)


class Smoke(unittest.TestCase):
    def git(self, cwd, *args):
        subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True,
                       env=dict(os.environ, **GIT_ENV))

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        origin, self.work, self.other = (os.path.join(self.tmp, n) for n in ("origin.git", "work", "other"))
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", origin)
        self.git(self.tmp, "clone", "-q", origin, self.work)
        for rel in list(DEPLOYED) + ["tools/" + name for name in TOOLS_USED]:
            self.copy(rel)
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-q", "-m", "base")
        self.git(self.work, "push", "-q", "origin", "HEAD:main")
        self.git(self.work, "branch", "-q", "--set-upstream-to=origin/main")
        self.git(self.tmp, "clone", "-q", origin, self.other)

        self.d = os.path.join(self.tmp, "stub")           # the fake device
        self.lease_root = os.path.join(self.tmp, "run")
        self.shots = os.path.join(self.tmp, "shots")
        for rel, remote in DEPLOYED.items():             # it has every file, as deployed
            dst = os.path.join(self.d, "dev") + remote
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(self.work, rel), dst)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for name in ("ssh", "scp", "curl"):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write('#!/bin/sh\nexec "%s" "%s" --stub %s "$@"\n' % (sys.executable, STUB, name))
            os.chmod(path, 0o755)
        self.ms = load_lib(self.d)
        self.ms.DIR = os.path.join(self.d, "signin")
        self.ms.USERDATA = os.path.join(self.d, "addon_data")
        os.makedirs(self.ms.DIR)
        self.youtube = os.path.join(self.ms.USERDATA, "plugin.video.youtube")
        os.makedirs(self.youtube)
        with open(os.path.join(self.youtube, "access_manager.json"), "w") as f:
            json.dump({"access_manager": {"current_user": 0, "users": {
                "0": {"name": "Default", "refresh_token": SECRET, "access_token": "ya29.OTHER-SECRET"}}}}, f)
        self.scenario()
        self.acquire(A)

    def copy(self, rel):
        dst = os.path.join(self.work, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), dst)

    def scenario(self, **sc):
        with open(os.path.join(self.d, "scenario.json"), "w") as f:
            json.dump(sc, f)

    def env(self, **extra):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_DIR=self.d,
                   MEDIASTICK_LEASE_ROOT=self.lease_root, MEDIASTICK_NOW=str(T0), TZ="UTC", TMPDIR=self.tmp,
                   MEDIASTICK_SMOKE_POLL="0", MEDIASTICK_HOLDER=A, MEDIASTICK_HOST="10.1.2.3",
                   MEDIASTICK_KEY=os.path.join(self.tmp, "key"), PYTHONDONTWRITEBYTECODE="1", **GIT_ENV)
        for name in ("MEDIASTICK_NO_LEASE", "MEDIASTICK_NO_BASE_CHECK"):
            env.pop(name, None)
        env.update(extra)
        return {k: v for k, v in env.items() if v is not None}

    def acquire(self, holder):
        p = subprocess.run([sys.executable, "-I", HELPER, "acquire", "--for", holder, "--why", "smoke", "--ttl", "30m"],
                           env=self.env(), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def smoke(self, *args, **extra):
        p = subprocess.run([os.path.join(self.work, "tools", "smoke-accounts.sh"), *args], env=self.env(**extra),
                           capture_output=True, text=True, cwd=self.tmp)
        return p.returncode, p.stdout, p.stderr

    def calls(self):
        try:
            with open(os.path.join(self.d, "calls.log")) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def curls(self, method=None, path=None):
        out = [json.loads(c[len("curl: "):]) for c in self.calls() if c.startswith("curl: ")]
        return [c for c in out if (method is None or c["method"] == method) and (path is None or c["url"].endswith(path))]

    def states_read(self):
        return sum(1 for c in self.calls() if c.startswith("ssh: cd /usr/local/lib/media-stick && python3 -c"))

    def lines(self, out, kind):
        return [ln for ln in out.splitlines() if ln.startswith(kind + "  ")]

    def failed(self, out, text):
        return [ln for ln in self.lines(out, "FAIL") if text in ln]

    # -- the refusals --

    def test_without_a_lease_it_says_what_it_would_do_then_refuses_and_touches_nothing(self):
        rc, out, err = self.smoke(MEDIASTICK_HOLDER=B)
        self.assertEqual(rc, 3, err)
        self.assertIn("refused", err)
        self.assertIn("smoke test of the accounts feature", out)
        self.assertIn("read-only:", out)
        self.assertEqual(self.lines(out, "FAIL"), [])
        self.assertEqual(self.curls(), [])
        rc, out, err = self.smoke("--live", MEDIASTICK_HOLDER=None)  # no holder named while A has it
        self.assertEqual(rc, 3, err)
        self.assertIn(A, err)
        self.assertEqual(self.curls(), [])
        subprocess.run([sys.executable, "-I", HELPER, "release", "--for", A], env=self.env(), check=True, capture_output=True)
        rc, out, err = self.smoke("--live", MEDIASTICK_HOLDER=None)  # nobody has it
        self.assertEqual(rc, 3, err)
        self.assertIn("hold no device lease", err)
        self.assertEqual(self.curls(), [])

    def test_a_tree_behind_origin_main_is_refused(self):
        self.git(self.other, "pull", "-q", "origin", "main")
        with open(os.path.join(self.other, "theirs"), "w") as f:
            f.write("x")
        self.git(self.other, "add", "theirs")
        self.git(self.other, "commit", "-q", "-m", "theirs")
        self.git(self.other, "push", "-q", "origin", "HEAD:main")
        rc, out, err = self.smoke("--live")
        self.assertEqual(rc, 4, err)
        self.assertIn("rebase/merge first", err)
        self.assertEqual(self.curls(), [])

    def test_bad_usage_is_2(self):
        for args in (("--bogus",), ("--shots",), ("live",)):
            self.assertEqual(self.smoke(*args)[0], 2, args)

    def test_the_plan_comes_before_any_result(self):
        rc, out, err = self.smoke()
        self.assertEqual(rc, 0, out + err)
        self.assertLess(out.index("read-only:"), out.index("PASS"))
        self.assertIn("no --live: nothing is started on the TV", out)

    # -- checks 0-1 --

    def test_default_run_is_read_only_and_everything_passes(self):
        rc, out, err = self.smoke()
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.lines(out, "FAIL"), [])
        passes = self.lines(out, "PASS")
        self.assertEqual(len(passes), 2 + len(DEPLOYED) + 4, out)  # tree, lease, the files, dir, panel, api x2
        for rel in DEPLOYED.values():
            self.assertTrue(any(rel in ln for ln in passes), rel)
        self.assertIn("summary: %d passed, 0 failed" % len(passes), out)
        self.assertEqual([c["method"] for c in self.curls()], ["GET"])
        self.assertEqual(self.curls()[0]["url"], "http://10.1.2.3/api/accounts")
        self.assertIn("X-Panel: 1", self.curls()[0]["headers"])
        self.assertEqual(self.states_read(), 0)
        self.assertFalse([c for c in self.calls() if "kodi-rpc" in c or "journalctl" in c])
        self.assertFalse(os.path.exists(self.shots))
        self.assertNotIn(SECRET, out + err)
        self.assertNotIn("SECRET", out + err)

    def test_the_real_api_answer_has_a_token_count_and_that_is_allowed(self):
        import panel_accounts
        profile = panel_accounts.view()["accounts"][0]["profiles"][0]
        self.assertEqual(profile["tokens"], 3)  # the real answer has the key, as a count
        rc, out, err = self.smoke()
        self.assertEqual(rc, 0, out + err)
        self.assertIn("api: no token in the body", out)

    def test_a_file_that_differs_or_is_missing_on_the_device_fails_by_name(self):
        rel, remote = "device/files/usr/local/bin/panel", "/usr/local/bin/panel"
        with open(os.path.join(self.d, "dev") + remote, "a") as f:
            f.write("hand edit")
        os.unlink(os.path.join(self.d, "dev") + DEPLOYED["device/kodi-addons/script.media-stick.home/resources/lib/signin.py"])
        rc, out, _ = self.smoke()
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.lines(out, "FAIL")), 2, out)
        self.assertTrue(self.failed(out, "%s differs from %s" % (remote, rel)))
        self.assertTrue(self.failed(out, "script.media-stick.home/resources/lib/signin.py is not on the device"))
        self.assertIn("summary: %d passed, 2 failed" % (2 + len(DEPLOYED) + 4 - 2), out)

    def test_signin_dir_missing_and_panel_down_fail(self):
        self.scenario(signin_dir_ok=False, panel="inactive")
        rc, out, _ = self.smoke()
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "dir: /run/media-stick/signin"))
        self.assertTrue(self.failed(out, "panel: panel.service is inactive"))

    def test_api_unreachable_fails_and_live_does_not_start(self):
        self.scenario(curl_exit=7)
        rc, out, _ = self.smoke("--live")
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "api: GET http://10.1.2.3/api/accounts answered HTTP 000"))
        self.assertTrue(self.failed(out, "live: not started"))
        self.assertEqual(self.states_read(), 0)

    def test_a_leaking_body_fails_and_the_leak_is_not_printed(self):
        bodies = {
            "refresh_token": {"accounts": [{"service": "youtube", "refresh_token": "LEAK-ONE"}], "waiting": []},
            "key /accounts/0/api_key": {"accounts": [{"api_key": "LEAK-ONE"}]},
            "key /accounts/0/profiles/0/tokens": {"accounts": [{"profiles": [{"tokens": "LEAK-ONE"}]}]},
            "token-like value": {"accounts": [{"note": "ya29.LEAK-ONE"}]},
            "Bearer": {"accounts": [{"note": "Bearer LEAK-ONE"}]},
            "key /accounts/0/Authorization": {"accounts": [{"Authorization": "LEAK-ONE"}]},
        }
        for label, body in bodies.items():
            self.scenario(body_override=json.dumps(body))
            rc, out, err = self.smoke()
            self.assertEqual(rc, 1, label)
            self.assertTrue(self.failed(out, "api: the body leaks"), label)
            self.assertIn(label, out)
            self.assertNotIn("LEAK-ONE", out + err)

    def test_not_json_fails(self):
        self.scenario(body_override="<html>captive portal</html>")
        rc, out, _ = self.smoke()
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "not the expected JSON"))

    def test_host_override_is_used_for_ssh_curl_and_url(self):
        rc, out, _ = self.smoke(MEDIASTICK_HOST="192.168.2.2")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.curls()[0]["url"], "http://192.168.2.2/api/accounts")
        self.assertIn("on 192.168.2.2", out)

    def test_owner_bypasses_are_loud_and_still_checked(self):
        rc, out, err = self.smoke(MEDIASTICK_HOLDER=B, MEDIASTICK_NO_LEASE="1", MEDIASTICK_NO_BASE_CHECK="1")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("WITHOUT the lease", err)
        self.assertIn("NO_BASE_CHECK", err)
        self.assertIn("lease: bypassed", out)

    # -- --live --

    def test_live_starts_shows_cancels_and_checks_everything(self):
        rc, out, err = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.lines(out, "FAIL"), [])
        posts = self.curls("POST")
        self.assertEqual([(p["url"].rsplit("/", 1)[1], p["body"]) for p in posts],
                         [("signin", '{"service": "sweettv"}'), ("cancel", '{"service": "sweettv"}')])
        for p in posts:
            self.assertIn("X-Panel: 1", p["headers"])
            self.assertTrue(p["url"].startswith("http://10.1.2.3/api/accounts/"))
        shot = os.path.join(self.shots, "accounts-sweettv-code.png")
        self.assertTrue(os.path.isfile(shot))
        self.assertIn(shot, out)  # the path is printed
        for text in ("state waiting with a code of 9 characters", "TV screenshot saved", "accounts/cancel accepted",
                     "state is cancelled", "no sign-in is waiting any more", "no new [script.media-stick.home]"):
            self.assertIn(text, out)
        self.assertNotIn(CODE, out + err)  # the code is not printed
        self.assertNotIn("SECRET", out + err)
        self.assertEqual(self.ms.active(), [])
        self.assertNotIn("cleanup:", out)  # the cancel was sent in the flow, the trap had nothing to do

    def test_live_default_screenshot_dir_is_made_and_printed(self):
        rc, out, _ = self.smoke("--live")
        self.assertEqual(rc, 0, out)
        self.assertIn("a screenshot to %s/smoke-accounts." % self.tmp, out.split("PASS")[0])
        line = [ln for ln in out.splitlines() if "TV screenshot saved" in ln][0]
        self.assertTrue(os.path.isfile(line.split("saved: ")[1].split(" ")[0]))

    def test_live_waits_for_the_code_but_not_for_ever_and_still_cancels(self):
        self.scenario(waits_after=None)
        rc, out, _ = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "no waiting state with a code"))
        self.assertTrue(os.path.isfile(os.path.join(self.shots, "accounts-sweettv-code.png")))  # taken anyway, to look at
        self.assertEqual([p["url"].rsplit("/", 1)[1] for p in self.curls("POST")], ["signin", "cancel"])
        self.assertLessEqual(self.states_read(), 1 + 20 + 10 + 1)
        self.assertEqual(self.ms.active(), [])

    def test_live_code_arriving_late_is_seen(self):
        self.scenario(waits_after=7)
        rc, out, _ = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 0, out)

    def test_live_a_cancel_the_addon_ignores_fails(self):
        self.scenario(ignore_cancel=True)
        rc, out, _ = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "state is waiting, not cancelled"))
        self.assertTrue(self.failed(out, "still waiting: sweettv"))
        self.assertLessEqual(self.states_read(), 1 + 2 + 10 + 1)

    def test_live_a_cancel_the_panel_refused_is_sent_again_from_the_trap(self):
        self.scenario(cancel_fail_first=True)
        rc, out, _ = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "POST /api/accounts/cancel answered HTTP 500"))
        self.assertIn("cleanup: cancelling the sweettv sign-in", out)
        self.assertEqual([p["url"].rsplit("/", 1)[1] for p in self.curls("POST")], ["signin", "cancel", "cancel"])

    def test_live_a_failed_screenshot_is_a_failure_and_the_cancel_still_happens(self):
        self.scenario(screenshot_fails=True)
        rc, out, _ = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "TV screenshot failed"))
        self.assertIn("state is cancelled", out)

    def test_live_refused_signin_is_a_failure_and_the_trap_cancels_anyway(self):
        self.scenario(signin_http=500)
        rc, out, _ = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "signin answered HTTP 500"))
        self.assertEqual([p["url"].rsplit("/", 1)[1] for p in self.curls("POST")], ["signin", "cancel"])

    def test_live_leaves_a_sign_in_that_is_already_waiting_alone(self):
        self.ms.publish("sweettv", "waiting", code="MINE-1234", url="https://sweet.tv/addDevice")
        rc, out, _ = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "already waiting (sweettv)"))
        self.assertEqual(self.curls("POST"), [])
        self.assertEqual([s["service"] for s in self.ms.active()], ["sweettv"])

    def test_live_log_lines_and_a_traceback_fail_and_are_printed_without_tokens(self):
        self.scenario(kodi_new=["2026 warning <general>: [script.media-stick.home] accounts signin sweettv failed: boom",
                                "Traceback (most recent call last):", "  File x.py, line 1", "ValueError: refresh_token=" + SECRET],
                      journal_new=["kodi[1]: Traceback (most recent call last):"])
        rc, out, err = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "the log has new [script.media-stick.home] or Traceback lines"))
        for text in ("accounts signin sweettv failed: boom", "ValueError: refresh_token ***", "journalctl -u kodi"):
            self.assertIn(text, out)
        self.assertNotIn("SECRET", out + err)
        self.assertEqual(self.curls("POST")[-1]["url"].rsplit("/", 1)[1], "cancel")

    def test_live_unreadable_log_is_a_failure(self):
        self.scenario(log_unreadable=True)
        rc, out, _ = self.smoke("--live", "--shots", self.shots)
        self.assertEqual(rc, 1)
        self.assertTrue(self.failed(out, "cannot read where the Kodi log stands"))

    def test_the_log_is_read_from_the_mark_taken_before_the_start(self):
        self.smoke("--live", "--shots", self.shots)
        reads = [c for c in self.calls() if "<<<" in c]
        self.assertTrue(any("n=100" in c and ".kodi/temp/kodi.log" in c and "script\\.media-stick\\.home" in c for c in reads), reads)
        self.assertTrue(any("journalctl -u kodi --since '2026-11-22 10:00:00'" in c for c in reads), reads)

    def test_an_interrupt_during_the_wait_still_cancels(self):
        self.scenario(waits_after=None)
        p = subprocess.Popen([os.path.join(self.work, "tools", "smoke-accounts.sh"), "--live", "--shots", self.shots],
                             env=self.env(MEDIASTICK_SMOKE_POLL="1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, cwd=self.tmp)
        self.addCleanup(p.kill)
        end = time.time() + 20
        while not self.curls("POST", "/signin") and time.time() < end:
            time.sleep(0.1)
        time.sleep(0.5)
        p.send_signal(signal.SIGTERM)
        out, _ = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 130)
        self.assertIn("cleanup: cancelling", out)
        self.assertEqual([c["url"].rsplit("/", 1)[1] for c in self.curls("POST")], ["signin", "cancel"])

    # -- the script itself --

    def test_script_parses_passes_shellcheck_and_is_executable(self):
        self.assertEqual(subprocess.run(["bash", "-n", SCRIPT], capture_output=True).returncode, 0)
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        if shutil.which("shellcheck"):
            p = subprocess.run(["shellcheck", "-x", "-P", os.path.dirname(SCRIPT), SCRIPT], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout)

    def test_every_deployed_file_the_script_lists_is_in_the_repository_and_compared(self):
        with open(SCRIPT) as f:
            text = f.read()
        for rel in DEPLOYED:
            self.assertIn(rel, text)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), rel)
        self.assertEqual(len(DEPLOYED), 20)  # a file added to the script is added here too


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--stub":
        sys.exit(stub_main(sys.argv[2], sys.argv[3:]))
    unittest.main(verbosity=1)
