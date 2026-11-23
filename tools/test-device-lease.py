#!/usr/bin/env python3
"""Offline test of the device lease: the helper on the device, the lease checks in tools/*.sh and
`deploy.sh --only` (no ssh, no device; ssh and rsync are stubs or local directories):
python3 tools/test-device-lease.py"""
import sys

sys.dont_write_bytecode = True  # before any import

import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HELPER = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "media-stick-lease")
UPDATE = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "media-stick-update")
TOOLS = os.path.join(ROOT, "tools")
T0 = 1_800_000_000  # a fixed "now" for the injected clock

A, B = "alpha [local_aaa]", "beta [local_bbb]"


def load_helper():
    loader = importlib.machinery.SourceFileLoader("media_stick_lease", HELPER)
    spec = importlib.util.spec_from_loader("media_stick_lease", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "run")  # stands in for /run/media-stick
        self.state = os.path.join(self.root, "device-lease")
        self.lease_file = os.path.join(self.state, "lease.json")

    def env(self, now=None, **extra):
        env = dict(os.environ, MEDIASTICK_LEASE_ROOT=self.root, TZ="UTC")
        env.pop("MEDIASTICK_NOW", None)
        if now is not None:
            env["MEDIASTICK_NOW"] = str(now)
        env.update(extra)
        return env

    def lease(self, *args, now=None):
        p = subprocess.run([sys.executable, "-I", HELPER, *args], env=self.env(now), capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    def acquire(self, holder=A, why="testing sign-in", ttl="30m", now=T0, *more):
        return self.lease("acquire", "--for", holder, "--why", why, "--ttl", ttl, *more, now=now)

    def read(self):
        with open(self.lease_file, encoding="utf-8") as f:
            return json.load(f)


class Helper(Base):
    def test_acquire_when_free_writes_state_readable_by_all(self):
        rc, out, _ = self.acquire()
        self.assertEqual(rc, 0, out)
        lease = self.read()
        self.assertEqual((lease["holder"], lease["why"], lease["since"], lease["expires"]), (A, "testing sign-in", T0, T0 + 1800))
        self.assertIn(A, lease["text"])
        self.assertEqual(stat.S_IMODE(os.stat(self.state).st_mode), 0o755)
        self.assertEqual(os.stat(self.lease_file).st_mode & 0o044, 0o044)  # group and others can read

    def test_second_holder_is_refused_and_told_who_and_why(self):
        self.acquire(A, "testing sign-in")
        rc, out, err = self.acquire(B, "restarting kodi", now=T0 + 60)
        self.assertEqual(rc, 3)
        self.assertIn(A, err)
        self.assertIn("testing sign-in", err)
        self.assertIn("29 min left", err)
        self.assertEqual(self.read()["holder"], A)

    def test_same_holder_acquiring_again_renews_and_keeps_since(self):
        self.acquire(A, ttl="10m")
        rc, out, _ = self.acquire(A, "another reason", ttl="40m", now=T0 + 120)
        self.assertEqual(rc, 0)
        self.assertIn("renewed", out)
        lease = self.read()
        self.assertEqual((lease["since"], lease["expires"], lease["why"]), (T0, T0 + 120 + 2400, "another reason"))

    def test_eight_simultaneous_acquires_have_exactly_one_winner(self):
        procs = [subprocess.Popen([sys.executable, "-I", HELPER, "acquire", "--for", "h%d [s%d]" % (i, i), "--why", "race"],
                                  env=self.env(T0), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for i in range(8)]
        rcs = {}
        for i, p in enumerate(procs):
            p.communicate()
            rcs[i] = p.returncode
        winners = [i for i, rc in rcs.items() if rc == 0]
        self.assertEqual(len(winners), 1, rcs)
        self.assertEqual(sorted(rcs.values()), [0] + [3] * 7)
        self.assertEqual(self.read()["holder"], "h%d [s%d]" % (winners[0], winners[0]))

    def test_expired_lease_is_free_with_the_injected_clock(self):
        self.acquire(A, ttl="10m")
        self.assertEqual(self.lease("check", now=T0 + 599)[0], 3)
        self.assertEqual(self.lease("check", now=T0 + 600)[0], 0)
        rc, out, _ = self.lease("status", now=T0 + 700)
        self.assertEqual(rc, 0)
        self.assertIn("free", out)
        self.assertIn("expired", out)
        self.assertEqual(self.acquire(B, "next", now=T0 + 700)[0], 0)  # the expired one is simply replaced
        self.assertEqual(self.read()["holder"], B)

    def test_a_short_real_ttl_expires(self):
        self.assertEqual(self.lease("acquire", "--for", A, "--why", "quick", "--ttl", "1s")[0], 0)
        self.assertEqual(self.lease("check")[0], 3)
        time.sleep(2.2)
        self.assertEqual(self.lease("check")[0], 0)

    def test_ttl_units(self):
        helper = load_helper()
        for text, seconds in (("90s", 90), ("30m", 1800), ("2h", 7200), ("1h30m", 5400), ("15", 900), (" 5M ", 300)):
            self.assertEqual(helper.parse_duration(text), seconds, text)
        for bad in ("", "m", "5x", "-5m", "1.5h", "h5"):
            with self.assertRaises(ValueError, msg=bad):
                helper.parse_duration(bad)
        self.acquire(A, ttl="2h")
        self.assertEqual(self.read()["expires"], T0 + 7200)
        for bad in ("5x", "0s", "5h"):  # not a duration; zero; over the 4 h limit
            self.assertEqual(self.acquire(B, ttl=bad)[0], 2, bad)

    def test_renew_and_release_by_the_wrong_holder_are_refused_naming_the_real_one(self):
        self.acquire(A)
        for cmd in ("renew", "release"):
            rc, _, err = self.lease(cmd, "--for", B, now=T0 + 5)
            self.assertEqual(rc, 3, cmd)
            self.assertIn(A, err)
        self.assertEqual(self.read()["holder"], A)

    def test_renew_extends_but_never_shortens_and_needs_a_live_lease(self):
        self.assertEqual(self.lease("renew", "--for", A, now=T0)[0], 4)  # nothing held
        self.acquire(A, ttl="30m")
        self.lease("renew", "--for", A, "--ttl", "5m", now=T0 + 60)
        self.assertEqual(self.read()["expires"], T0 + 1800)
        self.assertEqual(self.lease("renew", "--for", A, "--ttl", "1h", now=T0 + 60)[0], 0)
        self.assertEqual(self.read()["expires"], T0 + 60 + 3600)
        self.assertEqual(self.lease("renew", "--for", A, now=T0 + 99999)[0], 4)  # expired is not held

    def test_release_frees_it_and_is_harmless_when_nothing_is_held(self):
        self.acquire(A)
        self.assertEqual(self.lease("release", "--for", A, now=T0)[0], 0)
        self.assertFalse(os.path.exists(self.lease_file))
        self.assertEqual(self.lease("check", now=T0)[0], 0)
        self.assertEqual(self.lease("release", "--for", B, now=T0)[0], 0)
        self.assertEqual(self.acquire(B)[0], 0)

    def test_check_exit_codes_and_message(self):
        self.assertEqual(self.lease("check")[:2], (0, ""))  # never used: silent and free
        self.acquire(A, "testing sign-in")
        rc, out, _ = self.lease("check", now=T0 + 60)
        self.assertEqual(rc, 3)
        self.assertIn(A, out)
        self.assertIn("testing sign-in", out)
        self.assertIn("until 08:30", out)  # T0 is 08:00 UTC (TZ=UTC in the test), +30 min

    def test_steal_needs_force_and_names_the_previous_holder(self):
        self.acquire(A, "testing sign-in")
        rc, _, err = self.lease("steal", "--for", "owner [o]", now=T0 + 10)
        self.assertEqual(rc, 2)
        self.assertEqual(self.read()["holder"], A)
        rc, out, _ = self.lease("steal", "--for", "owner [o]", "--force", "--why", "fixing it", now=T0 + 10)
        self.assertEqual(rc, 0)
        self.assertIn(A, out)
        self.assertIn("testing sign-in", out)
        self.assertEqual((self.read()["holder"], self.read()["why"]), ("owner [o]", "fixing it"))

    def test_wait_gives_up_with_exit_3_after_the_wait(self):
        self.acquire(A, ttl="30m", now=None)
        began = time.monotonic()
        rc, _, err = self.lease("acquire", "--for", B, "--why", "w", "--wait", "2s")
        self.assertEqual(rc, 3)
        self.assertGreaterEqual(time.monotonic() - began, 1.9)
        self.assertIn(A, err)

    def test_wait_gets_the_lease_when_the_holder_releases(self):
        self.acquire(A, now=None)
        waiter = subprocess.Popen([sys.executable, "-I", HELPER, "acquire", "--for", B, "--why", "w", "--wait", "20s"],
                                  env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.0)
        self.assertEqual(self.lease("release", "--for", A)[0], 0)
        waiter.communicate(timeout=15)
        self.assertEqual(waiter.returncode, 0)
        self.assertEqual(self.read()["holder"], B)

    def corrupt(self, text):
        os.makedirs(self.state, exist_ok=True)
        with open(self.lease_file, "w", encoding="utf-8") as f:
            f.write(text)

    def test_corrupt_lease_blocks_with_a_clear_message_until_the_owner_steals_it(self):
        for text in ("{not json", "[]", '{"holder": "x"}', '{"holder": "", "why": "", "since": 1, "expires": 2}'):
            self.corrupt(text)
            rc, _, err = self.acquire(B, now=None)  # the real clock: the file's age counts
            self.assertEqual(rc, 3, text)
            self.assertIn("unreadable", err)
            self.assertIn("steal", err)
            self.assertEqual(self.lease("check")[0], 3)
            self.assertEqual(self.lease("release", "--for", B)[0], 3)
            self.assertEqual(json.loads(self.lease("status", "--json")[1])["state"], "unreadable")
        rc, out, _ = self.lease("steal", "--for", "owner [o]", "--force")
        self.assertEqual(rc, 0)
        self.assertIn("unreadable", out)
        self.assertEqual(self.read()["holder"], "owner [o]")

    def test_a_corrupt_lease_cannot_block_for_ever(self):
        self.corrupt("{not json")
        self.assertEqual(self.lease("check", now=int(time.time()) + 5 * 3600)[0], 0)  # older than the 4 h limit

    def test_status_json_shape(self):
        keys = {"state", "holder", "why", "since", "expires", "seconds_left", "now", "text"}
        free = json.loads(self.lease("status", "--json", now=T0)[1])
        self.assertEqual(set(free), keys)
        self.assertEqual((free["state"], free["holder"], free["expires"]), ("free", None, None))
        self.acquire(A, "testing sign-in", ttl="45m")
        held = json.loads(self.lease("status", "--json", now=T0 + 60)[1])
        self.assertEqual(set(held), keys)
        self.assertEqual((held["state"], held["holder"], held["why"], held["since"], held["expires"], held["seconds_left"], held["now"]),
                         ("held", A, "testing sign-in", T0, T0 + 2700, 2640, T0 + 60))
        self.assertIn(A, held["text"])
        expired = json.loads(self.lease("status", "--json", now=T0 + 9000)[1])
        self.assertEqual((expired["state"], expired["holder"], expired["seconds_left"]), ("expired", A, 0))

    def test_usage_errors_exit_2_and_text_is_one_clean_line(self):
        self.assertEqual(self.lease("acquire", "--for", A)[0], 2)  # no --why
        self.assertEqual(self.lease("acquire", "--why", "x")[0], 2)  # no --for
        self.assertEqual(self.lease("acquire", "--for", "  ", "--why", "x")[0], 2)
        self.assertEqual(self.lease("frobnicate")[0], 2)
        self.assertEqual(self.lease()[0], 2)
        self.acquire(A, "two\nlines\x07 here")
        self.assertEqual(self.read()["why"], "two lines here")


# --- shell level -------------------------------------------------------------------------------

SHELL_FILES = [os.path.join(TOOLS, n) for n in ("common.sh", "deploy.sh", "device-lease.sh", "doctor.sh", "screenshot.sh")] + [UPDATE]


class Shell(Base):
    def sh(self, script, now=T0, **extra):
        env = self.env(now, **extra)
        env.pop("MEDIASTICK_HOLDER", None)
        env.pop("MEDIASTICK_NO_LEASE", None)
        p = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, cwd=ROOT)
        return p.returncode, p.stdout, p.stderr

    # ssh is a function that runs the "remote" command here, against the real helper
    PRE = ('set -euo pipefail; . tools/common.sh; ssh() { bash -c "${@: -1}"; }; LEASE_BIN=%s; ' % HELPER)

    def test_scripts_parse_and_pass_shellcheck(self):
        for path in SHELL_FILES:
            self.assertEqual(subprocess.run(["bash", "-n", path], capture_output=True).returncode, 0, path)
        if shutil.which("shellcheck"):
            p = subprocess.run(["shellcheck", "-S", "warning", "-x", "-P", TOOLS, *SHELL_FILES], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout)

    def test_require_lease_with_no_lease_says_how_to_get_one(self):
        rc, _, err = self.sh(self.PRE + 'require_lease')
        self.assertEqual(rc, 3)
        self.assertIn("device-lease.sh acquire", err)

    def test_require_lease_passes_for_the_holder_and_extends_the_lease(self):
        self.acquire(A, ttl="2m")  # holder has spaces and brackets: quoting over ssh must survive
        rc, _, err = self.sh(self.PRE + 'MEDIASTICK_HOLDER=%s require_lease' % "'%s'" % A)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(self.read()["expires"], T0 + 900)

    def test_require_lease_refuses_another_session_naming_it(self):
        self.acquire(A, "testing sign-in")
        for holder in ("'%s'" % B, "''"):  # another holder, and no holder at all
            rc, _, err = self.sh(self.PRE + 'MEDIASTICK_HOLDER=%s require_lease' % holder)
            self.assertEqual(rc, 3, holder)
            self.assertIn(A, err)
            self.assertIn("testing sign-in", err)
        self.assertEqual(self.read()["expires"], T0 + 1800)  # a refused tool changes nothing

    def test_require_lease_escape_hatch_is_loud_and_a_missing_helper_only_warns(self):
        self.acquire(A)
        rc, _, err = self.sh(self.PRE + 'MEDIASTICK_NO_LEASE=1 require_lease')
        self.assertEqual(rc, 0)
        self.assertIn("WITHOUT the lease", err)
        rc, _, err = self.sh(self.PRE + 'LEASE_BIN=%s/none; require_lease' % self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("not installed", err)

    def test_lease_note_for_read_only_tools(self):
        self.assertEqual(self.sh(self.PRE + 'lease_note')[1:], ("", ""))
        self.acquire(A, "testing sign-in")
        rc, out, err = self.sh(self.PRE + 'lease_note')
        self.assertEqual(rc, 0)
        self.assertTrue(err.startswith("NOTE"), err)
        self.assertIn(A, err)
        self.assertEqual(self.sh(self.PRE + 'LEASE_BIN=%s/none; lease_note' % self.tmp)[1:], ("", ""))


class Deploy(Base):
    """tools/deploy.sh, run from a temporary clone of a temporary origin (up to date with it), with
    ssh and rsync replaced by programs that only log what they were asked."""

    GIT_ENV = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)

    def git(self, cwd, *args):
        subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True,
                       env=dict(os.environ, **self.GIT_ENV))

    def commit(self, tree, name):
        with open(os.path.join(tree, name), "w") as f:
            f.write(name)
        self.git(tree, "add", name)
        self.git(tree, "commit", "-q", "-m", name)

    def setUp(self):
        super().setUp()
        origin, self.work, self.other = (os.path.join(self.tmp, n) for n in ("origin.git", "work", "other"))
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", origin)
        self.git(self.tmp, "clone", "-q", origin, self.work)
        for rel in ("tools/common.sh", "tools/deploy.sh"):
            os.makedirs(os.path.join(self.work, "tools"), exist_ok=True)
            shutil.copy2(os.path.join(ROOT, rel), os.path.join(self.work, rel))
        panel = os.path.join(self.work, "device", "files", "usr", "local", "bin")
        os.makedirs(panel)
        with open(os.path.join(panel, "panel"), "w") as f:
            f.write("panel")
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-q", "-m", "base")
        self.git(self.work, "push", "-q", "origin", "HEAD:main")
        self.git(self.work, "branch", "-q", "--set-upstream-to=origin/main")
        self.git(self.tmp, "clone", "-q", origin, self.other)
        self.bin = os.path.join(self.tmp, "bin")
        self.log = os.path.join(self.tmp, "calls.log")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "ssh"), "w") as f:  # the real helper answers the lease; the rest is logged
            f.write('#!/bin/bash\ncmd=${@: -1}\n'
                    'case "$cmd" in /usr/local/bin/media-stick-lease*) exec bash -c "${cmd/\\/usr\\/local\\/bin\\/media-stick-lease/%s}" ;; esac\n'
                    'echo "ssh: $cmd" >> %s\n' % (HELPER, self.log))
        with open(os.path.join(self.bin, "rsync"), "w") as f:
            f.write('#!/bin/bash\n{ echo "rsync:"; printf "  %%s\\n" "$@"; } >> %s\n' % self.log)
        for name in ("ssh", "rsync"):
            os.chmod(os.path.join(self.bin, name), 0o755)

    def deploy(self, *args, holder=None, no_lease=False, no_base_check=False):
        env = self.env(T0, PATH=self.bin + os.pathsep + os.environ["PATH"], **self.GIT_ENV)
        env.pop("MEDIASTICK_HOLDER", None)
        if holder:
            env["MEDIASTICK_HOLDER"] = holder
        if no_lease:
            env["MEDIASTICK_NO_LEASE"] = "1"
        if no_base_check:
            env["MEDIASTICK_NO_BASE_CHECK"] = "1"
        p = subprocess.run([os.path.join(self.work, "tools", "deploy.sh"), *args], env=env, capture_output=True, text=True)
        calls = ""
        if os.path.exists(self.log):
            with open(self.log) as f:
                calls = f.read()
        return p.returncode, p.stdout, p.stderr, calls

    def test_every_form_is_refused_without_a_lease_and_changes_nothing(self):
        for args in ((), ("--local",), ("--only", "tools/common.sh")):
            rc, _, err, calls = self.deploy(*args)
            self.assertEqual(rc, 3, args)
            self.assertIn("hold no device lease", err)
            self.assertEqual(calls, "", args)

    def test_every_form_is_refused_while_another_session_holds_it(self):
        self.acquire(A, "testing sign-in")
        for args in ((), ("--local",), ("--only", "tools/common.sh")):
            rc, _, err, calls = self.deploy(*args, holder=B)
            self.assertEqual(rc, 3, args)
            self.assertIn("testing sign-in", err)
            self.assertEqual(calls, "", args)

    def test_only_sends_just_the_listed_paths_without_delete_then_bootstraps(self):
        self.acquire(A)
        rc, out, err, calls = self.deploy("--only", "device/files/usr/local/bin/panel", "./tools/common.sh", holder=A)
        self.assertEqual(rc, 0, err)
        self.assertIn("sending only: device/files/usr/local/bin/panel tools/common.sh", out)
        rsync, ssh = calls.split("ssh:", 1)
        self.assertIn("  ./device/files/usr/local/bin/panel\n  ./tools/common.sh\n", rsync)
        self.assertNotIn("delete", rsync)
        self.assertIn("-azRv", rsync)
        self.assertIn("--checksum", rsync)  # same size and mtime second must not keep the old file
        self.assertIn("/opt/media-stick/device/bootstrap.sh", ssh)
        self.assertEqual(calls.count("rsync:"), 1)

    def test_only_refuses_paths_outside_the_repository_before_anything_else(self):
        self.acquire(A)
        for bad in ("/etc/passwd", "../x", "device/../../x", ".git/config", "device/.git", "secrets.env", "device/x.local",
                    ".", "", "no/such/file"):
            rc, _, err, calls = self.deploy("--only", "tools/common.sh", bad, holder=A)
            self.assertEqual(rc, 2, bad)
            self.assertIn("refusing", err, bad)
            self.assertEqual(calls, "", bad)
        self.assertEqual(self.deploy("--only", holder=A)[0], 2)
        self.assertEqual(self.deploy("--bogus", holder=A)[0], 2)

    FORMS = ((), ("--local",), ("--only", "tools/common.sh"))

    def push_from_the_other_session(self):
        self.git(self.other, "pull", "-q", "origin", "main")
        self.commit(self.other, "their-panel-edit")
        self.git(self.other, "push", "-q", "origin", "HEAD:main")

    def test_a_tree_behind_origin_main_is_refused_in_every_form_after_a_fetch(self):
        self.acquire(A)
        self.push_from_the_other_session()  # this clone has not fetched it yet: the tool must
        for args in self.FORMS:
            rc, _, err, calls = self.deploy(*args, holder=A)
            self.assertEqual(rc, 4, args)
            self.assertIn("local tree lacks commits from origin/main, rebase/merge first", err)
            self.assertEqual(calls, "", args)
        self.git(self.work, "pull", "-q", "--rebase", "origin", "main")  # after the rebase it goes through
        for args in self.FORMS:
            self.assertEqual(self.deploy(*args, holder=A)[0], 0, args)

    def test_a_tree_ahead_of_origin_main_is_allowed_a_diverged_one_is_not(self):
        self.acquire(A)
        self.commit(self.work, "my-local-commit")  # not pushed
        for args in self.FORMS:
            self.assertEqual(self.deploy(*args, holder=A)[0], 0, args)
        self.push_from_the_other_session()
        rc, _, err, _ = self.deploy("--only", "tools/common.sh", holder=A)
        self.assertEqual(rc, 4)
        self.assertIn("rebase/merge first", err)

    def test_an_uncommitted_edit_on_an_up_to_date_tree_is_what_local_is_for(self):
        self.acquire(A)
        with open(os.path.join(self.work, "device", "files", "usr", "local", "bin", "panel"), "w") as f:
            f.write("edited")
        self.assertEqual(self.deploy("--local", holder=A)[0], 0)

    def test_the_owner_can_skip_the_base_check_loudly(self):
        self.push_from_the_other_session()
        rc, _, err, _ = self.deploy("--only", "tools/common.sh", no_lease=True, no_base_check=True)
        self.assertEqual(rc, 0)
        self.assertIn("NO_BASE_CHECK", err)

    def test_owner_escape_hatch_lets_a_deploy_through_loudly(self):
        rc, _, err, calls = self.deploy("--only", "tools/common.sh", no_lease=True)
        self.assertEqual(rc, 0)
        self.assertIn("WITHOUT the lease", err)
        self.assertIn("rsync:", calls)


