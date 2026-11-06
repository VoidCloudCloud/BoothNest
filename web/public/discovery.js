import { MAX_SAVED_SEARCHES, normalizeSavedSearches, normalizeRecentViews, recordRecentView, savedFilterQuery, privateFilterQuery } from './discovery-state.js';

const messages = {
  zh: {
    savedSearches: '保存筛选', recent: '最近浏览', quick: '快速查找', clearRecent: '清空最近浏览',
    savedTitle: '常用筛选', savedHint: '保存当前条件，之后一键恢复。筛选保存在本机，恢复时回到第一页。',
    name: '筛选名称', nameHint: '例如：MAYO 发型 · 2000 日元以内', save: '保存当前筛选', emptySaved: '还没有保存筛选。',
    apply: '应用筛选', remove: '删除', localFilter: '本机视图', itemFilter: '商品筛选', conditions: '项条件',
    saved: '筛选已保存', duplicate: '已有同名筛选，请使用其他名称。', limit: '最多保存 50 组筛选，请先删除不需要的筛选。',
    invalid: '筛选条件过长，请减少条件后重试。', cleared: '最近浏览已清空', removed: '已从最近浏览移除',
    paletteTitle: '快速查找', paletteHint: '查找已收录的商品、模型、创作者和标签', loading: '正在查找…',
    items: '商品', avatars: '模型', authors: '创作者', tags: '标签', searchAll: '搜索全部素材',
    empty: '没有找到匹配项，可以使用此关键词搜索素材。', failed: '暂时无法查找，请重试。',
    keyboard: '↑ ↓ 选择 · Enter 打开 · Esc 关闭', close: '关闭',
  },
  en: {
    savedSearches: 'Saved filters', recent: 'Recently viewed', quick: 'Quick find', clearRecent: 'Clear recent views',
    savedTitle: 'Saved filters', savedHint: 'Save the current filters on this device. Applying a saved filter starts at page one.',
    name: 'Filter name', nameHint: 'e.g. MAYO hair · up to ¥2,000', save: 'Save current filters', emptySaved: 'No saved filters yet.',
    apply: 'Apply filters', remove: 'Delete', localFilter: 'Local view', itemFilter: 'Item filters', conditions: 'conditions',
    saved: 'Filters saved', duplicate: 'This name is already used. Choose another name.', limit: 'You can save up to 50 filters. Delete an unused filter first.',
    invalid: 'These filters are too long. Remove some conditions and try again.', cleared: 'Recent views cleared', removed: 'Removed from recent views',
    paletteTitle: 'Quick find', paletteHint: 'Find indexed items, avatars, creators and tags', loading: 'Searching…',
    items: 'Items', avatars: 'Avatars', authors: 'Creators', tags: 'Tags', searchAll: 'Search all items',
    empty: 'No matches. You can still search all items with this query.', failed: 'Could not search. Please try again.',
    keyboard: '↑ ↓ Select · Enter Open · Esc Close', close: 'Close',
  },
};

