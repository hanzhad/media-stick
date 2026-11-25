const OWNER_LABELS = {
  airplay: 'Сейчас на экране: AirPlay',
  miracast: 'Сейчас на экране: Miracast',
  'web-app': 'Сейчас на экране: веб-приложение',
};

export function ownerLabel(owner) {
  return OWNER_LABELS[owner] || 'Экран занят трансляцией';
}

export function initPowerBanner(opts = {}) {
  const bannerEl = opts.bannerEl || null;
  const labelEl = opts.labelEl || null;
  const returnBtn = opts.returnBtn || null;
  const standbyBtn = opts.standbyBtn || null;
  const wakeBtn = opts.wakeBtn || null;
  const api = opts.api;
  const toast = typeof opts.toast === 'function' ? opts.toast : () => {};
  const buzz = typeof opts.buzz === 'function' ? opts.buzz : () => {};
  const onAfterAction = typeof opts.onAfterAction === 'function' ? opts.onAfterAction : () => {};

  let busy = false;

  async function sendPower(action) {
    if (busy || !api) return false;
    busy = true;
    try {
      await api('/api/power', { action });
      if (action === 'standby') toast('ТВ переведён в ожидание');
      else if (action === 'wake') toast('ТВ включён');
      else if (action === 'return_kodi') toast('Возвращаю Kodi…');
      onAfterAction(action);
      return true;
    } catch (e) {
      toast((e && e.message) || 'Команда питания не прошла');
      return false;
    } finally {
      busy = false;
    }
  }

  function updateScreen(owner) {
    if (!bannerEl) return;
    const active = Boolean(owner && OWNER_LABELS[owner]);
    bannerEl.classList.toggle('hide', !active);
    if (active && labelEl) {
      labelEl.textContent = ownerLabel(owner);
    }
    if (active && returnBtn && !returnBtn.textContent) {
      returnBtn.textContent = 'Вернуться в Kodi';
    }
  }

  if (returnBtn) {
    if (!returnBtn.textContent) returnBtn.textContent = 'Вернуться в Kodi';
    returnBtn.addEventListener('click', () => {
      buzz();
      sendPower('return_kodi');
    });
  }
  if (standbyBtn) {
    standbyBtn.addEventListener('click', () => {
      buzz();
      sendPower('standby');
    });
  }
  if (wakeBtn) {
    wakeBtn.addEventListener('click', () => {
      buzz();
      sendPower('wake');
    });
  }

  return {
    updateScreen,
    sendPower,
  };
}