class UpdateGuard(Base):
    """media-stick-update, run for real with its absolute paths pointed into a temporary directory and git,
    kodi-rpc, systemctl and bootstrap replaced by stubs that only log: what makes it postpone."""
    SIGNIN = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick", "mediastick_signin.py")

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmp, "opt-repo")
        self.bin = os.path.join(self.tmp, "bin")
        self.signin_dir = os.path.join(self.tmp, "signin")
        self.log = os.path.join(self.tmp, "calls.log")
        for d in (os.path.join(self.repo, "device"), self.bin):
            os.makedirs(d)
        self.stub("git", 'echo "git $*" >> "$STUB_LOG"\ncase "$*" in\n'
                         '  *"rev-parse HEAD"*) echo aaaaaaa1111;;\n  *"rev-parse origin/main"*) echo bbbbbbb2222;;\n'
                         '  *" log "*) echo "a subject";;\nesac\nexit 0')
        self.stub("setpriv", 'while [ $# -gt 0 ] && [ "$1" != git ]; do shift; done\nexec "$@"')   # drops the user switch
        self.stub("kodi-rpc", "echo '[]'")                                          # nothing is playing
        self.stub("systemctl", 'echo "systemctl $*" >> "$STUB_LOG"\nexit 1')       # no web app is active; a reboot is logged
        with open(os.path.join(self.repo, "device", "bootstrap.sh"), "w") as f:
            f.write('#!/bin/bash\necho "bootstrap" >> "$STUB_LOG"\necho "[bootstrap] done"\n')
        os.chmod(os.path.join(self.repo, "device", "bootstrap.sh"), 0o755)
        with open(UPDATE, encoding="utf-8") as f:
            text = f.read()
        for old, new in (("REPO=/opt/media-stick", "REPO=" + self.repo),
                         ("/run/media-stick-update.lock", os.path.join(self.tmp, "update.lock")),
                         ("/usr/local/bin/media-stick-lease", HELPER),
                         ("/usr/local/lib/media-stick/mediastick_signin.py", self.SIGNIN),
                         ("/var/lib/media-stick/bad-commit", os.path.join(self.tmp, "bad-commit"))):
            self.assertIn(old, text)
            text = text.replace(old, new)
        self.script = os.path.join(self.tmp, "media-stick-update")
        with open(self.script, "w", encoding="utf-8") as f:
            f.write(text)

    def stub(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write("#!/bin/bash\n" + body + "\n")
        os.chmod(path, 0o755)

    def update(self, *args, now=None, signin_script=None):
        env = self.env(now, PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_LOG=self.log,
                       MEDIASTICK_SIGNIN_DIR=self.signin_dir)
        p = subprocess.run(["bash", signin_script or self.script, *args], env=env, capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    def calls(self):
        try:
            with open(self.log, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def signin_state(self, service="sweettv", state="waiting", mode="partner", updated_ago=0, left=3600):
        now = int(time.time())
        os.makedirs(self.signin_dir, exist_ok=True)
        with open(os.path.join(self.signin_dir, service + ".json"), "w") as f:
            json.dump({"service": service, "state": state, "mode": mode, "step": 1, "steps": 1, "code": "12345",
                       "updated": now - updated_ago, "expires": now + left}, f)

    def assertUpdated(self, rc, out):
        self.assertEqual(rc, 0)
        self.assertIn("updating aaaaaaa -> bbbbbbb", out)
        self.assertIn("updated to bbbbbbb", out)
        self.assertIn("bootstrap", self.calls())
        self.assertIn("reset -q --hard bbbbbbb2222", self.calls())

    def assertPostponed(self, rc, out, who):
        self.assertEqual(rc, 0)
        self.assertIn("update to bbbbbbb postponed", out)
        self.assertIn(who, out)
        self.assertNotIn("bootstrap", self.calls())
        self.assertNotIn("reset", self.calls())

    def test_with_nothing_in_the_way_it_updates(self):
        rc, out, _ = self.update()
        self.assertUpdated(rc, out)

    def test_a_partner_sign_in_that_is_waiting_postpones_it(self):
        self.signin_state(mode="partner")
        rc, out, _ = self.update()
        self.assertPostponed(rc, out, "SWEET.TV sign-in waits for a code (partner")
        self.assertNotIn("12345", out)                     # the code is not written to the update's log

    def test_so_does_a_normal_one_and_a_youtube_one(self):
        self.signin_state(mode="normal")
        self.assertPostponed(*self.update()[:2], "SWEET.TV sign-in waits for a code (normal")
        os.unlink(os.path.join(self.signin_dir, "sweettv.json"))
        self.signin_state(service="youtube", mode="normal")
        self.assertPostponed(*self.update()[:2], "YouTube sign-in waits for a code")

    def test_a_state_that_nobody_touches_or_that_ran_out_or_is_over_does_not_hold_the_update(self):
        for kw in ({"updated_ago": 120}, {"left": -5}, {"state": "done"}, {"state": "failed"}, {"state": "cancelled"}):
            self.signin_state(**kw)
            rc, out, _ = self.update()
            self.assertUpdated(rc, out)
            os.unlink(self.log)

    def test_force_goes_ahead_while_a_sign_in_waits(self):
        self.signin_state()
        rc, out, _ = self.update("--force")
        self.assertUpdated(rc, out)

    def test_the_update_goes_on_when_the_device_has_no_helper_or_it_is_broken(self):
        self.signin_state()
        text = open(self.script, encoding="utf-8").read().replace(self.SIGNIN, os.path.join(self.tmp, "no-such-helper.py"))
        old = os.path.join(self.tmp, "old-update")
        with open(old, "w", encoding="utf-8") as f:
            f.write(text)
        rc, out, _ = self.update(signin_script=old)
        self.assertUpdated(rc, out)                        # an older device: nothing to ask, as with the lease helper
        os.unlink(self.log)
        broken = os.path.join(self.tmp, "broken.py")
        with open(broken, "w") as f:
            f.write("raise SystemExit(1)\n")
        with open(old, "w", encoding="utf-8") as f:
            f.write(text.replace(os.path.join(self.tmp, "no-such-helper.py"), broken))
        rc, out, _ = self.update(signin_script=old)
        self.assertUpdated(rc, out)

    def test_the_lease_and_playback_still_postpone_it_and_a_sign_in_does_not_hide_which(self):
        self.acquire(A, "testing sign-in")
        rc, out, _ = self.update(now=T0)
        self.assertPostponed(rc, out, A)
        self.stub("kodi-rpc", 'echo \'[{"playerid": 1}]\'')
        os.unlink(self.lease_file)
        rc, out, _ = self.update(now=T0)
        self.assertIn("kodi is playing", out)

    def test_the_library_command_itself_says_who_waits_and_exits_3(self):
        env = self.env(None, MEDIASTICK_SIGNIN_DIR=self.signin_dir)

        def ask(*args):
            p = subprocess.run([sys.executable, self.SIGNIN, *args], env=env, capture_output=True, text=True)
            return p.returncode, p.stdout.strip()
        self.assertEqual(ask("waiting"), (0, ""))
        self.signin_state(left=2 * 3600 + 30)
        rc, out = ask("waiting")
        self.assertEqual(rc, 3)
        self.assertRegex(out, r"^SWEET\.TV sign-in waits for a code \(partner, 1(19|20) min left\)$")
        self.assertEqual(ask("bogus")[0], 2)
        self.assertEqual(ask()[0], 2)


class OnlyPaths(Base):
    """only_check / only_push on local directories: one tree is the repository, one the device."""

    def setUp(self):
        super().setUp()
        self.repo, self.dev = os.path.join(self.tmp, "repo"), os.path.join(self.tmp, "dev")
        for tree, text in ((self.repo, "new"), (self.dev, "old")):
            for rel in ("a/one.txt", "a/two.txt", "b/three.txt"):
                self.put(tree, rel, text)
        self.put(self.dev, "c/keep.txt", "device only")
        self.put(self.dev, "a/extra.txt", "device only")
        self.put(self.repo, "n/deep/four.txt", "new")
        self.put(self.repo, "secrets.example.env", "NAME=\n")
        # same sizes and one whole-second mtime on both sides: what rsync quick check cannot tell apart
        for tree in (self.repo, self.dev):
            for d, _, names in os.walk(tree):
                for name in names:
                    os.utime(os.path.join(d, name), (1700000000, 1700000000))

    def put(self, tree, rel, text):
        path = os.path.join(tree, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def text(self, tree, rel):
        with open(os.path.join(tree, rel)) as f:
            return f.read()

    def bash(self, script):
        p = subprocess.run(["bash", "-c", ". %s/common.sh; %s" % (TOOLS, script)], capture_output=True, text=True, env=self.env())
        return p.returncode, p.stdout, p.stderr

    def test_check_accepts_inside_paths_and_normalises_dot_slash(self):
        rc, out, _ = self.bash('only_check %s ./a/one.txt b secrets.example.env n/deep; echo "${ONLY[*]}"' % self.repo)
        self.assertEqual((rc, out.strip()), (0, "a/one.txt b secrets.example.env n/deep"))

    def test_check_refuses_the_rest(self):
        os.symlink(self.dev, os.path.join(self.repo, "escape"))
        self.put(self.repo, ".git/config", "x")
        for bad in ("/etc/passwd", "../dev/c/keep.txt", "a/../b", ".git/config", "a/.git", "secrets.env", "a/secrets.env",
                    "x.local", "a/y.local/z", ".", "./", "missing.txt", "escape/c/keep.txt"):
            rc, _, err = self.bash('only_check %s a/one.txt %s' % (self.repo, "'%s'" % bad))
            self.assertEqual(rc, 1, bad)
            self.assertIn("refusing", err, bad)

    @unittest.skipUnless(shutil.which("rsync"), "rsync is not installed here (the owner's computer has it)")
    def test_only_push_touches_nothing_that_is_not_listed(self):
        rc, _, err = self.bash('RSYNC_E=(); only_push %s %s/ a/one.txt n/deep/four.txt' % (self.repo, self.dev))
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.text(self.dev, "a/one.txt"), "new")  # listed: sent
        self.assertEqual(self.text(self.dev, "n/deep/four.txt"), "new")  # listed, directories made on the way
        self.assertEqual(self.text(self.dev, "a/two.txt"), "old")  # same directory, not listed
        self.assertEqual(self.text(self.dev, "b/three.txt"), "old")  # other directory, not listed
        self.assertEqual(self.text(self.dev, "a/extra.txt"), "device only")  # only on the device: not deleted
        self.assertEqual(self.text(self.dev, "c/keep.txt"), "device only")
        self.assertFalse(os.path.exists(os.path.join(self.dev, "secrets.example.env")))

    @unittest.skipUnless(shutil.which("rsync"), "rsync is not installed here (the owner's computer has it)")
    def test_only_push_of_a_directory_adds_and_replaces_but_never_deletes(self):
        rc, _, err = self.bash('RSYNC_E=(); only_push %s %s/ a' % (self.repo, self.dev))
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.text(self.dev, "a/two.txt"), "new")
        self.assertEqual(self.text(self.dev, "a/extra.txt"), "device only")
        self.assertEqual(self.text(self.dev, "b/three.txt"), "old")


if __name__ == "__main__":
    unittest.main()
