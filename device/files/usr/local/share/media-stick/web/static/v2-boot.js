import { WsClient } from './ws-client.js';
import { initTrackpad } from './trackpad.js';
import { initPowerBanner } from './power-banner.js';
import { initScreenV2 } from './screen-v2.js';
import { initDiagnostics } from './diagnostics.js';
import { initTouchBar } from './touchbar.js';

function byId(id) {
  return document.getElementById(id);
}

function registerSw() {
  if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
}

function boot() {
  registerSw();

  const api = window.api;
  const toast = window.toast || (() => {});
  const buzz = window.buzz || (() => {});

  const ws = new WsClient({ path: '/ws' });

  const powerBanner = initPowerBanner({
    bannerEl: byId('cast-banner'),
    labelEl: byId('cast-label'),
    returnBtn: byId('cast-return'),
    standbyBtn: byId('cec-standby'),
    wakeBtn: byId('cec-wake'),
    api,
    toast,
    buzz,
    onAfterAction: () => {
      if (typeof window.tick === 'function') {
        setTimeout(() => window.tick(), 600);
      }
    },
  });

  const screenV2 = initScreenV2({
    box: byId('shot-box'),
    img: byId('shot'),
    stateEl: byId('shot-s'),
    metaEl: byId('shot-ms'),
    liveBtn: byId('live-btn'),
    liveIcon: byId('live-ic'),
    liveText: byId('live-t'),
    castBanner: byId('shot-cast'),
    castText: byId('shot-cast-t'),
    returnBtn: byId('shot-cast-ret'),
    saveBtns: [byId('shot-save-act'), byId('shot-save-btn'), byId('f-shot')].filter(Boolean),
    shotSheet: byId('shot-sheet'),
    shotSheetBack: byId('shot-sheet-back'),
    shotSheetImg: byId('shot-sheet-img'),
    shotSheetShare: byId('shot-sheet-share'),
    shotSheetDl: byId('shot-sheet-dl'),
    shotSheetClose: byId('shot-sheet-close'),
    api,
    toast,
    buzz,
    onGotFrame: () => {
      window.gotFrame = true;
    },
    onLiveChange: (on) => {
      window.live = on;
    },
  });

  if (screenV2) {
    window.__screenV2 = screenV2;
    window.frame = () => screenV2.frame();
    window.setLive = (on) => screenV2.setLive(on);
  }

  const trackpad = initTrackpad({
    pad: byId('tp-pad'),
    sensInput: byId('tp-k'),
    ws,
    api,
    buzz,
    onNote: (msg, bad) => {
      const h = byId('tp-h');
      if (h) {
        h.textContent = msg;
        h.classList.toggle('bad', Boolean(bad));
      }
    },
    onAfterClick: () => {
      if (screenV2 && screenV2.isLive()) {
        setTimeout(() => screenV2.frame(), 380);
      }
      if (typeof window.tick === 'function') {
        setTimeout(() => window.tick(), 900);
      }
    },
  });

  const diagnostics = initDiagnostics({
    unitSel: byId('diag-unit'),
    loadBtn: byId('diag-load'),
    logOut: byId('diag-out'),
    pinStateEl: byId('pin-state'),
    pinInput: byId('pin-in'),
    pinSetBtn: byId('pin-set'),
    pinOffBtn: byId('pin-off'),
    pinModal: byId('pin-modal'),
    pinModalBack: byId('pin-modal-back'),
    pinModalInput: byId('pin-modal-in'),
    pinModalErr: byId('pin-modal-err'),
    pinModalSubmit: byId('pin-modal-ok'),
    api,
    toast,
    buzz,
    onUnlocked: () => {
      ws.reconnectNow();
      if (typeof window.tick === 'function') window.tick();
    },
  });

  const touchbar = initTouchBar({
    root: byId('touchbar'),
    ws,
    api,
    toast,
    buzz,
    onSearch: () => {
      if (typeof window.openCtxSearch === 'function') window.openCtxSearch();
    },
    onContext: (ctx) => {
      window.__uiCtx = ctx;
    },
  });

  ws.on('now', () => {
    if (typeof window.tick === 'function') window.tick();
  });
  ws.on('vol', () => {
    if (typeof window.hdrDraw === 'function') window.hdrDraw();
  });
  ws.on('kb', (ev) => {
    if (ev && ev.method === 'Input.OnInputFinished') {
      if (typeof window.kbUi === 'function') window.kbUi(null);
    } else if (typeof window.tick === 'function') {
      window.tick();
    }
  });
  ws.on('screen_owner', (data) => {
    const owner = typeof data === 'string' ? data : (data && (data.screen || data.owner)) || '';
    if (powerBanner) powerBanner.updateScreen(owner);
  });
  ws.on('status', (st) => {
    if (powerBanner && st && typeof st.screen === 'string') {
      powerBanner.updateScreen(st.screen);
    }
    if (typeof window.hdrDraw === 'function') window.hdrDraw();
  });
  let wsCtxSeen = false;
  ws.on('ui_context', (ctx) => {
    wsCtxSeen = true;
    window.__uiCtx = ctx;
  });

  window.addEventListener('panel:status', (e) => {
    const st = e.detail;
    if (powerBanner) powerBanner.updateScreen((st && st.screen) || '');
  });

  fetch('/api/ui/context', { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((ctx) => {
      if (!wsCtxSeen && ctx && typeof ctx === 'object' && touchbar) touchbar.update(ctx);
    })
    .catch(() => {});

  ws.connect();
  window.panelV2 = { ws, trackpad, powerBanner, screenV2, diagnostics, touchbar };
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
