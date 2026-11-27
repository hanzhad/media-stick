const TB_CSS = `
.tb{background:var(--card);border-radius:18px;padding:5px 6px;border:1px solid var(--line)}
.tb-row{display:flex;align-items:center;gap:5px;min-height:36px}
.tb-pill,.tb-chip,.tb-btn{display:inline-flex;align-items:center;justify-content:center;gap:4px;min-height:34px;padding:0 10px;border:1px solid var(--line);border-radius:999px;background:var(--card2);color:#fff;font-size:13px;font-weight:500;white-space:nowrap;flex:none;touch-action:manipulation;user-select:none;-webkit-user-select:none}
.tb-pill:disabled{opacity:.85;cursor:default}
.tb-chips{display:flex;align-items:center;gap:5px;flex:1 1 0;min-width:0;overflow-x:auto;touch-action:pan-x;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.tb-chips::-webkit-scrollbar{display:none}
.tb-chip.on,.tb-btn.on,.tb-fav.on{background:#fff;color:var(--bg);font-weight:600;border-color:#fff}
.tb-fav.on{color:#d9384a}
.tb-acts{display:flex;align-items:center;gap:6px;flex:none}
.tb-btn.tb-ico{width:34px;min-width:34px;padding:0}
.tb-btn.tb-pri{background:#fff;color:var(--bg);border-color:#fff;font-weight:600}
.tb-btn:active,.tb-chip:active,.tb-pill:active{opacity:.75}
.tb-sheet-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.tb-sheet-head h2{margin:0;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tb-sheet-list{display:flex;flex-direction:column;gap:8px}
.tb-sheet-item{display:flex;flex-direction:column;align-items:flex-start;gap:2px;width:100%;min-height:48px;padding:10px 14px;border:1px solid var(--line);border-radius:14px;background:var(--bg);color:#fff;text-align:left;touch-action:manipulation}
.tb-sheet-item.on{border-color:#fff;background:var(--card2);font-weight:600}
.tb-sheet-item small{color:var(--dim);font-size:12px}
.tb-sheet-empty{padding:20px 8px;text-align:center;color:var(--dim);font-size:14px}
`;

function ensureStyles() {
  if (typeof document === 'undefined' || document.getElementById('tb-styles')) return;
  const st = document.createElement('style');
  st.id = 'tb-styles';
  st.textContent = TB_CSS;
  document.head.appendChild(st);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function svgIcon(href, cls = 'i s') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', href);
  svg.appendChild(use);
  return svg;
}

function isInt(v) {
  return typeof v === 'number' && Number.isInteger(v);
}

function modalPlayFields(modal) {
  const out = {};
  if (!modal) return out;
  if (typeof modal.show_id === 'string' && modal.show_id) out.show_id = modal.show_id;
  if (typeof modal.cid === 'string' && modal.cid) out.cid = modal.cid;
  return out;
}

function seasonLabel(item) {
  if (isInt(item)) return `С${item}`;
  const s = String(item || '').trim();
  return /^\d+$/.test(s) ? `С${s}` : s;
}

