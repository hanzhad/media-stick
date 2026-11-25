import { OP_MOVE_BY, OP_CLICK, OP_RIGHT, OP_SCROLL } from './ws-client.js';

const MOVE_MAX = 0.25;
const SLOP_PX = 8;
const LONG_PRESS_MS = 480;
const SCROLL_STEP_PX = 20;
const REST_MOVE_GAP_MS = 32;

function clampDelta(v) {
  return Math.max(-MOVE_MAX, Math.min(MOVE_MAX, v));
}

async function postPointer(api, payload) {
  if (typeof api === 'function') {
    return api('/api/pointer', payload);
  }
  const res = await fetch('/api/pointer', {
    method: 'POST',
    headers: { 'X-Panel': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = new Error(await res.text());
    err.http = res.status;
    throw err;
  }
  return res.json();
}

export function initTrackpad(opts = {}) {
  const pad = opts.pad;
  if (!pad) return null;

  const ws = opts.ws || null;
  const api = opts.api || null;
  const buzz = typeof opts.buzz === 'function' ? opts.buzz : () => {};
  const onNote = typeof opts.onNote === 'function' ? opts.onNote : () => {};
  const onAfterClick = typeof opts.onAfterClick === 'function' ? opts.onAfterClick : () => {};
  const sensInput = opts.sensInput || null;

  let sens = 5;
  try {
    const saved = parseInt(localStorage.getItem('tpSens'), 10);
    if (saved >= 1 && saved <= 10) sens = saved;
  } catch (_) {}
  if (sensInput) {
    sensInput.value = String(sens);
    sensInput.addEventListener('input', (e) => {
      const val = parseInt(e.target.value, 10);
      if (val >= 1 && val <= 10) {
        sens = val;
        try {
          localStorage.setItem('tpSens', String(sens));
        } catch (_) {}
      }
    });
  }

  const pointers = new Map();
  let state = null;
  let restBusy = false;
  let restLast = 0;
  let restTimer = null;
  const pendingMove = { dx: 0, dy: 0 };

  function gainFactor() {
    return 0.8 + sens * 0.24;
  }

  function sendMove(dx, dy) {
    const fx = clampDelta(dx);
    const fy = clampDelta(dy);
    if (Math.abs(fx) < 1e-5 && Math.abs(fy) < 1e-5) return;
    if (ws && ws.sendPointer(OP_MOVE_BY, fx, fy)) {
      return;
    }
    pendingMove.dx += fx;
    pendingMove.dy += fy;
    flushRestMove();
  }

  function flushRestMove() {
    if (restBusy) return;
    const wait = REST_MOVE_GAP_MS - (performance.now() - restLast);
    if (wait > 0) {
      if (!restTimer) {
        restTimer = setTimeout(() => {
          restTimer = null;
          flushRestMove();
        }, wait);
      }
      return;
    }
    if (Math.abs(pendingMove.dx) < 1e-5 && Math.abs(pendingMove.dy) < 1e-5) return;
    const dx = clampDelta(pendingMove.dx);
    const dy = clampDelta(pendingMove.dy);
    pendingMove.dx -= dx;
    pendingMove.dy -= dy;
    restBusy = true;
    restLast = performance.now();
    postPointer(api, { action: 'move_by', dx, dy })
      .catch((e) => onNote(e && e.message ? e.message : 'Указка не ответила', true))
      .finally(() => {
        restBusy = false;
        if (Math.abs(pendingMove.dx) > 1e-5 || Math.abs(pendingMove.dy) > 1e-5) {
          flushRestMove();
        }
      });
  }

  function sendAction(action, op, dy = 0) {
    if (op === OP_SCROLL && ws && ws.sendPointer(OP_SCROLL, 0, dy)) {
      return;
    }
    if ((op === OP_CLICK || op === OP_RIGHT) && ws && ws.sendPointer(op, 0, 0)) {
      onAfterClick(action);
      return;
    }
    const body = action === 'scroll' ? { action: 'scroll', dy } : { action, here: true };
    postPointer(api, body)
      .then(() => {
        if (action === 'click' || action === 'right') onAfterClick(action);
      })
      .catch((e) => onNote(e && e.message ? e.message : 'Указка не ответила', true));
  }

  function avgPoint() {
    let sx = 0;
    let sy = 0;
    let n = 0;
    for (const p of pointers.values()) {
      sx += p.x;
      sy += p.y;
      n += 1;
    }
    return n ? { x: sx / n, y: sy / n } : { x: 0, y: 0 };
  }

  function clearHoldTimer() {
    if (state && state.holdTimer) {
      clearTimeout(state.holdTimer);
      state.holdTimer = null;
    }
  }

  pad.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0 && e.button !== 2) return;
    e.preventDefault();
    try {
      pad.setPointerCapture(e.pointerId);
    } catch (_) {}
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    pad.classList.add('on');

    if (pointers.size === 1) {
      state = {
        startX: e.clientX,
        startY: e.clientY,
        lastX: e.clientX,
        lastY: e.clientY,
        moved: false,
        twoFinger: false,
        longFired: false,
        rightBtn: e.pointerType === 'mouse' && e.button === 2,
        scrollAcc: 0,
        lastTwoY: e.clientY,
        holdTimer: null,
      };
      if (e.pointerType !== 'mouse') {
        state.holdTimer = setTimeout(() => {
          if (state && !state.moved && !state.twoFinger && pointers.size === 1) {
            state.longFired = true;
            buzz();
            sendAction('right', OP_RIGHT);
          }
        }, LONG_PRESS_MS);
      }
    } else if (pointers.size >= 2 && state) {
      clearHoldTimer();
      state.twoFinger = true;
      state.moved = true;
      state.lastTwoY = avgPoint().y;
      state.scrollAcc = 0;
    }
  });

  pad.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId) || !state) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (state.twoFinger && pointers.size >= 2) {
      const avg = avgPoint();
      const dyPx = avg.y - state.lastTwoY;
      state.lastTwoY = avg.y;
      state.scrollAcc += dyPx;
      const steps = Math.trunc(state.scrollAcc / SCROLL_STEP_PX);
      if (steps) {
        state.scrollAcc -= steps * SCROLL_STEP_PX;
        sendAction('scroll', OP_SCROLL, steps);
      }
      return;
    }

    if (pointers.size === 1 && !state.twoFinger && !state.longFired) {
      const totalDist = Math.hypot(e.clientX - state.startX, e.clientY - state.startY);
      if (!state.moved && totalDist > SLOP_PX) {
        state.moved = true;
        clearHoldTimer();
      }
      if (state.moved) {
        const w = Math.max(120, pad.clientWidth || 280);
        const h = Math.max(120, pad.clientHeight || 200);
        const g = gainFactor();
        const dx = ((e.clientX - state.lastX) / w) * g;
        const dy = ((e.clientY - state.lastY) / h) * g;
        state.lastX = e.clientX;
        state.lastY = e.clientY;
        sendMove(dx, dy);
      }
    }
  });

  function finishPointer(e, cancel) {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (pointers.size === 0) {
      pad.classList.remove('on');
    }
    if (!state || pointers.size > 0) return;

    clearHoldTimer();
    const cur = state;
    state = null;
    if (!cancel && !cur.twoFinger && !cur.moved && !cur.longFired) {
      buzz();
      if (cur.rightBtn) {
        sendAction('right', OP_RIGHT);
      } else {
        sendAction('click', OP_CLICK);
      }
    }
  }

  pad.addEventListener('pointerup', (e) => finishPointer(e, false));
  pad.addEventListener('pointercancel', (e) => finishPointer(e, true));
  pad.addEventListener('contextmenu', (e) => e.preventDefault());
  pad.addEventListener('wheel', (e) => {
    e.preventDefault();
    const steps = e.deltaY > 0 ? -1 : e.deltaY < 0 ? 1 : 0;
    if (steps) sendAction('scroll', OP_SCROLL, steps);
  }, { passive: false });

  return {
    reset() {
      clearHoldTimer();
      pointers.clear();
      state = null;
      pad.classList.remove('on');
    },
  };
}
