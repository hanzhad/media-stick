"""Pure stdlib RFC 6455 WebSocket handshake, frame codec, and client broadcast hub.

Pure Core:
  - handshake_accept, validate_ws_headers, build_handshake_response
  - decode_pointer_frame (9-byte `<Bff` binary pointer frames), encode_frame

Thin I/O Shell:
  - read_frame, WsHub (thread-safe broadcast + dead-client pruning + client loop)
"""
import base64
import hashlib
import json
import math
import struct
import threading
from urllib.parse import urlparse

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

POINTER_OPS = frozenset({1, 2, 3, 4})  # 1=move_by, 2=click, 3=right, 4=scroll
MAX_WS_PAYLOAD = 65536


# --- Pure Core ------------------------------------------------------------------------------------


def _hdr_get(headers, name: str) -> str:
    target = name.lower()
    if hasattr(headers, "items"):
        for k, v in headers.items():
            if str(k).lower() == target:
                return str(v).strip()
    return ""


def handshake_accept(sec_websocket_key: str) -> str:
    """Compute RFC 6455 Sec-WebSocket-Accept header value."""
    raw = (sec_websocket_key.strip() + WS_GUID).encode("ascii")
    return base64.b64encode(hashlib.sha1(raw).digest()).decode("ascii")


def validate_ws_headers(headers, public_host: str = "") -> bool:
    """Validate RFC 6455 upgrade headers and same-origin policy."""
    upgrade = _hdr_get(headers, "Upgrade").lower()
    if "websocket" not in upgrade:
        return False

    conn_tokens = {tok.strip() for tok in _hdr_get(headers, "Connection").lower().split(",") if tok.strip()}
    if "upgrade" not in conn_tokens:
        return False

    if _hdr_get(headers, "Sec-WebSocket-Version") != "13":
        return False

    key = _hdr_get(headers, "Sec-WebSocket-Key")
    if not key:
        return False
    try:
        if len(base64.b64decode(key, validate=True)) != 16:
            return False
    except Exception:
        return False

    host = _hdr_get(headers, "Host").lower()
    if not host:
        return False

    origin = _hdr_get(headers, "Origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        origin_netloc = parsed.netloc.lower()
        if origin_netloc != host:
            if not (public_host and (parsed.hostname or "").lower() == public_host.lower()):
                return False

    return True


def build_handshake_response(sec_websocket_key: str) -> bytes:
    """Build raw HTTP/1.1 101 Switching Protocols response bytes."""
    accept = handshake_accept(sec_websocket_key)
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    ).encode("ascii")


def decode_pointer_frame(data: bytes) -> tuple[int, float, float]:
    """Decode a 9-byte `<Bff` pointer frame into `(opcode, dx, dy)`."""
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) != 9:
        raise ValueError("pointer frame must be exactly 9 bytes")
    op, dx, dy = struct.unpack("<Bff", data)
    if op not in POINTER_OPS:
        raise ValueError(f"invalid pointer opcode: {op}")
    if not (math.isfinite(dx) and math.isfinite(dy)):
        raise ValueError("non-finite pointer coordinate")
    return op, dx, dy


def encode_frame(opcode: int, payload: bytes | str = b"") -> bytes:
    """Encode an unmasked server->client RFC 6455 frame."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    b0 = 0x80 | (opcode & 0x0F)
    n = len(payload)
    if n < 126:
        hdr = struct.pack("!BB", b0, n)
    elif n < 65536:
        hdr = struct.pack("!BBH", b0, 126, n)
    else:
        hdr = struct.pack("!BBQ", b0, 127, n)
    return hdr + payload


# --- Thin I/O Shell -------------------------------------------------------------------------------


def _recv_exact(sock, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock, max_payload: int = MAX_WS_PAYLOAD) -> tuple[int, bytes] | None:
    """Read a single RFC 6455 frame from `sock`, returning `(opcode, payload)` or None on EOF."""
    hdr = _recv_exact(sock, 2)
    if hdr is None:
        return None
    b0, b1 = struct.unpack("!BB", hdr)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F

    if length == 126:
        ext = _recv_exact(sock, 2)
        if ext is None:
            return None
        (length,) = struct.unpack("!H", ext)
    elif length == 127:
        ext = _recv_exact(sock, 8)
        if ext is None:
            return None
        (length,) = struct.unpack("!Q", ext)

    if length > max_payload:
        raise ValueError(f"websocket payload too large: {length}")

    mask_key = b""
    if masked:
        mask_key = _recv_exact(sock, 4)
        if mask_key is None:
            return None

    payload = _recv_exact(sock, length) if length else b""
    if payload is None:
        return None

    if masked and length:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

    return opcode, payload


class WsHub:
    """Thread-safe WebSocket client registry and broadcast hub."""

    def __init__(self):
        self._lock = threading.Lock()
        self._clients: set = set()
        self._send_locks: dict = {}

    def add(self, sock) -> None:
        with self._lock:
            self._clients.add(sock)
            self._send_locks[sock] = threading.Lock()

    def remove(self, sock) -> None:
        with self._lock:
            self._clients.discard(sock)
            self._send_locks.pop(sock, None)

    def count(self) -> int:
        with self._lock:
            return len(self._clients)

    def _send_frame(self, sock, frame: bytes) -> bool:
        with self._lock:
            slock = self._send_locks.get(sock)
        if slock is None:
            return False
        try:
            with slock:
                sock.sendall(frame)
            return True
        except (OSError, ValueError):
            self.remove(sock)
            try:
                sock.close()
            except OSError:
                pass
            return False

    def send_json(self, sock, obj) -> bool:
        return self._send_frame(sock, encode_frame(OP_TEXT, json.dumps(obj)))

    def broadcast(self, message) -> None:
        """Broadcast JSON dict/list, UTF-8 text, or binary frame to all connected clients."""
        if isinstance(message, (dict, list)):
            frame = encode_frame(OP_TEXT, json.dumps(message))
        elif isinstance(message, str):
            frame = encode_frame(OP_TEXT, message)
        else:
            frame = encode_frame(OP_BINARY, bytes(message))

        with self._lock:
            targets = list(self._clients)
        for sock in targets:
            self._send_frame(sock, frame)

    def serve_client(self, sock, on_text=None, on_pointer=None, idle_timeout: float = 120.0) -> None:
        """Read and dispatch RFC 6455 frames until client closes or errors."""
        self.add(sock)
        try:
            sock.settimeout(idle_timeout)
            while True:
                try:
                    frame = read_frame(sock)
                except (OSError, ValueError):
                    break
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == OP_CLOSE:
                    self._send_frame(sock, encode_frame(OP_CLOSE, b""))
                    break
                if opcode == OP_PING:
                    self._send_frame(sock, encode_frame(OP_PONG, payload[:125]))
                    continue
                if opcode == OP_PONG:
                    continue
                if opcode == OP_BINARY:
                    try:
                        op, dx, dy = decode_pointer_frame(payload)
                    except ValueError:
                        continue
                    if on_pointer is not None:
                        try:
                            on_pointer(op, dx, dy)
                        except Exception:
                            pass
                elif opcode == OP_TEXT:
                    if on_text is not None:
                        try:
                            msg = json.loads(payload.decode("utf-8"))
                        except (UnicodeDecodeError, ValueError):
                            continue
                        try:
                            on_text(msg, sock)
                        except Exception:
                            pass
        finally:
            self.remove(sock)
            try:
                sock.close()
            except OSError:
                pass
