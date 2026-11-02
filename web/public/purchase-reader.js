// Runs in the user's signed-in BOOTH library page. Only public product metadata is exported.
export function extractLibraryPage(doc, pageUrl) {
  const base = new URL(pageUrl);
  const libraryPath = /^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?library\/?$/i;
  if (!['accounts.booth.pm', 'booth.pm'].includes(base.hostname) || base.protocol !== 'https:' || !libraryPath.test(base.pathname)) throw new Error('请打开 BOOTH「下载库 / ライブラリ」的已购页面后再采集。');
  if (doc.querySelector('input[type="password"]') || /\/sign_in|\/login/.test(base.pathname)) throw new Error('请先在 BOOTH 完成登录。');
  const itemUrl = href => {
    try { const u = new URL(href, base); if (u.protocol === 'https:' && (u.hostname === 'booth.pm' || (u.hostname.endsWith('.booth.pm') && u.hostname !== 'accounts.booth.pm'))) { const match = /^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?items\/([1-9]\d{0,9})\/?$/i.exec(u.pathname); if (match) return { url: u.href, id: Number(match[1]) }; } } catch {}
    return null;
  };
  const text = element => element?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const excluded = 'aside,nav,body>header,body>footer,dialog,[role="complementary"],[data-recommendation]';
  const productLinks = [...doc.querySelectorAll('a[href]')].filter(link => !link.closest(excluded) && itemUrl(link.getAttribute('href')));
  const hasDownload = card => [...card.querySelectorAll('a,button,[role="button"],input[type="button"]')].some(control => {
    if (itemUrl(control.getAttribute('href'))) return false;
    // A download control proves this is a library card, rather than a recommendation.
    // Its URL is never stored or requested.
    if (/(?:\bdownloads?\b|ダウンロード|下载|下載)/i.test([text(control), control.getAttribute('aria-label'), control.getAttribute('title'), control.getAttribute('value')].filter(Boolean).join(' '))) return true;
    try { const u = new URL(control.getAttribute('href'), base); return u.protocol === 'https:' && (u.hostname === 'booth.pm' || u.hostname.endsWith('.booth.pm')) && /^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?(?:downloadables|downloads)\//i.test(u.pathname); } catch { return false; }
  });
  const products = new Map();
  for (const link of productLinks) {
    const item = itemUrl(link.getAttribute('href'));
    if (products.has(item.id)) continue;
    let card = link.parentElement, links, title;
    while (card && card !== doc.body && card !== doc.documentElement && !card.matches('main,[role="main"]')) {
      links = [...card.querySelectorAll('a[href]')].filter(a => !a.closest(excluded));
      const ids = new Set(links.map(a => itemUrl(a.getAttribute('href'))?.id).filter(Boolean));
      if (ids.size > 1) { card = null; break; }
      const namedLink = links.find(a => itemUrl(a.getAttribute('href'))?.id === item.id && text(a));
      title = text(namedLink) || text(card.querySelector('.text-text-default,h2,h3,h4,[data-item-title]'));
      // Keep older saved library pages working without requiring any current CSS class.
      const legacyCard = card.querySelector('img.l-library-item-thumbnail') && title;
      if (hasDownload(card) || legacyCard) break;
      card = card.parentElement;
    }
    if (!card || card === doc.body || card === doc.documentElement || card.matches('main,[role="main"]')) continue;
    const image = links.filter(a => itemUrl(a.getAttribute('href'))?.id === item.id).map(a => a.querySelector('img')).find(Boolean) || card.querySelector('img');
    const shop = links.find(a => {
      try { const u = new URL(a.getAttribute('href'), base); return u.protocol === 'https:' && u.hostname.endsWith('.booth.pm') && !['accounts.booth.pm', 'www.booth.pm'].includes(u.hostname) && /^\/(?:[a-z]{2}(?:-[a-z]{2})?\/?)?$/i.test(u.pathname); } catch { return false; }
    });
    title ||= link.getAttribute('title')?.trim() || image?.alt?.trim() || `BOOTH #${item.id}`;
    let thumbnail = '';
    const imageSource = image?.getAttribute('src') || image?.getAttribute('data-src') || image?.getAttribute('data-original');
    if (imageSource) { try { const u = new URL(imageSource, base); if (u.protocol === 'https:') thumbnail = u.href; } catch {} }
    products.set(item.id, { id: item.id, title: title.slice(0, 500), shop: text(shop).slice(0, 500), shopUrl: shop ? new URL(shop.getAttribute('href'), base).href : '', image: thumbnail, isAdult: /(?:^|[^a-z0-9])R-?18(?:[^a-z0-9]|$)/i.test(card.textContent) });
  }
  if (!products.size) throw new Error(`没有识别到下载库商品（检测到 ${productLinks.length} 个商品链接）。请确认商品已加载，再重新运行新版采集书签；也可保存下载库 HTML 后导入。`);
  const pages = new Set([Number(base.searchParams.get('page')) || 1]);
  for (const a of doc.querySelectorAll('a[href]')) {
    try { const u = new URL(a.getAttribute('href'), base); const page = Number(u.searchParams.get('page')); if (u.origin === base.origin && u.pathname.replace(/\/$/, '') === base.pathname.replace(/\/$/, '') && Number.isSafeInteger(page) && page > 0) pages.add(page); } catch {}
  }
  return { products: [...products.values()], pages: [...pages] };
}

export async function collectLibraryPages({ pageUrl = location.href, initialDocument, request = fetch, parse = html => new DOMParser().parseFromString(html, 'text/html'), onProgress = () => {}, pause = ms => new Promise(resolve => setTimeout(resolve, ms)), signal } = {}) {
  const start = new URL(pageUrl);
  if (start.protocol !== 'https:' || !['accounts.booth.pm', 'booth.pm'].includes(start.hostname) || !/^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?library\/?$/i.test(start.pathname)) throw new Error('请在 BOOTH 已购下载库页面运行。');
  const currentPage = Number(start.searchParams.get('page')) || 1;
  const pending = new Set(initialDocument ? [currentPage, 1] : [1]), visited = new Set(), products = new Map();
  while (pending.size) {
    if (signal?.aborted) throw new Error('采集已取消，没有修改本地记录。');
    const page = Math.min(...pending); pending.delete(page);
    if (page > 500 || visited.size >= 500) throw new Error('超过 500 页限制，已停止；请分批保存网页导入。');
    // Keep language and library filters; category and free/gift filters can change the library.
    const url = new URL(start.href); url.hash = ''; url.searchParams.set('page', page);
    onProgress({ page, pages: Math.max(page, ...pending), products: products.size });
    let parsed;
    if (initialDocument && page === currentPage) parsed = extractLibraryPage(initialDocument, start.href);
    else {
      const response = await request(url.href, { credentials: 'same-origin', signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000) });
      const final = new URL(response.url || url);
      if (!response.ok || final.origin !== start.origin || final.pathname.replace(/\/$/, '') !== start.pathname.replace(/\/$/, '')) throw new Error('BOOTH 登录已失效、要求验证或暂时无法访问。请在网页完成登录后重试。');
      parsed = extractLibraryPage(parse(await response.text()), url.href);
    }
    for (const product of parsed.products) products.set(product.id, product);
    visited.add(page);
    const last = Math.max(...parsed.pages);
    if (last > 500) throw new Error('超过 500 页限制，已停止；请分批保存网页导入。');
    for (let discovered = 1; discovered <= last; discovered++) if (!visited.has(discovered)) pending.add(discovered);
    if (pending.size) await pause(650);
  }
  return { type: 'vrcatalogue-booth-purchases', schemaVersion: 1, source: 'https://accounts.booth.pm/library', exportedAt: new Date().toISOString(), complete: ![...start.searchParams.keys()].some(key => key !== 'page'), pages: visited.size, products: [...products.values()] };
}
