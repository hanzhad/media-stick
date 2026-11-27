#!/usr/bin/env python3
"""Declarative OS file, fstab, sudoers, and admin hygiene reconciler.

Pure Core functions plan file syncs/prunes, fstab updates, and affected systemd units
without touching the filesystem. The Thin I/O Shell applies them atomically under
--root (defaulting to /) so offline unit tests can exercise the full flow safely.
"""
import argparse
from dataclasses import dataclass
import json
import os
import posixpath
import pwd
import stat
import subprocess
import sys
import tempfile

MANAGED_FILES_REL = "var/lib/media-stick/managed-files.json"
FSTAB_REL = "etc/fstab"
TMPFS_KODI_TEMP = (
    "tmpfs /home/media/.kodi/temp tmpfs "
    "nosuid,nodev,noexec,size=16M,uid=1000,gid=1000,mode=0755 0 0"
)
EXECUTABLE_PARENTS = frozenset({"usr/local/bin", "usr/local/sbin"})
SUDOERS_PARENTS = frozenset({"etc/sudoers.d"})
DEFAULT_REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


# --- Pure Core ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FileSpec:
    """Target file specification with normalized root-relative path and octal mode."""

    rel_path: str
    mode: int


def _norm_rel(path: str) -> str:
    cleaned = path.replace("\\", "/").lstrip("/")
    return posixpath.normpath(cleaned)


def _mode_for_rel(rel_path: str) -> int:
    parent = posixpath.dirname(rel_path)
    if parent in EXECUTABLE_PARENTS:
        return 0o755
    if parent in SUDOERS_PARENTS:
        return 0o440
    return 0o644


def plan_file_ops(src_files, prev_managed) -> tuple[list[FileSpec], list[str]]:
    """Compute deterministic FileSpecs to sync and orphaned paths to prune."""
    src_set = {_norm_rel(p) for p in src_files if p}
    prev_set = {_norm_rel(p) for p in prev_managed if p}
    specs = [FileSpec(rel_path=p, mode=_mode_for_rel(p)) for p in sorted(src_set)]
    orphans = sorted(prev_set - src_set)
    return specs, orphans


def reconcile_fstab_lines(existing_lines: list[str]) -> tuple[list[str], bool]:
    """Ensure / has noatime,commit=60 and /home/media/.kodi/temp tmpfs mount exists."""
    out_lines: list[str] = []
    changed = False
    has_kodi_tmpfs = False

    for line in existing_lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue

        fields = line.split()
        if len(fields) >= 2 and fields[1] == "/home/media/.kodi/temp":
            has_kodi_tmpfs = True

        if len(fields) >= 4 and fields[1] == "/":
            opts = [o for o in fields[3].split(",") if o]
            new_opts = list(opts)
            if "noatime" not in new_opts:
                new_opts.append("noatime")
            if "commit=60" not in new_opts:
                replaced = False
                for idx, opt in enumerate(new_opts):
                    if opt.startswith("commit="):
                        new_opts[idx] = "commit=60"
                        replaced = True
                        break
                if not replaced:
                    new_opts.append("commit=60")
            if new_opts != opts:
                fields[3] = ",".join(new_opts)
                out_lines.append("  ".join(fields))
                changed = True
            else:
                out_lines.append(line)
            continue

        out_lines.append(line)

    if not has_kodi_tmpfs:
        out_lines.append(TMPFS_KODI_TEMP)
        changed = True

    return out_lines, changed


