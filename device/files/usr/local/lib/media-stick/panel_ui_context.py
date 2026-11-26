"""Thin I/O shell for TV UI context tmpfs persistence, watching, and Kodi command dispatch."""
import json
import os
import tempfile
import threading

from mediastick_onboarding import Refused
from mediastick_ui_context import empty_context, normalize_context, validate_cmd

CONTEXT_PATH = "/run/media-stick/ui-context.json"
MAX_FILE_BYTES = 16384
POLL_ACTIVE_INTERVAL = 0.2
POLL_PASSIVE_INTERVAL = 0.4


def _compact_bytes(doc: dict) -> bytes:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_context(doc, path: str = CONTEXT_PATH) -> bool:
    """Normalize `doc` and atomically write to `path` only if serialized UTF-8 bytes changed."""
    normalized = normalize_context(doc)
    payload = _compact_bytes(normalized)

    try:
        if os.path.isfile(path) and not os.path.islink(path):
            with open(path, "rb") as f:
                existing = f.read(MAX_FILE_BYTES + 1)
            if existing == payload:
                return False
    except OSError:
        pass

    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, mode=0o755, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".ui-context-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return True


def read_context(path: str = CONTEXT_PATH) -> dict:
    """Read and validate `path`, returning `empty_context()` on any missing/corrupt/leaking input."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
    except OSError:
        return empty_context()

    if len(raw) > MAX_FILE_BYTES:
        return empty_context()

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, MemoryError):
        return empty_context()

    if not isinstance(data, dict):
        return empty_context()

    try:
        return normalize_context(data)
    except (Refused, ValueError, TypeError):
        return empty_context()


class UiContextWatcher:
    """Background daemon watcher for `/run/media-stick/ui-context.json`.

    Wakes immediately on `notify()` (e.g. `Other.mediastick.ui_context` from KodiBus).
    Polls `st_mtime_ns` / `st_size` every 0.2s while `ws_count() > 0`, and stays
    passive (no disk reads) when `ws_count() == 0`.
    """

    def __init__(
        self,
        path: str = CONTEXT_PATH,
        ws_count=None,
        on_change=None,
        poll_interval: float = POLL_ACTIVE_INTERVAL,
    ):
        self.path = path
        self._ws_count = ws_count or (lambda: 0)
        self._on_change = on_change
        self._poll_interval = max(0.05, float(poll_interval))

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._notify_lock = threading.Lock()
        self._notified = False
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None

        self._last_stat: tuple[int, int, int] | None = None
        self._last_bytes: bytes | None = None

    def start(self) -> None:
        """Start the watcher daemon thread (idempotent)."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="ui-context-watcher", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the watcher daemon thread."""
        self._stop.set()
        self._wake.set()
        with self._state_lock:
            t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=timeout)

    def notify(self) -> None:
        """Wake the watcher immediately to inspect the context file."""
        with self._notify_lock:
            self._notified = True
            self._wake.set()

    def _safe_ws_count(self) -> int:
        try:
            return int(self._ws_count())
        except Exception:
            return 0

    def _check_file(self) -> None:
        try:
            st = os.stat(self.path)
        except OSError:
            if self._last_bytes is not None:
                ctx = empty_context()
                encoded = _compact_bytes(ctx)
                self._last_stat = None
                if encoded != self._last_bytes:
                    self._last_bytes = encoded
                    self._emit(ctx)
            return

        stat_key = (st.st_mtime_ns, st.st_size, st.st_ino)
        if stat_key == self._last_stat and self._last_bytes is not None:
            return

        ctx = read_context(self.path)
        encoded = _compact_bytes(ctx)
        self._last_stat = stat_key
        if encoded != self._last_bytes:
            self._last_bytes = encoded
            self._emit(ctx)

    def _emit(self, ctx: dict) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(ctx)
        except Exception:
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._notify_lock:
                notified = self._notified
                self._notified = False
                self._wake.clear()

            active = self._safe_ws_count() > 0
            if notified or active:
                self._check_file()

            timeout = self._poll_interval if active else POLL_PASSIVE_INTERVAL
            self._wake.wait(timeout=timeout)


def dispatch_ui_cmd(raw, kodi_call) -> dict:
    """Validate a Phone -> TV command and dispatch it via `JSONRPC.NotifyAll`."""
    cmd = validate_cmd(raw)
    kodi_call(
        "JSONRPC.NotifyAll",
        {
            "sender": "media-stick.panel",
            "message": "mediastick.ui_cmd",
            "data": cmd,
        },
    )
    return cmd
