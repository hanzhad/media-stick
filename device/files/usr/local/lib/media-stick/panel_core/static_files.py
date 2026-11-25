"""Pure Core + Thin File Server for Panel v2 PWA and ES-module static assets.

Pure Core:
  - is_static_path, resolve_asset_rel, cache_control_for, mime_type_for
  - accepts_gzip, etag_matches, build_cached_response

Thin File Server:
  - StaticAssets: serves /manifest.webmanifest, /sw.js, /icon-192.png, /icon-512.png,
    and /static/* from /usr/local/share/media-stick/web (with repo-relative fallback),
    with strong ETags, 304 Not Modified, gzip compression, immutable ?v=<hash> cache
    headers, and strict path-traversal rejection.
"""
import gzip
import hashlib
import os
import threading
from urllib.parse import parse_qs, unquote

INSTALLED_WEB_DIR = "/usr/local/share/media-stick/web"
ROOT_ASSETS = {
    "/manifest.webmanifest": "manifest.webmanifest",
    "/sw.js": "sw.js",
    "/icon-192.png": "icon-192.png",
    "/icon-512.png": "icon-512.png",
}

MIME_TYPES = {
    ".js": ("application/javascript; charset=utf-8", True),
    ".mjs": ("application/javascript; charset=utf-8", True),
    ".webmanifest": ("application/manifest+json; charset=utf-8", True),
    ".json": ("application/json; charset=utf-8", True),
    ".css": ("text/css; charset=utf-8", True),
    ".html": ("text/html; charset=utf-8", True),
    ".svg": ("image/svg+xml; charset=utf-8", True),
    ".png": ("image/png", False),
    ".jpg": ("image/jpeg", False),
    ".jpeg": ("image/jpeg", False),
}


# --- Pure Core ------------------------------------------------------------------------------------


def _hdr_get(headers, name: str) -> str:
    if not headers:
        return ""
    target = name.lower()
    if hasattr(headers, "items"):
        for k, v in headers.items():
            if str(k).lower() == target:
                return str(v).strip()
    return ""


def is_static_path(url_path: str) -> bool:
    """Return True if url_path targets a PWA root asset or /static/*."""
    raw_path = (url_path or "").split("?", 1)[0]
    return raw_path in ROOT_ASSETS or raw_path.startswith("/static/")


def resolve_asset_rel(url_path: str) -> str | None:
    """Map url_path to a safe root-relative asset path, or None if invalid/traversal."""
    raw_path = (url_path or "").split("?", 1)[0]
    if raw_path in ROOT_ASSETS:
        return ROOT_ASSETS[raw_path]
    if not raw_path.startswith("/static/"):
        return None
    sub = raw_path[len("/static/"):]
    if not sub:
        return None
    # Decode once, and reject double-encoded tricks or raw backslashes/NULs
    decoded = unquote(sub)
    if "%" in decoded:
        decoded_twice = unquote(decoded)
        if decoded_twice != decoded:
            return None
    if "\x00" in sub or "\x00" in decoded or "\\" in sub or "\\" in decoded:
        return None
    parts = decoded.split("/")
    for seg in parts:
        if seg in ("", ".", ".."):
            return None
    return "static/" + "/".join(parts)


def has_version_query(url_path: str) -> bool:
    """Return True if the URL query string carries a non-empty `v` parameter."""
    if "?" not in (url_path or ""):
        return False
    qs = url_path.split("?", 1)[1]
    vals = parse_qs(qs, keep_blank_values=False).get("v")
    return bool(vals and vals[0])


def cache_control_for(url_path: str, rel_path: str) -> str:
    """Choose Cache-Control header value for a resolved static asset."""
    if rel_path.startswith("static/") and has_version_query(url_path):
        return "public, max-age=31536000, immutable"
    if rel_path == "sw.js":
        return "no-cache"
    if rel_path in ("icon-192.png", "icon-512.png"):
        return "public, max-age=86400"
    return "public, max-age=3600"


def mime_type_for(rel_path: str) -> tuple[str, bool]:
    """Return `(content_type, compressible)` for `rel_path`."""
    _, ext = os.path.splitext(rel_path.lower())
    return MIME_TYPES.get(ext, ("application/octet-stream", False))


def accepts_gzip(headers) -> bool:
    """Return True when request Accept-Encoding permits gzip."""
    ae = _hdr_get(headers, "Accept-Encoding").lower()
    if not ae:
        return False
    for part in ae.split(","):
        tokens = [t.strip() for t in part.split(";") if t.strip()]
        if not tokens:
            continue
        coding = tokens[0]
        if coding not in ("gzip", "*"):
            continue
        q_zero = False
        for param in tokens[1:]:
            if param.startswith("q="):
                try:
                    if float(param[2:]) <= 0.0:
                        q_zero = True
                except ValueError:
                    pass
        if not q_zero:
            return True
    return False


