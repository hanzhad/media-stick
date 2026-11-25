const LOG_UNITS = ['kodi', 'panel', 'update', 'displayd'];
const PIN_RE = /^[0-9]{4}$/;

export function initDiagnostics(opts = {}) {
  const unitSel = opts.unitSel || null;
  const loadBtn = opts.loadBtn || null;
  const logOut = opts.logOut || null;
  const pinStateEl = opts.pinStateEl || null;
  const pinInput = opts.pinInput || null;
  const pinSetBtn = opts.pinSetBtn || null;
  const pinOffBtn = opts.pinOffBtn || null;
  const pinModal = opts.pinModal || null;
  const pinModalBack = opts.pinModalBack || null;
  const pinModalInput = opts.pinModalInput || null;
  const pinModalErr = opts.pinModalErr || null;
  const pinModalSubmit = opts.pinModalSubmit || null;
  const api = opts.api;
  const toast = typeof opts.toast === 'function' ? opts.toast : () => {};
  const buzz = typeof opts.buzz === 'function' ? opts.buzz : () => {};
  const onUnlocked = typeof opts.onUnlocked === 'function' ? opts.onUnlocked : () => {};

  let pinEnabled = false;

  async function loadLogs() {
    if (!logOut) return;
    const unit = unitSel && LOG_UNITS.includes(unitSel.value) ? unitSel.value : 'panel';
    logOut.textContent = 'Загружаю…';
    logOut.classList.remove('hide');
    try {
      const resp = await fetch(`/api/logs?unit=${encodeURIComponent(unit)}&lines=200`, { cache: 'no-store' });
      if (resp.status === 401) {
        openPinModal();
        logOut.textContent = 'Требуется PIN-код';
        return;
      }
      if (!resp.ok) {
        logOut.textContent = `Ошибка загрузки (${resp.status})`;
        return;
      }
      const text = await resp.text();
      logOut.textContent = text || 'Журнал пуст';
    } catch (_) {
      logOut.textContent = 'Не удалось загрузить журнал';
    }
  }

  function renderPinState(enabled) {
    pinEnabled = Boolean(enabled);
    if (pinStateEl) {
      pinStateEl.textContent = pinEnabled ? 'Включён' : 'Выключен';
    }
    if (pinOffBtn) {
      pinOffBtn.classList.toggle('hide', !pinEnabled);
    }
  }

  async function refreshPinStatus() {
    try {
      const resp = await fetch('/api/pin', { cache: 'no-store' });
      if (resp.ok) {
        const data = await resp.json();
        renderPinState(Boolean(data && data.enabled));
      }
    } catch (_) {}
  }

  function openPinModal() {
    if (!pinModal) return;
    pinModal.classList.remove('hide');
    if (pinModalErr) pinModalErr.classList.add('hide');
    if (pinModalInput) {
      pinModalInput.value = '';
      pinModalInput.focus();
    }
  }

  function closePinModal() {
    if (!pinModal) return;
    pinModal.classList.add('hide');
    if (pinModalInput) pinModalInput.blur();
  }

  async function submitSetPin() {
    if (!pinInput || !api) return;
    const pin = String(pinInput.value || '').trim();
    if (!PIN_RE.test(pin)) {
      toast('Введите 4 цифры PIN');
      return;
    }
    try {
      const res = await api('/api/pin', { action: 'set', pin });
      pinInput.value = '';
      renderPinState(Boolean(res && res.enabled));
      toast('PIN установлен');
    } catch (e) {
      toast((e && e.message) || 'Не удалось сохранить PIN');
    }
  }

  async function submitDisablePin() {
    if (!api) return;
    try {
      await api('/api/pin', { action: 'disable' });
      renderPinState(false);
      toast('PIN отключён');
    } catch (e) {
      if (e && e.http === 401) openPinModal();
      else toast((e && e.message) || 'Не удалось отключить PIN');
    }
  }

  async function submitUnlockPin() {
    if (!pinModalInput || !api) return;
    const pin = String(pinModalInput.value || '').trim();
    if (!PIN_RE.test(pin)) {
      if (pinModalErr) {
        pinModalErr.textContent = 'Введите 4 цифры';
        pinModalErr.classList.remove('hide');
      }
      return;
    }
    try {
      await api('/api/pin', { pin });
      closePinModal();
      toast('Доступ открыт');
      onUnlocked();
    } catch (_) {
      if (pinModalErr) {
        pinModalErr.textContent = 'Неверный PIN';
        pinModalErr.classList.remove('hide');
      }
    }
  }

  if (loadBtn) {
    loadBtn.addEventListener('click', () => {
      buzz();
      loadLogs();
    });
  }
  if (unitSel) {
    unitSel.addEventListener('change', () => {
      if (logOut && !logOut.classList.contains('hide')) {
        loadLogs();
      }
    });
  }
  if (pinSetBtn) {
    pinSetBtn.addEventListener('click', () => {
      buzz();
      submitSetPin();
    });
  }
  if (pinOffBtn) {
    pinOffBtn.addEventListener('click', () => {
      buzz();
      submitDisablePin();
    });
  }
  if (pinModalSubmit) {
    pinModalSubmit.addEventListener('click', () => {
      buzz();
      submitUnlockPin();
    });
  }
  if (pinModalInput) {
    pinModalInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        buzz();
        submitUnlockPin();
      }
    });
  }
  if (pinModalBack) {
    pinModalBack.addEventListener('click', closePinModal);
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('panel:unauthorized', openPinModal);
  }

  refreshPinStatus();

  return {
    loadLogs,
    refreshPinStatus,
    openPinModal,
    closePinModal,
    isPinEnabled: () => pinEnabled,
  };
}
