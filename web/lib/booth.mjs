import { boothId } from './catalog.mjs';

export class BoothRequestError extends Error {
  constructor(message, kind = 'network') { super(message); this.kind = kind; }
}
export function requestSignal(signal, timeout = 25000) { return signal ? AbortSignal.any([signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout); }
export function responseError(status) {
  if (status === 429) return new BoothRequestError('BOOTH 请求过于频繁，已暂停；请稍后手动重试。', 'blocked');
  if ([401, 403].includes(status)) return new BoothRequestError('BOOTH 要求登录或浏览器验证，已暂停本轮自动同步。', 'blocked');
  if ([404, 410].includes(status)) return new BoothRequestError('商品暂时无法公开访问，已有记录已保留。', 'unavailable');
  return new BoothRequestError(`BOOTH 返回 ${status}，稍后再试。`);
}
export function parseSearchPage(html) {
  // Empty searches include recommendation cards with valid IDs; those are not search matches.
  if (/(?:Results\s*|に関する人気の同人グッズ)0\s*[件点]|No (?:items|results)|見つかりません/i.test(html)) return [];
  const cards = [...html.matchAll(/<[^>]+data-product-id=["']([1-9]\d{0,9})["'][^>]*>/g)];
  const ids = [...new Set(cards.filter(match => {
    const list = /data-product-list=["']([^"']*)["']/.exec(match[0])?.[1];
    return !list || /\bsearch_result/.test(list);
  }).map(match => boothId(match[1])).filter(Boolean))];
  if (ids.length) return ids;
  const title = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html)?.[1] || '';
  if (/just a moment|access denied|attention required/i.test(title) || /id=["']challenge-form|verify you are human|cf-chl-error|you have been blocked/i.test(html)) throw new BoothRequestError('BOOTH 暂时要求浏览器验证，已暂停自动同步。', 'blocked');
  throw new BoothRequestError('无法识别 BOOTH 搜索结果，未推进同步进度。');
}
export async function searchBooth(query, { page = 1, sort = 'new', signal, fetcher = fetch } = {}) {
  const searchQuery = /vrchat/i.test(query) ? query : `${query} VRChat`;
  let response;
  try { response = await fetcher(`https://booth.pm/en/search/${encodeURIComponent(searchQuery)}?${new URLSearchParams({ sort, page: String(page) })}`, { signal: requestSignal(signal), headers: { 'user-agent': 'VRCatalogueLocal/0.4 (personal catalogue)' } }); }
  catch (error) { if (signal?.aborted) throw error; throw new BoothRequestError('连接 BOOTH 搜索失败，已保留进度，稍后可继续。'); }
  if (!response.ok) throw responseError(response.status);
  if (response.url && page > 1 && Number(new URL(response.url).searchParams.get('page')) !== Number(page)) throw new BoothRequestError('BOOTH 跳转未保留页码，已停止推进历史页。');
  return { ids: parseSearchPage(await response.text()), query: searchQuery, page };
}
export function is3dListing(record) { return /3d|ソフトウェア|ツール|software|tools/i.test(String(record.category || '').normalize('NFKC')); }