def etag_matches(if_none_match: str, etag: str) -> bool:
    """Return True when If-None-Match strongly matches `etag` or `*`."""
    if not if_none_match:
        return False
    stripped = if_none_match.strip()
    if stripped == "*":
        return True
    return any(tok.strip() == etag for tok in stripped.split(","))


def build_cached_response(
    raw_bytes: bytes,
    content_type: str,
    req_headers=None,
    cache_control: str = "no-cache",
    compress: bool = True,
    gz_bytes: bytes | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    """Build `(status_code, headers, body)` with strong ETag, gzip, and 304 support."""
    use_gz = bool(compress and accepts_gzip(req_headers))
    digest = hashlib.sha256(raw_bytes).hexdigest()[:16]
    etag = f'"{digest}-gz"' if use_gz else f'"{digest}"'
    inm = _hdr_get(req_headers, "If-None-Match")
    if etag_matches(inm, etag):
        headers = [
            ("ETag", etag),
            ("Cache-Control", cache_control),
            ("Vary", "Accept-Encoding"),
        ]
        return 304, headers, b""

    body = (gz_bytes if gz_bytes is not None else gzip.compress(raw_bytes, compresslevel=6)) if use_gz else raw_bytes
    headers = [
        ("Content-Type", content_type),
        ("Cache-Control", cache_control),
        ("ETag", etag),
        ("Vary", "Accept-Encoding"),
    ]
    if use_gz:
        headers.append(("Content-Encoding", "gzip"))
    return 200, headers, body


# --- Thin File Server -----------------------------------------------------------------------------


def default_web_root() -> str:
    """Locate static web directory: env override, installed path, or repo-relative fallback."""
    env_dir = os.environ.get("PANEL_WEB_DIR", "").strip()
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    if os.path.isdir(INSTALLED_WEB_DIR):
        return INSTALLED_WEB_DIR
    usr_local = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(usr_local, "share", "media-stick", "web")


class StaticAssets:
    """Thread-safe static asset server with mtime-checked gzip + ETag cache."""

    def __init__(self, root: str | None = None):
        self.root = os.path.realpath(root or default_web_root())
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[int, int, bytes, bytes | None, str]] = {}

    def _safe_path(self, rel_path: str) -> str | None:
        candidate = os.path.realpath(os.path.join(self.root, rel_path))
        if candidate == self.root or not candidate.startswith(self.root + os.sep):
            return None
        return candidate

    def _load(self, rel_path: str) -> tuple[bytes, bytes | None, str] | None:
        full_path = self._safe_path(rel_path)
        if full_path is None:
            return None
        try:
            st = os.stat(full_path)
        except OSError:
            return None
        if not os.path.isfile(full_path):
            return None

        with self._lock:
            entry = self._cache.get(rel_path)
            if entry is not None and entry[0] == st.st_mtime_ns and entry[1] == st.st_size:
                return entry[2], entry[3], entry[4]

        try:
            with open(full_path, "rb") as f:
                raw = f.read()
        except OSError:
            return None

        _, compressible = mime_type_for(rel_path)
        gz = gzip.compress(raw, compresslevel=6) if compressible else None
        ver = hashlib.sha256(raw).hexdigest()[:12]
        with self._lock:
            self._cache[rel_path] = (st.st_mtime_ns, st.st_size, raw, gz, ver)
        return raw, gz, ver

    def asset_version(self, rel_path: str) -> str:
        """Return short content hash for a static asset, or empty string if missing."""
        loaded = self._load(rel_path)
        return loaded[2] if loaded is not None else ""

    def serve(self, url_path: str, headers=None) -> tuple[int, list[tuple[str, str]], bytes]:
        """Serve a static asset, returning `(status_code, headers, body)`."""
        rel_path = resolve_asset_rel(url_path)
        if rel_path is None:
            return 403, [("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")], b"forbidden"

        if self._safe_path(rel_path) is None:
            return 403, [("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")], b"forbidden"

        loaded = self._load(rel_path)
        if loaded is None:
            return 404, [("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")], b"not found"

        raw, gz, _ = loaded
        ctype, compressible = mime_type_for(rel_path)
        cc = cache_control_for(url_path, rel_path)
        return build_cached_response(
            raw,
            ctype,
            req_headers=headers,
            cache_control=cc,
            compress=compressible,
            gz_bytes=gz,
        )


def serve_static(url_path: str, headers=None, root: str | None = None) -> tuple[int, list[tuple[str, str]], bytes]:
    """Convenience function to serve a single static path."""
    return StaticAssets(root=root).serve(url_path, headers=headers)
