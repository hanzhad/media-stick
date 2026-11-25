"""Persistent JSON-RPC 2.0 TCP client for Kodi (127.0.0.1:9090).

Pure Core:
  - build_request(rid, method, params)
  - decode_messages(buf) -> (messages, remaining_bytes)

Thin I/O Shell:
  - KodiBus: auto-reconnecting TCP client with id-correlated RPC and push subscriber dispatch.
"""
import json
import socket
import threading

PUSH_METHODS = frozenset({
    "Player.OnPlay",
    "Player.OnPause",
    "Player.OnResume",
    "Player.OnStop",
    "Player.OnSeek",
    "Player.OnAVChange",
    "Application.OnVolumeChanged",
    "Input.OnInputRequested",
    "Input.OnInputFinished",
})


class KodiError(RuntimeError):
    """Base error for Kodi JSON-RPC bus failures."""


class KodiRpcError(KodiError):
    """Raised when Kodi responds with a JSON-RPC error object."""

    def __init__(self, error):
        self.error = error
        super().__init__(str(error))


# --- Pure Core ------------------------------------------------------------------------------------


def build_request(rid: int, method: str, params=None) -> bytes:
    """Serialize a JSON-RPC 2.0 request frame."""
    payload = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        payload["params"] = params
    else:
        payload["params"] = {}
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def decode_messages(buf: bytes) -> tuple[list[dict], bytes]:
    """Decode concatenated JSON-RPC objects from `buf`, leaving incomplete trailing bytes."""
    if not buf:
        return [], b""

    valid_end = len(buf)
    text = ""
    while valid_end > 0:
        try:
            text = buf[:valid_end].decode("utf-8")
            break
        except UnicodeDecodeError as exc:
            if exc.end == valid_end:
                valid_end = exc.start
            else:
                text = buf.decode("utf-8", errors="replace")
                valid_end = len(buf)
                break
    else:
        return [], buf

    dec = json.JSONDecoder()
    msgs: list[dict] = []
    pos = 0
    length = len(text)
    while pos < length:
        while pos < length and text[pos].isspace():
            pos += 1
        if pos >= length:
            break
        try:
            obj, end = dec.raw_decode(text, pos)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            msgs.append(obj)
        pos = end

    consumed = len(text[:pos].encode("utf-8"))
    return msgs, buf[consumed:]


# --- Thin I/O Shell -------------------------------------------------------------------------------


class KodiBus:
    """Persistent auto-reconnecting JSON-RPC 2.0 TCP client for Kodi."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9090,
        timeout: float = 3.0,
        reconnect_delay: float = 0.5,
        connect_fn=None,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.reconnect_delay = reconnect_delay
        self._connect_fn = connect_fn or socket.create_connection

        self._stop = threading.Event()
        self._connected = threading.Event()
        self._connect_attempted = threading.Event()
        self._had_connection = False
        self._last_error = None

        self._state_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._sub_lock = threading.Lock()

        self._sock = None
        self._rid = 0
        self._pending: dict[int, tuple[threading.Event, dict]] = {}
        self._subscribers: list = []
        self._thread: threading.Thread | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def subscribe(self, callback) -> None:
        """Register a push notification callback `(method, params)`."""
        with self._sub_lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        with self._sub_lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def start(self) -> None:
        """Start the background I/O & reconnect thread (idempotent)."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._io_loop, name="kodi-bus", daemon=True)
            self._thread.start()

    def close(self) -> None:
        """Stop the bus, close the socket, and wake any pending callers."""
        self._stop.set()
        self._connected.clear()
        self._connect_attempted.set()
        self._drop_socket(KodiError("kodi bus closed"))
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=1.0)

    def _drop_socket(self, exc: Exception) -> None:
        with self._state_lock:
            sock = self._sock
            self._sock = None
            pending = list(self._pending.values())
            self._pending.clear()
        self._connected.clear()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        for ev, box in pending:
            box["exc"] = exc
            ev.set()

    def _dispatch_notification(self, method: str, params) -> None:
        with self._sub_lock:
            subs = list(self._subscribers)
        for sub in subs:
            try:
                sub(method, params)
            except Exception:
                pass

    def _io_loop(self) -> None:
        while not self._stop.is_set():
            try:
                sock = self._connect_fn((self.host, self.port), timeout=self.timeout)
                sock.settimeout(0.5)
            except OSError as exc:
                self._last_error = exc
                self._connected.clear()
                self._connect_attempted.set()
                self._stop.wait(self.reconnect_delay)
                continue

            with self._state_lock:
                if self._stop.is_set():
                    try:
                        sock.close()
                    except OSError:
                        pass
                    break
                self._sock = sock
                self._last_error = None
                self._had_connection = True
            self._connected.set()
            self._connect_attempted.set()

            buf = b""
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError as exc:
                    self._last_error = exc
                    break
                if not chunk:
                    self._last_error = OSError("kodi closed connection")
                    break
                msgs, buf = decode_messages(buf + chunk)
                for obj in msgs:
                    if "id" in obj and "method" not in obj:
                        with self._state_lock:
                            entry = self._pending.pop(obj["id"], None)
                        if entry is not None:
                            ev, box = entry
                            box["msg"] = obj
                            ev.set()
                    elif "method" in obj:
                        self._dispatch_notification(obj["method"], obj.get("params"))

            self._drop_socket(self._last_error or OSError("kodi disconnected"))
            if not self._stop.is_set():
                self._stop.wait(self.reconnect_delay)

    def _ensure_connected(self, timeout: float):
        if not self._connected.is_set():
            if not self._connect_attempted.is_set():
                self._connect_attempted.wait(timeout)
            if not self._connected.is_set() and self._had_connection:
                wait_s = min(timeout, max(0.2, self.reconnect_delay * 5))
                self._connected.wait(wait_s)
        with self._state_lock:
            sock = self._sock
        if sock is None:
            raise self._last_error or OSError("kodi not connected")
        return sock

    def call(self, method: str, params=None, timeout: float | None = None):
        """Send a JSON-RPC 2.0 request and wait for its correlated reply."""
        eff_timeout = self.timeout if timeout is None else timeout
        for attempt in range(2):
            ev = threading.Event()
            box: dict = {}

            with self._send_lock:
                sock = self._ensure_connected(eff_timeout)
                with self._state_lock:
                    self._rid += 1
                    rid = self._rid
                    self._pending[rid] = (ev, box)
                raw = build_request(rid, method, params)
                try:
                    sock.sendall(raw)
                except OSError as exc:
                    with self._state_lock:
                        self._pending.pop(rid, None)
                    self._drop_socket(exc)
                    if attempt == 0 and not self._stop.is_set():
                        continue
                    raise

            if not ev.wait(eff_timeout):
                with self._state_lock:
                    self._pending.pop(rid, None)
                raise TimeoutError(f"kodi RPC timeout for {method}")

            if "exc" in box:
                if attempt == 0 and not self._stop.is_set() and isinstance(box["exc"], OSError):
                    continue
                raise box["exc"]
            msg = box["msg"]
            if "error" in msg:
                raise KodiRpcError(msg["error"])
            return msg.get("result")