def extract_changed_units(updated_rel_paths: list[str], existing_services: set[str]) -> list[str]:
    """Return systemd units affected by updated files, filtered by existing_services."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(unit: str) -> None:
        if unit in existing_services and unit not in seen:
            seen.add(unit)
            candidates.append(unit)

    for raw_rel in updated_rel_paths:
        rel = _norm_rel(raw_rel)
        parent = posixpath.dirname(rel)
        if parent == "etc/systemd/system":
            _add(posixpath.basename(rel))
        elif rel.startswith("home/media/.kodi/"):
            _add("kodi.service")
        elif rel == "etc/asound.conf":
            for unit in ("kodi.service", "airplay.service", "miracast.service"):
                _add(unit)
        elif rel == "etc/pam.d/mediastick-kodi":
            _add("kodi.service")
        elif rel.startswith("usr/local/lib/media-stick/"):
            _add("panel.service")
        elif parent == "usr/local/bin":
            _add(f"{posixpath.basename(rel)}.service")

    return candidates


# --- Thin I/O Shell -------------------------------------------------------------------------------


def _collect_source_files(files_dir: str) -> list[str]:
    if not os.path.isdir(files_dir):
        return []
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(files_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in {".git", "__pycache__"})
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, files_dir).replace(os.sep, "/")
            found.append(_norm_rel(rel))
    return sorted(found)


def _load_managed_files(managed_path: str) -> list[str]:
    if not os.path.exists(managed_path):
        return []
    with open(managed_path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [str(x) for x in data]
    if isinstance(data, dict) and isinstance(data.get("files"), list):
        return [str(x) for x in data["files"]]
    return []


def _atomic_write_bytes(dst_path: str, data: bytes, mode: int, uid: int = -1, gid: int = -1) -> None:
    parent = os.path.dirname(dst_path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".os-apply-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp_path, mode)
        if uid >= 0 or gid >= 0:
            os.chown(tmp_path, uid, gid)
        os.replace(tmp_path, dst_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _validate_sudoers(path: str) -> None:
    proc = subprocess.run(["visudo", "-cf", path], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"visudo validation failed for {path}: {detail}")


def _file_matches(dst_path: str, src_bytes: bytes, expected_mode: int) -> bool:
    if os.path.islink(dst_path) or not os.path.isfile(dst_path):
        return False
    st = os.stat(dst_path)
    if stat.S_IMODE(st.st_mode) != expected_mode:
        return False
    with open(dst_path, "rb") as f:
        return f.read() == src_bytes


def ensure_msadmin(root: str = "/", dry_run: bool = False, skip_visudo: bool = False) -> bool:
    """Additively ensure msadmin admin user, sudoers drop-in, and SSH keys on real /."""
    if os.geteuid() != 0 or os.path.realpath(root) != "/":
        return False

    changed = False
    try:
        pw = pwd.getpwnam("msadmin")
        user_exists = True
    except KeyError:
        pw = None
        user_exists = False

    if not user_exists:
        if dry_run:
            print("[os_apply] would create user msadmin (sudo,systemd-journal)")
        else:
            subprocess.run(
                ["useradd", "-m", "-s", "/bin/bash", "-G", "sudo,systemd-journal", "msadmin"],
                check=True,
            )
            pw = pwd.getpwnam("msadmin")
            print("[os_apply] created user msadmin")
        changed = True
    else:
        groups_out = subprocess.check_output(["id", "-nG", "msadmin"], text=True).split()
        missing_groups = [g for g in ("sudo", "systemd-journal") if g not in groups_out]
        if missing_groups:
            if dry_run:
                print(f"[os_apply] would add msadmin to {','.join(missing_groups)}")
            else:
                subprocess.run(
                    ["usermod", "-aG", ",".join(missing_groups), "msadmin"],
                    check=True,
                )
            changed = True

    sudoers_dst = os.path.join(root, "etc", "sudoers.d", "msadmin")
    sudoers_bytes = b"msadmin ALL=(ALL) NOPASSWD:ALL\n"
    if not _file_matches(sudoers_dst, sudoers_bytes, 0o440):
        if dry_run:
            print("[os_apply] would update /etc/sudoers.d/msadmin")
        else:
            parent = os.path.dirname(sudoers_dst)
            os.makedirs(parent, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".sudoers-msadmin-", dir=parent)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(sudoers_bytes)
                os.chmod(tmp_path, 0o440)
                if not skip_visudo:
                    _validate_sudoers(tmp_path)
                os.replace(tmp_path, sudoers_dst)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            print("[os_apply] updated /etc/sudoers.d/msadmin")
        changed = True

    media_keys = os.path.join(root, "home", "media", ".ssh", "authorized_keys")
    if os.path.isfile(media_keys):
        with open(media_keys, "rb") as f:
            key_bytes = f.read()
        msadmin_ssh_dir = os.path.join(root, "home", "msadmin", ".ssh")
        msadmin_keys = os.path.join(msadmin_ssh_dir, "authorized_keys")
        if not _file_matches(msadmin_keys, key_bytes, 0o600):
            if dry_run:
                print("[os_apply] would copy authorized_keys to msadmin")
            else:
                assert pw is not None
                os.makedirs(msadmin_ssh_dir, mode=0o700, exist_ok=True)
                os.chmod(msadmin_ssh_dir, 0o700)
                os.chown(msadmin_ssh_dir, pw.pw_uid, pw.pw_gid)
                _atomic_write_bytes(msadmin_keys, key_bytes, 0o600, uid=pw.pw_uid, gid=pw.pw_gid)
                print("[os_apply] copied authorized_keys to msadmin")
            changed = True

    return changed


def apply_os(
    repo: str,
    root: str = "/",
    dry_run: bool = False,
    skip_visudo: bool = False,
) -> dict:
    """Reconcile device/files, orphan pruning, /etc/fstab, and msadmin under root."""
    files_dir = os.path.join(repo, "device", "files")
    managed_path = os.path.join(root, MANAGED_FILES_REL)

    src_files = _collect_source_files(files_dir)
    prev_managed = _load_managed_files(managed_path)
    specs, orphans = plan_file_ops(src_files, prev_managed)

    updated: list[str] = []
    removed: list[str] = []

    media_uid = -1
    media_gid = -1
    if os.geteuid() == 0 and os.path.realpath(root) == "/":
        try:
            media_pw = pwd.getpwnam("media")
            media_uid = media_pw.pw_uid
            media_gid = media_pw.pw_gid
        except KeyError:
            pass

    for spec in specs:
        src_path = os.path.join(files_dir, spec.rel_path)
        dst_path = os.path.join(root, spec.rel_path)
        with open(src_path, "rb") as f:
            src_bytes = f.read()

        if _file_matches(dst_path, src_bytes, spec.mode):
            continue

        if dry_run:
            print(f"[os_apply] would update /{spec.rel_path}")
            updated.append(spec.rel_path)
            continue

        if spec.rel_path.startswith("etc/sudoers.d/") and not skip_visudo:
            _validate_sudoers(src_path)

        uid, gid = (-1, -1)
        if spec.rel_path.startswith("home/media/"):
            uid, gid = media_uid, media_gid

        _atomic_write_bytes(dst_path, src_bytes, spec.mode, uid=uid, gid=gid)
        print(f"[os_apply] updated /{spec.rel_path}")
        updated.append(spec.rel_path)

    for rel in orphans:
        dst_path = os.path.join(root, rel)
        if os.path.lexists(dst_path):
            if dry_run:
                print(f"[os_apply] would remove /{rel}")
            else:
                os.unlink(dst_path)
                print(f"[os_apply] removed /{rel}")
            removed.append(rel)

    if not dry_run:
        managed_payload = json.dumps([s.rel_path for s in specs], indent=2) + "\n"
        _atomic_write_bytes(managed_path, managed_payload.encode("utf-8"), 0o644)

    fstab_path = os.path.join(root, FSTAB_REL)
    fstab_changed = False
    if os.path.isfile(fstab_path):
        with open(fstab_path, encoding="utf-8") as f:
            existing_lines = f.read().splitlines()
        new_lines, fstab_changed = reconcile_fstab_lines(existing_lines)
        if fstab_changed:
            if dry_run:
                print("[os_apply] would update /etc/fstab")
            else:
                new_text = "\n".join(new_lines) + "\n"
                _atomic_write_bytes(fstab_path, new_text.encode("utf-8"), 0o644)
                print("[os_apply] updated /etc/fstab")

    ensure_msadmin(root, dry_run=dry_run, skip_visudo=skip_visudo)
    return {
        "updated": updated,
        "removed": removed,
        "fstab_changed": fstab_changed,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Declarative OS reconciler for media-stick.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Path to media-stick repo")
    parser.add_argument("--root", default="/", help="Target root filesystem (default: /)")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing")
    parser.add_argument("--skip-visudo", action="store_true", help="Skip visudo validation (for offline tests)")
    args = parser.parse_args(argv)

    try:
        apply_os(
            repo=os.path.abspath(args.repo),
            root=os.path.abspath(args.root),
            dry_run=args.dry_run,
            skip_visudo=args.skip_visudo,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"[os_apply] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
