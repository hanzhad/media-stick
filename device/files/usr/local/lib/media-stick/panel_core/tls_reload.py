"""Hot-reloading TLS SSLContext via sni_callback watching cert/key mtime.

Pure Core:
  - stat_fingerprint(crt_path, key_path)

Thin I/O Shell:
  - TlsReloader: reloads SSLContext when fullchain.pem or key.pem mtime/inode changes
    so certificate renewals never drop connections or restart panel.service.
"""
import os
import ssl
import threading


# --- Pure Core ------------------------------------------------------------------------------------


def _stat_key(path: str) -> tuple[int, int, int] | None:
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_ino, st.st_size)
    except OSError:
        return None


def stat_fingerprint(crt_path: str, key_path: str) -> tuple | None:
    """Return comparable (crt_stat, key_stat) tuple or None if either file is missing."""
    crt = _stat_key(crt_path)
    key = _stat_key(key_path)
    if crt is None or key is None:
        return None
    return (crt, key)


# --- Thin I/O Shell -------------------------------------------------------------------------------


class TlsReloader:
    """Thread-safe hot-reloading TLS context holder using `SSLContext.sni_callback`."""

    def __init__(self, crt_path: str, key_path: str):
        self.crt_path = crt_path
        self.key_path = key_path
        self._lock = threading.Lock()
        self._stamp = stat_fingerprint(crt_path, key_path)
        self._ctx = self._build_context()

    def _build_context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.crt_path, self.key_path)
        ctx.sni_callback = self._sni_callback
        return ctx

    def _sni_callback(self, ssl_sock, _server_name, _initial_ctx) -> None:
        self.maybe_reload()
        ssl_sock.context = self.context

    @property
    def context(self) -> ssl.SSLContext:
        with self._lock:
            return self._ctx

    def maybe_reload(self) -> bool:
        """Reload SSLContext if cert or key mtime/inode changed; return True if swapped."""
        with self._lock:
            current = stat_fingerprint(self.crt_path, self.key_path)
            if current is None or current == self._stamp:
                return False
            try:
                new_ctx = self._build_context()
            except (OSError, ssl.SSLError):
                return False
            self._ctx = new_ctx
            self._stamp = current
            return True