export function initDiscovery({ api, escape, icon, language, readStorage, writeStorage, getQuery, getView, applyQuery, selectGroup, openItem, onHistoryChange, toast }) {
  const t = key => (messages[language()] || messages.zh)[key];
  let saved = normalizeSavedSearches(readStorage('saved-searches', []));
  let recent = normalizeRecentViews(readStorage('recent-views', []));
  let viewed = new Set(recent.map(entry => entry.id));
  let returnFocus, timer, controller, generation = 0, active = -1, choices = [], currentLanguage = language();
  const savedDialog = document.createElement('dialog');
  savedDialog.className = 'discovery-dialog saved-search-dialog'; savedDialog.id = 'saved-search-dialog'; savedDialog.setAttribute('aria-labelledby', 'saved-search-heading');
  const palette = document.createElement('dialog');
  palette.className = 'discovery-dialog palette-dialog'; palette.id = 'palette-dialog'; palette.setAttribute('aria-labelledby', 'palette-heading');
  document.body.append(savedDialog, palette);

  function closeButton() { return `<button type="button" class="icon-btn" data-discovery="close" aria-label="${t('close')}">${icon('x')}</button>`; }
  function open(dialog) {
    returnFocus = document.activeElement;
    dialog.showModal();
  }
  for (const dialog of [savedDialog, palette]) {
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
    dialog.addEventListener('close', () => {
      if (dialog === palette) { clearTimeout(timer); controller?.abort(); generation++; }
      if (returnFocus?.isConnected && !document.querySelector('dialog[open]')) returnFocus.focus();
    });
  }

  function renderSaved() {
    const currentName = savedDialog.querySelector('#saved-filter-name')?.value || '';
    savedDialog.innerHTML = `<div class="discovery-heading"><h1 id="saved-search-heading">${t('savedTitle')}</h1>${closeButton()}</div>
      <p class="discovery-hint">${t('savedHint')}</p>
      <form id="saved-filter-form"><label for="saved-filter-name">${t('name')}</label><div class="saved-filter-form-row"><input id="saved-filter-name" name="name" required maxlength="80" autocomplete="off" placeholder="${t('nameHint')}" value="${escape(currentName)}"><button class="btn primary" type="submit">${t('save')}</button></div></form>
      <p id="saved-filter-feedback" class="form-feedback" role="status"></p>
      <div class="saved-filter-list">${saved.length ? saved.map(entry => {
        const params = new URLSearchParams(entry.query);
        const count = [...params].filter(([key]) => !['view', 'pageSize', 'sort'].includes(key)).length;
        return `<div class="saved-filter-row"><button type="button" class="saved-filter-apply" data-discovery="apply-saved" data-id="${entry.id}" title="${t('apply')}"><strong>${escape(entry.name)}</strong><span>${t(privateFilterQuery(entry.query) ? 'localFilter' : 'itemFilter')} · ${count} ${t('conditions')}</span></button><button type="button" class="icon-btn" data-discovery="delete-saved" data-id="${entry.id}" aria-label="${t('remove')} ${escape(entry.name)}">${icon('x')}</button></div>`;
      }).join('') : `<p class="discovery-empty">${t('emptySaved')}</p>`}</div>`;
  }
  function openSaved() { renderSaved(); open(savedDialog); savedDialog.querySelector('input').focus(); }

  function openPalette() {
    palette.innerHTML = `<div class="discovery-heading"><h1 id="palette-heading">${t('paletteTitle')}</h1>${closeButton()}</div>
      <div class="palette-input-row">${icon('search')}<input id="palette-input" type="search" maxlength="200" autocomplete="off" spellcheck="false" placeholder="${t('paletteHint')}" aria-label="${t('paletteHint')}" role="combobox" aria-controls="palette-results" aria-expanded="true" aria-autocomplete="list"></div>
      <p id="palette-status" class="discovery-hint" role="status">${t('paletteHint')}</p><div id="palette-results" role="listbox" aria-label="${t('paletteTitle')}"></div><p class="palette-keyboard">${t('keyboard')}</p>`;
    active = -1; choices = []; open(palette); palette.querySelector('input').focus();
  }
  function setActive(index) {
    const options = [...palette.querySelectorAll('.palette-result')];
    active = options.length ? (index + options.length) % options.length : -1;
    options.forEach((option, i) => { option.classList.toggle('active', i === active); option.setAttribute('aria-selected', String(i === active)); });
    const input = palette.querySelector('input');
    if (active < 0) input.removeAttribute('aria-activedescendant');
    else { input.setAttribute('aria-activedescendant', options[active].id); options[active].scrollIntoView({ block: 'nearest' }); }
  }
  function renderChoices(result, q, failed = false) {
    choices = [];
    const sections = ['items', 'avatars', 'authors', 'tags'].map(group => {
      const entries = result[group] || [];
      if (!entries.length) return '';
      const rows = entries.map(entry => {
        const title = group === 'items' ? entry.title : group === 'avatars' ? (language() === 'zh' ? entry.ja || entry.en : entry.en || entry.ja) : entry.name;
        const subtitle = group === 'items' ? entry.author : String(entry.count);
        const index = choices.push({ group, value: group === 'items' ? entry.id : group === 'avatars' ? entry.slug : entry.name }) - 1;
        return `<button type="button" id="palette-option-${index}" class="palette-result" role="option" aria-selected="false" tabindex="-1" data-palette-index="${index}"><span class="palette-symbol">${icon(({ items: 'box', avatars: 'avatar', authors: 'avatar', tags: 'filter' })[group])}</span><span class="palette-result-text"><strong>${escape(title)}</strong><small>${escape(subtitle)}</small></span>${icon('arrow')}</button>`;
      }).join('');
      return `<div class="palette-group" role="group" aria-labelledby="palette-group-${group}"><h2 id="palette-group-${group}">${t(group)}</h2>${rows}</div>`;
    }).join('');
    const hasMatches = choices.length > 0;
    const index = choices.push({ group: 'query', value: q }) - 1;
    palette.querySelector('#palette-results').innerHTML = sections + `<button type="button" id="palette-option-${index}" class="palette-result palette-search-all" role="option" aria-selected="false" tabindex="-1" data-palette-index="${index}">${icon('search')}<span class="palette-result-text"><strong>${t('searchAll')}</strong><small>${escape(q)}</small></span>${icon('arrow')}</button>`;
    palette.querySelector('#palette-status').textContent = failed ? t('failed') : hasMatches ? '' : t('empty');
    setActive(0);
  }
  function scheduleSearch() {
    clearTimeout(timer); controller?.abort();
    const request = ++generation;
    const q = palette.querySelector('input').value.trim();
    choices = []; active = -1;
    palette.querySelector('#palette-results').innerHTML = '';
    palette.querySelector('input').removeAttribute('aria-activedescendant');
    palette.querySelector('#palette-status').textContent = t(q ? 'loading' : 'paletteHint');
    if (!q) return;
    controller = new AbortController();
    const signal = controller.signal;
    const adult = new URLSearchParams(getQuery()).get('adult') || 'safe';
    timer = setTimeout(async () => {
      try {
        const result = await api('/api/palette?' + new URLSearchParams({ q, adult }), { signal });
        if (request === generation && palette.open) renderChoices(result, q);
      } catch (error) {
        if (error.name !== 'AbortError' && request === generation && palette.open) renderChoices({}, q, true);
      }
    }, 150);
  }
  function choose(index) {
    const entry = choices[index];
    if (!entry) return;
    palette.close();
    if (entry.group === 'items') openItem(entry.value);
    else selectGroup(entry.group, entry.value);
  }
  palette.addEventListener('input', event => { if (event.target.id === 'palette-input') scheduleSearch(); });
  palette.addEventListener('keydown', event => {
    if (event.isComposing) return;
    if (event.key === 'Escape') { event.preventDefault(); palette.close(); }
    else if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); setActive(active + (event.key === 'ArrowDown' ? 1 : -1)); }
    else if (event.key === 'Enter' && event.target.id === 'palette-input') { event.preventDefault(); choose(active); }
  });
  palette.addEventListener('click', event => {
    const row = event.target.closest('[data-palette-index]');
    if (row) choose(Number(row.dataset.paletteIndex));
  });

  function persistRecent(next) {
    recent = normalizeRecentViews(next); viewed = new Set(recent.map(entry => entry.id));
    writeStorage('recent-views', recent); refresh(); onHistoryChange();
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-discovery]');
    if (!button || button.disabled) return;
    const action = button.dataset.discovery;
    if (action === 'open-saved') openSaved();
    else if (action === 'open-palette') openPalette();
    else if (action === 'close') button.closest('dialog').close();
    else if (action === 'apply-saved') {
      const entry = saved.find(entry => entry.id === button.dataset.id);
      if (entry) { savedDialog.close(); applyQuery(entry.query); }
    } else if (action === 'delete-saved') {
      saved = saved.filter(entry => entry.id !== button.dataset.id);
      writeStorage('saved-searches', saved); renderSaved(); savedDialog.querySelector('input').focus();
    } else if (action === 'remove-view') { persistRecent(recent.filter(entry => entry.id !== Number(button.dataset.id))); toast(t('removed')); }
    else if (action === 'clear-recent') { persistRecent([]); toast(t('cleared')); }
  });
  savedDialog.addEventListener('submit', event => {
    if (event.target.id !== 'saved-filter-form') return;
    event.preventDefault();
    const input = savedDialog.querySelector('input'), name = input.value.trim();
    const feedback = savedDialog.querySelector('#saved-filter-feedback');
    if (!name) { input.focus(); return; }
    if (saved.some(entry => entry.name.normalize('NFKC').toLowerCase() === name.normalize('NFKC').toLowerCase())) { feedback.textContent = t('duplicate'); return; }
    if (saved.length >= MAX_SAVED_SEARCHES) { feedback.textContent = t('limit'); return; }
    const query = savedFilterQuery(getQuery());
    if (query.length > 16000) { feedback.textContent = t('invalid'); return; }
    saved.unshift({ id: crypto.randomUUID(), name, query });
    writeStorage('saved-searches', saved); input.value = ''; renderSaved();
    savedDialog.querySelector('#saved-filter-feedback').textContent = t('saved'); savedDialog.querySelector('input').focus();
  });
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (palette.open) palette.close();
      else if (!document.querySelector('dialog[open]')) openPalette();
    }
  });
  function refresh() {
    document.querySelectorAll('[data-discovery-label]').forEach(element => { element.textContent = t(element.dataset.discoveryLabel); });
    const recentButton = document.querySelector('[data-view="recent"]');
    recentButton?.setAttribute('aria-pressed', String(getView() === 'recent'));
    const clear = document.querySelector('[data-discovery="clear-recent"]');
    if (clear) clear.hidden = getView() !== 'recent' || !recent.length;
    if (currentLanguage !== language()) {
      currentLanguage = language();
      if (savedDialog.open) renderSaved();
    }
  }
  refresh();
  return {
    refresh,
    recentIds: () => recent.map(entry => entry.id),
    hasViewed: id => viewed.has(id),
    recordView: id => persistRecent(recordRecentView(recent, id)),
  };
}