export function initTouchBar(opts = {}) {
  const root = opts.root || null;
  if (!root) return null;
  ensureStyles();

  const ws = opts.ws || null;
  const api = opts.api || null;
  const toast = typeof opts.toast === 'function' ? opts.toast : () => {};
  const buzz = typeof opts.buzz === 'function' ? opts.buzz : () => {};
  const onContext = typeof opts.onContext === 'function' ? opts.onContext : () => {};

  let currentCtx = null;
  let sheet = null;
  let sheetTitle = null;
  let sheetBody = null;
  let loadGen = 0;

  function ensureSheet() {
    if (sheet) return sheet;
    sheet = el('div', 'sheet hide');
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    const back = el('div', 'sheet-back');
    const box = el('div', 'sheet-box');
    const head = el('div', 'tb-sheet-head');
    sheetTitle = el('h2', '', 'Список');
    const closeBtn = el('button', 'btn sm', 'Закрыть');
    closeBtn.type = 'button';
    closeBtn.addEventListener('click', closeSheet);
    back.addEventListener('click', closeSheet);
    head.append(sheetTitle, closeBtn);
    sheetBody = el('div', 'tb-sheet-list');
    box.append(head, sheetBody);
    sheet.append(back, box);
    document.body.appendChild(sheet);
    return sheet;
  }

  function closeSheet() {
    loadGen += 1;
    if (sheet) sheet.classList.add('hide');
  }

  function openSheet(title) {
    ensureSheet();
    sheetTitle.textContent = title || 'Список';
    sheetBody.replaceChildren();
    sheet.classList.remove('hide');
  }

  function sendCmd(payload) {
    if (!payload || !payload.cmd || !payload.app) return Promise.resolve(false);
    if (ws && typeof ws.sendJson === 'function' && ws.isOpen()) {
      if (ws.sendJson({ type: 'ui_cmd', ...payload })) {
        return Promise.resolve(true);
      }
    }
    if (typeof api === 'function') {
      return api('/api/ui/cmd', payload)
        .then(() => true)
        .catch((e) => {
          toast((e && e.message) || 'Команда не прошла');
          return false;
        });
    }
    return Promise.resolve(false);
  }

  function openPickerSheet(title, items, activeId, onPick) {
    openSheet(title);
    for (const item of items) {
      const id = String(item.id || '');
      const label = String(item.label || id);
      const btn = el('button', `tb-sheet-item${id === activeId ? ' on' : ''}`, label);
      btn.type = 'button';
      btn.addEventListener('click', () => {
        buzz();
        closeSheet();
        onPick(item);
      });
      sheetBody.appendChild(btn);
    }
  }

  function renderDrawerItems(ctx, modeKind, items) {
    sheetBody.replaceChildren();
    if (!Array.isArray(items) || items.length === 0) {
      sheetBody.appendChild(el('div', 'tb-sheet-empty', 'Список пуст'));
      return;
    }
    items.forEach((item, idx) => {
      const btn = el('button', 'tb-sheet-item');
      btn.type = 'button';
      const titleText = String(item.title || item.name || item.text || `#${idx + 1}`);
      const subParts = [];
      if (item.time) subParts.push(String(item.time));
      else if (item.when) subParts.push(String(item.when));
      if (item.subtitle) subParts.push(String(item.subtitle));
      else if (item.duration) subParts.push(String(item.duration));
      btn.appendChild(el('b', '', titleText));
      if (subParts.length) {
        btn.appendChild(el('small', '', subParts.join(' · ')));
      }
      btn.addEventListener('click', () => {
        buzz();
        closeSheet();
        if (modeKind === 'epg') {
          sendCmd({ cmd: 'play_epg', app: ctx.app, idx });
        } else {
          const payload = { cmd: 'play_episode', app: ctx.app, idx };
          if (isInt(item.season) && item.season >= 0) payload.season = item.season;
          sendCmd(payload);
        }
      });
      sheetBody.appendChild(btn);
    });
  }

  async function openModalDrawer(ctx, modal) {
    const gen = ++loadGen;
    const isGuide = modal.kind === 'guide' || ctx.view === 'guide';
    openSheet(modal.title || (isGuide ? 'Программа передач' : 'Список'));

    if (modal.demo) {
      if (isGuide || Array.isArray(modal.programs)) {
        renderDrawerItems(ctx, 'epg', modal.programs || []);
      } else {
        renderDrawerItems(ctx, 'episode', modal.episodes || []);
      }
      return;
    }

    if (ctx.app !== 'sweettv') {
      renderDrawerItems(ctx, isGuide ? 'epg' : 'episode', []);
      return;
    }

    let url = '';
    let kind = 'episode';
    if (isGuide) {
      kind = 'epg';
      const cid = encodeURIComponent(modal.cid || '');
      if (typeof modal.selected_day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(modal.selected_day)) {
        url = `/api/sweettv/day?cid=${cid}&date=${encodeURIComponent(modal.selected_day)}`;
      } else {
        url = `/api/sweettv/guide?cid=${cid}`;
      }
    } else if (modal.kind === 'vod' || ctx.view === 'detail') {
      const vodId = String(modal.show_id || '').replace(/^vod:/, '');
      url = `/api/sweettv/vod?id=${encodeURIComponent(vodId)}`;
    } else {
      url = `/api/sweettv/show?id=${encodeURIComponent(modal.show_id || '')}`;
    }

    sheetBody.appendChild(el('div', 'tb-sheet-empty', 'Загружаю…'));
    try {
      const resp = await fetch(url, { cache: 'no-store' });
      const data = await resp.json().catch(() => ({}));
      if (gen !== loadGen) return;
      if (!resp.ok) {
        sheetBody.replaceChildren(el('div', 'tb-sheet-empty', data.error || 'Не удалось загрузить'));
        return;
      }
      let items = [];
      if (kind === 'epg') {
        if (Array.isArray(data.items)) {
          items = data.items;
        } else {
          items = [
            ...(data.current ? [data.current] : []),
            ...(Array.isArray(data.past) ? data.past : []),
            ...(Array.isArray(data.next) ? data.next : []),
          ];
        }
      } else {
        items = Array.isArray(data.episodes) ? data.episodes : (Array.isArray(data.items) ? data.items : []);
      }
      renderDrawerItems(ctx, kind, items);
    } catch (_) {
      if (gen !== loadGen) return;
      sheetBody.replaceChildren(el('div', 'tb-sheet-empty', 'Не удалось загрузить'));
    }
  }

  function renderSection(ctx) {
    const row = el('div', 'tb-row');
    const sections = Array.isArray(ctx.sections) ? ctx.sections : [];
    const activeSec = sections.find((s) => s.id === ctx.section);
    const secLabel = (activeSec && activeSec.label) || ctx.section || ctx.app;
    const secBtn = el('button', 'tb-pill', sections.length > 1 ? `${secLabel} ▾` : secLabel);
    secBtn.type = 'button';
    if (sections.length > 1) {
      secBtn.addEventListener('click', () => {
        buzz();
        openPickerSheet('Раздел', sections, ctx.section, (s) => {
          sendCmd({ cmd: 'set_section', app: ctx.app, section: s.id });
        });
      });
    } else {
      secBtn.disabled = true;
    }
    row.appendChild(secBtn);

    const chips = Array.isArray(ctx.chips) ? ctx.chips : [];
    const chipsWrap = el('div', 'tb-chips');
    for (const chip of chips) {
      const btn = el('button', `tb-chip${chip.active ? ' on' : ''}`, chip.label || chip.id);
      btn.type = 'button';
      btn.addEventListener('click', () => {
        buzz();
        sendCmd({ cmd: 'set_filter', app: ctx.app, id: String(chip.id || ''), active: !chip.active });
      });
      chipsWrap.appendChild(btn);
    }
    row.appendChild(chipsWrap);

    const acts = el('div', 'tb-acts');
    if (ctx.sort && typeof ctx.sort === 'object') {
      const optsList = Array.isArray(ctx.sort.options) ? ctx.sort.options : [];
      const sortLabel = ctx.sort.label ? 'Сортировка: ' + ctx.sort.label : 'Сортировка';
      const sortBtn = el('button', 'tb-btn tb-ico', '↕');
      sortBtn.type = 'button';
      if (optsList.length > 0 && ctx.sort.id && ctx.sort.id !== optsList[0].id) {
        sortBtn.classList.add('on');
      }
      sortBtn.setAttribute('aria-label', sortLabel);
      sortBtn.setAttribute('title', sortLabel);
      sortBtn.addEventListener('click', () => {
        buzz();
        if (optsList.length > 1) {
          openPickerSheet('Сортировка', optsList, ctx.sort.id || '', (opt) => {
            sendCmd({ cmd: 'sort', app: ctx.app, sort: opt.id });
          });
        } else if (ctx.sort.id) {
          sendCmd({ cmd: 'sort', app: ctx.app, sort: ctx.sort.id });
        }
      });
      acts.appendChild(sortBtn);
    }
    if (acts.childElementCount > 0) row.appendChild(acts);
    root.replaceChildren(row);
  }

  function renderModal(ctx) {
    const modal = ctx.modal && typeof ctx.modal === 'object' ? ctx.modal : {};
    const row = el('div', 'tb-row tb-modal');
    const fields = modalPlayFields(modal);

    if (modal.can_play !== false) {
      const playLabel = modal.play_label || 'Смотреть';
      const playBtn = el('button', 'tb-btn tb-pri tb-ico');
      playBtn.type = 'button';
      playBtn.setAttribute('aria-label', playLabel);
      playBtn.setAttribute('title', playLabel);
      playBtn.appendChild(svgIcon('#i-play'));
      playBtn.addEventListener('click', () => {
        buzz();
        sendCmd({ cmd: 'play', app: ctx.app, ...fields });
      });
      row.appendChild(playBtn);
    }

    if (modal.can_archive || modal.alt_label) {
      const altLabel = modal.alt_label || 'Сначала';
      const altBtn = el('button', 'tb-btn tb-ico', '↺');
      altBtn.type = 'button';
      altBtn.setAttribute('aria-label', altLabel);
      altBtn.setAttribute('title', altLabel);
      altBtn.addEventListener('click', () => {
        buzz();
        sendCmd({ cmd: 'play_from_start', app: ctx.app, ...fields });
      });
      row.appendChild(altBtn);
    }

    const favBtn = el('button', `tb-btn tb-ico tb-fav${modal.fav ? ' on' : ''}`, '♥');
    favBtn.type = 'button';
    favBtn.setAttribute('aria-label', 'Избранное');
    favBtn.setAttribute('title', 'Избранное');
    favBtn.addEventListener('click', () => {
      buzz();
      const payload = { cmd: 'toggle_fav', app: ctx.app };
      if (typeof modal.fav_key === 'string' && modal.fav_key) payload.fav_key = modal.fav_key;
      sendCmd(payload);
    });
    row.appendChild(favBtn);

    const tabsWrap = el('div', 'tb-chips');
    if (Array.isArray(modal.seasons) && modal.seasons.length > 0) {
      modal.seasons.forEach((s, idx) => {
        const active = s === modal.selected_season || idx === modal.selected_season;
        const btn = el('button', `tb-chip${active ? ' on' : ''}`, seasonLabel(s));
        btn.type = 'button';
        btn.addEventListener('click', () => {
          buzz();
          sendCmd({ cmd: 'select_tab', app: ctx.app, idx });
        });
        tabsWrap.appendChild(btn);
      });
    } else if (Array.isArray(modal.days) && modal.days.length > 0) {
      modal.days.forEach((d, idx) => {
        const active = d === modal.selected_day || idx === modal.selected_day;
        const btn = el('button', `tb-chip${active ? ' on' : ''}`, String(d));
        btn.type = 'button';
        btn.addEventListener('click', () => {
          buzz();
          sendCmd({ cmd: 'select_tab', app: ctx.app, idx });
        });
        tabsWrap.appendChild(btn);
      });
    }
    row.appendChild(tabsWrap);

    const hasDrawer = Boolean(modal.demo || ctx.app === 'sweettv');
    if (hasDrawer) {
      const drawerBtn = el('button', 'tb-btn tb-ico', '≡');
      drawerBtn.type = 'button';
      drawerBtn.setAttribute('aria-label', 'Список');
      drawerBtn.addEventListener('click', () => {
        buzz();
        openModalDrawer(ctx, modal);
      });
      row.appendChild(drawerBtn);
    }

    root.replaceChildren(row);
  }

  function update(ctx) {
    currentCtx = ctx && typeof ctx === 'object' ? ctx : null;
    onContext(currentCtx);
    const shell = root.closest('.rc-shell');
    const active = Boolean(currentCtx && currentCtx.app && currentCtx.view && currentCtx.view !== 'none');
    if (!active) {
      root.classList.add('hide');
      root.replaceChildren();
      if (shell) shell.classList.remove('tb-on');
      closeSheet();
      return;
    }

    if (currentCtx.view === 'section') {
      root.classList.remove('hide');
      if (shell) shell.classList.add('tb-on');
      renderSection(currentCtx);
    } else if (currentCtx.view === 'show' || currentCtx.view === 'detail' || currentCtx.view === 'guide') {
      root.classList.remove('hide');
      if (shell) shell.classList.add('tb-on');
      renderModal(currentCtx);
    } else {
      root.classList.add('hide');
      root.replaceChildren();
      if (shell) shell.classList.remove('tb-on');
      closeSheet();
    }
  }

  if (ws && typeof ws.on === 'function') {
    ws.on('ui_context', update);
  }

  return {
    update,
    current: () => currentCtx,
    closeSheet,
  };
}
