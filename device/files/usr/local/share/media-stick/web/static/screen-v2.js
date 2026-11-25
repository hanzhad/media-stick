import { ownerLabel } from './power-banner.js';

const LIVE_MAX_MS = 120000;
const FRAME_GAP_MS = 1000;

export function initScreenV2(opts = {}) {
  const box = opts.box;
  const img = opts.img;
  const stateEl = opts.stateEl;
  const metaEl = opts.metaEl;
  const liveBtn = opts.liveBtn;
  const liveIcon = opts.liveIcon;
  const liveText = opts.liveText;
  const castBanner = opts.castBanner || null;
  const castText = opts.castText || null;
  const returnBtn = opts.returnBtn || null;
  const api = opts.api;
  const toast = typeof opts.toast === 'function' ? opts.toast : () => {};
  const buzz = typeof opts.buzz === 'function' ? opts.buzz : () => {};
  const onGotFrame = typeof opts.onGotFrame === 'function' ? opts.onGotFrame : () => {};
  const onLiveChange = typeof opts.onLiveChange === 'function' ? opts.onLiveChange : () => {};

  if (!box || !img) return null;

  let live = false;
  let liveSince = 0;
  let shotBusy = false;
  let liveTimer = null;
  let gotFrame = false;
  let failed = 0;
  let redo = false;
  let lastObjectUrl = '';

  function setStatus(text, bad = false) {
    if (!gotFrame && stateEl) stateEl.textContent = text;
    if (metaEl) {
      metaEl.textContent = gotFrame ? text : '';
      metaEl.classList.toggle('bad', Boolean(bad));
    }
  }

  function showCastBanner(show, owner = '') {
    if (!castBanner) return;
    castBanner.classList.toggle('hide', !show);
    if (show && castText) {
      castText.textContent = owner ? ownerLabel(owner) : 'Экран занят трансляцией';
    }
    if (show && returnBtn && !returnBtn.textContent) {
      returnBtn.textContent = 'Вернуться в Kodi';
    }
  }

  function setLive(on) {
    live = Boolean(on);
    liveSince = Date.now();
    if (liveText) liveText.textContent = live ? 'Стоп' : 'Показать';
    if (liveIcon) liveIcon.setAttribute('href', live ? '#i-stop' : '#i-play');
    onLiveChange(live);
    if (live) {
      failed = 0;
      showCastBanner(false);
      setStatus('Загрузка…');
      frame();
    } else {
      clearTimeout(liveTimer);
      liveTimer = null;
      setStatus(gotFrame ? 'Остановлено' : 'Нажмите «Показать»');
    }
  }

  async function frame() {
    if (typeof document !== 'undefined' && document.hidden) {
      if (live) setLive(false);
      return;
    }
    if (shotBusy) {
      redo = true;
      return;
    }
    shotBusy = true;
    const t0 = Date.now();
    try {
      const resp = await fetch(`/shot.jpg?${t0}`, { cache: 'no-store' });
      if (resp.status === 409) {
        let owner = '';
        try {
          const ct = (resp.headers.get('content-type') || '').toLowerCase();
          if (ct.includes('json')) {
            const payload = await resp.json();
            owner = payload.owner || '';
          } else {
            const txt = await resp.text();
            if (txt.includes('airplay')) owner = 'airplay';
            else if (txt.includes('miracast')) owner = 'miracast';
          }
        } catch (_) {}
        shotBusy = false;
        redo = false;
        showCastBanner(true, owner);
        setStatus(owner ? ownerLabel(owner) : 'Экран занят трансляцией');
        if (live) setLive(false);
        return;
      }
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      img.onload = () => {
        if (lastObjectUrl && lastObjectUrl !== url) {
          URL.revokeObjectURL(lastObjectUrl);
        }
        lastObjectUrl = url;
        shotBusy = false;
        failed = 0;
        gotFrame = true;
        showCastBanner(false);
        box.classList.add('has');
        onGotFrame();
        if (live) setStatus(`${Date.now() - t0} мс`);
        clearTimeout(liveTimer);
        if (live && !document.hidden && Date.now() - liveSince < LIVE_MAX_MS) {
          liveTimer = setTimeout(frame, FRAME_GAP_MS);
        } else if (live) {
          setLive(false);
        }
        if (redo) {
          redo = false;
          setTimeout(frame, 0);
        }
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        shotBusy = false;
        redo = false;
        setStatus('ТВ не отвечает', true);
      };
      img.src = url;
    } catch (_) {
      shotBusy = false;
      redo = false;
      if (!gotFrame && failed < 1) {
        failed += 1;
        setStatus('Загрузка…');
        setTimeout(frame, 800);
        return;
      }
      setStatus('ТВ не отвечает', true);
      if (live && !document.hidden) {
        liveTimer = setTimeout(frame, 3000);
      }
    }
  }

  if (returnBtn && api) {
    returnBtn.addEventListener('click', async () => {
      buzz();
      try {
        await api('/api/power', { action: 'return_kodi' });
        showCastBanner(false);
        toast('Возвращаю Kodi…');
        setTimeout(() => frame(), 800);
      } catch (e) {
        toast((e && e.message) || 'Не удалось вернуться в Kodi');
      }
    });
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && live) setLive(false);
    });
  }

  return {
    frame,
    setLive,
    isLive: () => live,
    hasFrame: () => gotFrame,
    showCastBanner,
  };
}
