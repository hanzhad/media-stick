export const OP_MOVE_BY = 1;
export const OP_CLICK = 2;
export const OP_RIGHT = 3;
export const OP_SCROLL = 4;

/**
 * Encode a 9-byte little-endian `<Bff` pointer/trackpad frame: (opcode, dx, dy).
 */
export function encodePointerFrame(opcode, dx = 0, dy = 0) {
  const buf = new ArrayBuffer(9);
  const view = new DataView(buf);
  view.setUint8(0, opcode & 0xff);
  view.setFloat32(1, Number.isFinite(dx) ? dx : 0, true);
  view.setFloat32(5, Number.isFinite(dy) ? dy : 0, true);
  return buf;
}

export class WsClient {
  constructor(options = {}) {
    this.path = options.path || '/ws';
    this.minDelayMs = options.minDelayMs || 500;
    this.maxDelayMs = options.maxDelayMs || 15000;
    this.pingIntervalMs = options.pingIntervalMs || 30000;
    this.ws = null;
    this.attempt = 0;
    this.closed = false;
    this.reconnectTimer = null;
    this.pingTimer = null;
    this.listeners = new Map();
    this._onVis = () => {
      if (!document.hidden && !this.closed && !this.isOpen()) {
        this.attempt = 0;
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
        this.connect();
      }
    };
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', this._onVis);
    }
  }

  on(event, fn) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event).add(fn);
    return () => this.off(event, fn);
  }

  off(event, fn) {
    const set = this.listeners.get(event);
    if (set) set.delete(fn);
  }

  emit(event, detail) {
    const set = this.listeners.get(event);
    if (!set) return;
    for (const fn of set) {
      try {
        fn(detail);
      } catch (_) {}
    }
  }

  wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    return `${proto}${location.host}${this.path}`;
  }

  isOpen() {
    return !!(this.ws && this.ws.readyState === WebSocket.OPEN);
  }

  connect() {
    if (this.closed) return;
    if (typeof WebSocket === 'undefined') return;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;

    let sock;
    try {
      sock = new WebSocket(this.wsUrl());
      sock.binaryType = 'arraybuffer';
    } catch (_) {
      this._scheduleReconnect();
      return;
    }
    this.ws = sock;

    sock.addEventListener('open', () => {
      if (this.ws !== sock) return;
      this.attempt = 0;
      this._startPing();
      this.emit('open', {});
    });

    sock.addEventListener('message', (ev) => {
      if (this.ws !== sock || typeof ev.data !== 'string') return;
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (_) {
        return;
      }
      if (!msg || typeof msg !== 'object') return;
      this._dispatchMessage(msg);
    });

    sock.addEventListener('close', () => {
      if (this.ws !== sock) return;
      this.ws = null;
      this._stopPing();
      this.emit('close', {});
      this._scheduleReconnect();
    });

    sock.addEventListener('error', () => {
      this.emit('error', {});
    });
  }

  _dispatchMessage(msg) {
    const t = msg.type;
    if (t === 'kodi') {
      const m = String(msg.method || '');
      const p = msg.params || {};
      this.emit('kodi', msg);
      if (m.startsWith('Player.')) {
        this.emit('now', { method: m, params: p });
      } else if (m === 'Application.OnVolumeChanged') {
        this.emit('vol', p);
      } else if (m === 'Input.OnInputRequested' || m === 'Input.OnInputFinished') {
        this.emit('kb', { method: m, params: p });
      }
      return;
    }
    if (t === 'now' || t === 'vol' || t === 'kb' || t === 'screen_owner' || t === 'status') {
      this.emit(t, msg.data !== undefined ? msg.data : msg);
    }
  }

  _startPing() {
    this._stopPing();
    this.pingTimer = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      this.sendJson({ type: 'ping' });
    }, this.pingIntervalMs);
  }

  _stopPing() {
    clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  _scheduleReconnect() {
    if (this.closed) return;
    if (typeof document !== 'undefined' && document.hidden) return;
    const base = Math.min(this.maxDelayMs, this.minDelayMs * Math.pow(2, this.attempt));
    const jitter = Math.floor(Math.random() * Math.min(500, base * 0.25));
    this.attempt += 1;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), base + jitter);
  }

  reconnectNow() {
    this.attempt = 0;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.ws) {
      try {
        this.ws.close();
      } catch (_) {}
      this.ws = null;
    }
    this.connect();
  }

  sendPointer(opcode, dx = 0, dy = 0) {
    if (!this.isOpen()) return false;
    try {
      this.ws.send(encodePointerFrame(opcode, dx, dy));
      return true;
    } catch (_) {
      return false;
    }
  }

  sendJson(obj) {
    if (!this.isOpen()) return false;
    try {
      this.ws.send(JSON.stringify(obj));
      return true;
    } catch (_) {
      return false;
    }
  }

  close() {
    this.closed = true;
    clearTimeout(this.reconnectTimer);
    this._stopPing();
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this._onVis);
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch (_) {}
      this.ws = null;
    }
  }
}
