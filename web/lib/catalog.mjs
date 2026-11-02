import { readFile, writeFile, mkdir, copyFile, rename } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

export const categoryNames = {
  '3d-characters': '3D 模型', clothing: '服装', hair: '发型',
  'avatar-accessories': '配饰', 'avatar-props': '道具与玩具',
  'avatar-textures-materials-and-shaders': '贴图、材质与着色器',
  'avatar-animations-physbones-gestures-and-gimmicks': '动画、形态键与物理',
  'avatar-systems-and-tools': '系统与工具', world: '世界与场景',
};
export const featureNames = { quest: 'Quest', vrcfury: 'VRCFury', ma: 'Modular Avatar', liltoon: 'lilToon', poiyomi: 'Poiyomi' };
const text = (value, limit = 500) => typeof value === 'string' ? value.slice(0, limit) : '';
const array = value => Array.isArray(value) ? value : [];
const fold = value => String(value ?? '').normalize('NFKC').toLocaleLowerCase();
const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : fallback;
const day = 86400000;
const likeCount = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0 ? Math.floor(Number(value)) : null;

function likeHistory(entries) {
  const samples = new Map();
  for (const entry of array(entries).slice(-128)) {
    const at = typeof entry?.at === 'string' ? Date.parse(entry.at) : NaN, likes = likeCount(entry?.likes);
    if (Number.isFinite(at) && likes !== null) samples.set(at, { at: new Date(at).toISOString(), likes });
  }
  return [...samples.values()].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

function recordLikeHistory(previous, likes, now) {
  const samples = likeHistory([
    ...array(previous.like_history),
    { at: previous.likes_observed_at ?? (previous.scraped_at || previous.updated_at), likes: previous.likes },
    ...(likes === null ? [] : [{ at: new Date(now).toISOString(), likes }]),
  ]).filter(sample => Date.parse(sample.at) >= now - 14 * day && Date.parse(sample.at) <= now);
  // Keep the first and last observation each UTC day, so frequent refreshes
  // cannot crowd out the baseline used to measure recent growth.
  const days = new Map();
  for (const sample of samples) {
    const key = sample.at.slice(0, 10), pair = days.get(key);
    days.set(key, pair ? [pair[0], sample] : [sample]);
  }
  return [...days.values()].flat().filter((sample, i, all) => !i || sample.at !== all[i - 1].at).slice(-32);
}

function trendingScore(item, now) {
  const published = Date.parse(item.publishedAt);
  const freshness = Number.isFinite(published) && published <= now ? 2 ** (-(now - published) / (30 * day)) : 0;
  const popularity = Math.log10(1 + item.likes) * (0.2 + 0.8 * freshness);
  const samples = item.likeHistory.filter(sample => Date.parse(sample.at) >= now - 7 * day && Date.parse(sample.at) <= now);
  const first = samples[0], last = samples.at(-1);
  // Short observation intervals must not turn a handful of likes into a huge
  // extrapolated growth rate. Stale growth loses weight after three days.
  if (!first || Date.parse(last.at) - Date.parse(first.at) < day / 4) return popularity;
  const dailyGrowth = Math.max(0, last.likes - first.likes) / Math.max(1, (Date.parse(last.at) - Date.parse(first.at)) / day);
  return popularity + 0.9 * Math.log10(1 + dailyGrowth) * 2 ** (-(now - Date.parse(last.at)) / (3 * day));
}

export function safeImage(value) {
  if (typeof value !== 'string') return '';
  if (/^\/media\/[a-f0-9]{32}\.(?:webp|png|jpe?g)$/.test(value)) return value;
  if (/^\/api\/local\/image\?key=[a-f0-9]{32}\.(?:webp|png|jpe?g)$/.test(value)) return value;
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' && ['cdn.vrcatalogue.com', 'booth.pximg.net', 'booth.p.pixiv.net', 'pixiv.pximg.net'].includes(url.hostname)) return url.href;
  } catch {}
  return '';
}

export function boothId(value) {
  const input = String(value ?? '').trim();
  if (/^[1-9]\d{0,9}$/.test(input)) return Number(input);
  try {
    const url = new URL(input);
    if (url.protocol !== 'https:' || !(url.hostname === 'booth.pm' || url.hostname.endsWith('.booth.pm'))) return null;
    const match = /^\/(?:[a-z]{2}\/)?items\/([1-9]\d{0,9})(?:\.json)?\/?$/.exec(url.pathname);
    return match ? Number(match[1]) : null;
  } catch { return null; }
}

function categoryFallback(item) {
  const name = fold(item.category);
  if (/hair|发型|髪型/.test(name)) return 'hair';
  if (/clothing|shoes|服装|衣装|鞋靴/.test(name)) return 'clothing';
  if (/character|avatar|角色|キャラクター|アバター/.test(name)) return '3d-characters';
  if (/accessor|饰品|配饰|アクセサリー/.test(name)) return 'avatar-accessories';
  if (/texture|shader|material|贴图|材质|テクスチャ/.test(name)) return 'avatar-textures-materials-and-shaders';
  if (/motion|animation|动作|动画/.test(name)) return 'avatar-animations-physbones-gestures-and-gimmicks';
  if (/world|environment|场景|世界/.test(name)) return 'world';
  if (/tool|software|工具|系统/.test(name)) return 'avatar-systems-and-tools';
  return 'avatar-props';
}

export function normalizeItem(raw, categories = []) {
  const id = boothId(raw.id);
  if (!id || !text(raw.title).trim()) throw new Error('每条商品必须包含有效的 id 和 title。');
  const title = text(raw.title);
  const bio = text(raw.bio, 60000);
  const tags = array(raw.tags).map(tag => text(typeof tag === 'string' ? tag : tag?.name, 120)).filter(Boolean).slice(0, 150);
  const smart = array(raw.smart_categories).length ? raw.smart_categories : raw.smart_category ? [raw.smart_category] : [];
  const categorySlugs = [], subcategories = [];
  for (const entry of [...smart].sort((a, b) => Number(b.is_primary === true) - Number(a.is_primary === true))) {
    const parent = categories.find(cat => entry.category_slug ? cat.slug === entry.category_slug : entry.category_id ? cat.id === entry.category_id : fold(cat.en) === fold(entry.category));
    if (!parent) continue;
    categorySlugs.push(parent.slug);
    const children = array(parent.children).filter(child => entry.subcategory_slug ? child.slug === entry.subcategory_slug : entry.subcategory_id ? child.id === entry.subcategory_id : fold(child.en) === fold(entry.sub_category) && (!entry.group_en || child.group_en === entry.group_en));
    const child = children.length === 1 ? children[0] : null;
    if (child) subcategories.push(child.slug);
  }
  if (!categorySlugs.length) categorySlugs.push(categoryFallback(raw));
  const linkedAvatars = array(raw.linked_avatars).slice(0, 500).map(avatar => ({
    slug: text(avatar.slug, 100), en: text(avatar.en, 100), ja: text(avatar.ja, 100),
    ko: text(avatar.ko, 100), image: safeImage(avatar.image_url),
    aliases: array(avatar.aliases).map(alias => text(alias, 100)).filter(Boolean).slice(0, 40),
    verified: typeof avatar.verified === 'boolean' ? avatar.verified : null,
    source: text(avatar.source, 100),
  })).filter(avatar => avatar.slug);
  const avatars = linkedAvatars.filter(avatar => avatar.verified !== false);
  const avatarMentions = linkedAvatars.filter(avatar => avatar.verified === false);
  const unifiedTags = array(raw.unified_tags).map(tag => ({ slug: text(tag.slug, 100), en: text(tag.en, 120), ja: text(tag.ja, 120), ko: text(tag.ko, 120), aliases: array(tag.aliases).map(alias => text(alias, 120)).slice(0, 100) })).filter(tag => tag.slug);
  const tagTokens = [...new Set([...tags, ...unifiedTags.flatMap(tag => [tag.en, tag.ja, tag.ko, ...tag.aliases])].filter(Boolean).map(fold))];
  const local = raw._local && typeof raw._local === 'object' ? raw._local : { known: false, copies: 0, bytes: 0, mtime: 0, types: [], entries: [], category: '' };
  const searchText = fold([id, title, bio, raw.author, ...tags, ...categorySlugs.map(slug => categoryNames[slug]),
    ...array(local.entries).map(entry => entry.folder), local.category,
    ...smart.flatMap(cat => [cat.category, cat.sub_category]), ...linkedAvatars.flatMap(avatar => [avatar.en, avatar.ja, avatar.ko, ...avatar.aliases]), ...tagTokens].join(' '));
  const features = [];
  for (const [key, field, pattern] of [
    ['quest', 'quest_compatible', null], ['vrcfury', 'uses_vrcfury', /vrc\s*fury/],
    ['ma', 'uses_modular_avatar', /modular\s*avatar|モジュラーアバター/],
    ['liltoon', 'uses_liltoon', /lil\s*toon/], ['poiyomi', 'uses_poiyomi', /poiyomi/],
  ]) {
    const label = fold(raw[field]);
    if (/^(?:yes|true|compatible)$/.test(label) || pattern?.test(searchText)) features.push(key);
  }
  let authorUrl = '';
  try { const u = new URL(raw.author_uri); if (u.protocol === 'https:' && (u.hostname === 'booth.pm' || u.hostname.endsWith('.booth.pm'))) authorUrl = u.href; } catch {}
  const published = new Date(raw.published_at);
  return {
    id, title, bio, author: text(raw.author) || 'Unknown', authorUrl, authorIcon: safeImage(raw.author_icon),
    url: `https://booth.pm/ja/items/${id}`, price: number(raw.price_jpy), priceKnown: raw.price_jpy !== null && raw.price_jpy !== undefined && Number.isFinite(Number(raw.price_jpy)), likes: number(raw.likes),
    local,
    purchase: { recorded: raw._purchase?.recorded === true, importedAt: text(raw._purchase?.importedAt, 100) },
    media: array(raw.media).map(safeImage).filter(Boolean).slice(0, 100), tags, avatars, avatarMentions, unifiedTags,
    openData: raw._open_data ? { ...raw._open_data } : null,
    categorySlugs: [...new Set(categorySlugs)], subcategories: [...new Set(subcategories)], features,
    category: text(smart[0]?.category || raw.category), categoryJa: text(smart[0]?.category_ja),
    rating: raw.is_adult || fold(raw.content_rating) === 'nsfw' ? 'adult' : /suggestive/i.test(raw.content_rating ?? '') ? 'suggestive' : 'safe',
    publishedAt: Number.isFinite(published.getTime()) ? published.toISOString() : null,
    updatedAt: text(raw.updated_at || raw.scraped_at, 100), source: text(raw.source, 100),
    rank: number(raw.rank, 999999), likeHistory: likeHistory(raw.like_history),
    variations: array(raw.variations).slice(0, 200).map(v => ({ name: text(v.name), price: number(v.price_jpy ?? v.price), status: text(v.status, 80) })),
    translations: Object.fromEntries(['en', 'ja'].map(lang => [lang, {
      title: text(raw.translations?.[lang]?.title), bio: text(raw.translations?.[lang]?.bio, 60000),
    }])),
    _search: searchText, _tagTokens: tagTokens,
    _facetTags: array(raw.facet_tags).length ? raw.facet_tags : tags,
  };
}

const values = (params, key) => [...new Set(params.getAll(key).flatMap(value => value.split(',')).filter(Boolean))].slice(0, 100);
const hasAny = (selected, actual) => !selected.length || selected.some(value => actual.includes(value));

export function publicRecord({ _search, _tagTokens, _facetTags, ...item }) { return item; }

export function searchCatalog(records, categories, params = new URLSearchParams(), now = Date.now(), avatarDictionary = []) {
  const view = params.get('view') || 'items';
  const q = fold((params.get('q') || '').slice(0, 200)).trim().split(/\s+/).filter(Boolean);
  const selected = Object.fromEntries(['category', 'avatar', 'author', 'tag', 'feature', 'fileType', 'localCategory'].map(key => [key, values(params, key)]));
  const ids = new Set(values(params, 'ids').map(Number));
  const adult = params.get('adult') || 'safe';
  const pmin = number(params.get('min'));
  const pmax = params.has('max') ? number(params.get('max'), Infinity) : Infinity;
  const free = params.get('free') === '1';
  const availability = params.get('availability') || 'all';
  const minBytes = number(params.get('minBytes'));
  const duplicates = params.get('duplicates') === '1';
  const purchase = params.get('purchase') || 'all';
  const includeMentions = params.get('includeMentions') === '1';
  const selectedAvatars = item => includeMentions ? [...item.avatars, ...array(item.avatarMentions)] : item.avatars;
  function matches(item, omit = '') {
    if ((view === 'purchased' || purchase === 'recorded' || purchase === 'missing-local') && !item.purchase.recorded) return false;
    if (purchase === 'not-recorded' && item.purchase.recorded) return false;
    if (purchase === 'missing-local' && !(item.local.known && item.local.copies === 0)) return false;
    if (view === 'avatars' && !item.categorySlugs.includes('3d-characters')) return false;
    if (view === 'local' && !(item.local.known && item.local.copies > 0)) return false;
    if (availability === 'local' && !(item.local.known && item.local.copies > 0)) return false;
    if (availability === 'missing' && !(item.local.known && item.local.copies === 0)) return false;
    if (minBytes && !(item.local.known && item.local.copies > 0 && item.local.bytes >= minBytes)) return false;
    if (duplicates && !(item.local.known && item.local.copies > 1)) return false;
    if (view === 'favourites' && !ids.has(item.id)) return false;
    if (q.some(term => !item._search.includes(term))) return false;
    if ((adult === 'safe' && item.rating === 'adult') || (adult === 'suggestive' && item.rating !== 'suggestive') || (adult === 'adult' && item.rating !== 'adult')) return false;
    if (item.price < pmin || item.price > pmax || (free && (!item.priceKnown || item.price !== 0))) return false;
    if (!item.priceKnown && (pmin > 0 || Number.isFinite(pmax))) return false;
    if (omit !== 'category' && !hasAny(selected.category, [...item.categorySlugs, ...item.subcategories])) return false;
    if (omit !== 'avatar' && !hasAny(selected.avatar, selectedAvatars(item).map(avatar => avatar.slug))) return false;
    if (omit !== 'author' && selected.author.length && !selected.author.includes(item.author)) return false;
    if (omit !== 'tag' && selected.tag.some(tag => !array(item._tagTokens).includes(fold(tag)))) return false;
    if (omit !== 'feature' && selected.feature.some(feature => !item.features.includes(feature))) return false;
    if (omit !== 'fileType' && !hasAny(selected.fileType, array(item.local.types))) return false;
    if (omit !== 'localCategory' && selected.localCategory.length && !(item.local.known && item.local.copies && selected.localCategory.includes(item.local.category))) return false;
    return true;
  }
  const result = records.filter(item => matches(item));
  const sort = params.get('sort') || 'trending';
  const scores = new Map(result.map(item => [item.id, trendingScore(item, now)]));
  const comparators = {
    trending: (a, b) => scores.get(b.id) - scores.get(a.id) || b.likes - a.likes || (Date.parse(b.publishedAt) || 0) - (Date.parse(a.publishedAt) || 0),
    newest: (a, b) => (Date.parse(b.publishedAt) || 0) - (Date.parse(a.publishedAt) || 0),
    oldest: (a, b) => (Date.parse(a.publishedAt) || 0) - (Date.parse(b.publishedAt) || 0),
    'price-asc': (a, b) => a.price - b.price,
    'price-desc': (a, b) => b.price - a.price,
    likes: (a, b) => b.likes - a.likes,
    title: (a, b) => a.title.localeCompare(b.title, 'ja'),
    'local-size': (a, b) => b.local.bytes - a.local.bytes,
    'local-newest': (a, b) => b.local.mtime - a.local.mtime,
    'local-copies': (a, b) => b.local.copies - a.local.copies,
  };
  result.sort((a, b) => (sort.startsWith('price') && a.priceKnown !== b.priceKnown ? Number(b.priceKnown) - Number(a.priceKnown) : (comparators[sort] || comparators.trending)(a, b)) || a.id - b.id);
  const pageSize = [20, 40, 60, 100].includes(Number(params.get('pageSize'))) ? Number(params.get('pageSize')) : 20;
  const totalPages = Math.max(1, Math.ceil(result.length / pageSize));
  const page = Math.min(totalPages, Math.max(1, Math.floor(number(params.get('page'), 1))));
  const countMap = (omit, keys) => {
    const map = new Map();
    for (const item of records) if (matches(item, omit)) for (const key of new Set(keys(item))) map.set(key, (map.get(key) || 0) + 1);
    return map;
  };
  const catCounts = countMap('category', item => [...item.categorySlugs, ...item.subcategories]);
  const avatarCounts = countMap('avatar', item => selectedAvatars(item).map(avatar => avatar.slug));
  const authorCounts = countMap('author', item => [item.author]);
  const tagCounts = countMap('tag', item => item._facetTags || item.tags);
  const featureCounts = countMap('feature', item => item.features);
  const typeCounts = countMap('fileType', item => item.local.copies ? array(item.local.types) : []);
  const localCategoryCounts = countMap('localCategory', item => item.local.copies ? [item.local.category] : []);
  const avatarMap = new Map(avatarDictionary.map(avatar => [avatar.slug, avatar]));
  for (const item of records) for (const avatar of [...item.avatars, ...array(item.avatarMentions)]) {
    const previous = avatarMap.get(avatar.slug);
    avatarMap.set(avatar.slug, { ...previous, ...avatar, aliases: [...new Set([...array(previous?.aliases), ...array(avatar.aliases)])] });
  }
  const tagMap = new Map(records.flatMap(item => array(item.unifiedTags).map(tag => [tag.en, tag])));
  const authorMap = new Map(records.map(item => [item.author, item.authorIcon]));
  const sorted = map => [...map].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return {
    count: result.length, totalRecords: records.length, page, pageSize, totalPages, sort,
    items: result.slice((page - 1) * pageSize, page * pageSize).map(publicRecord),
    facets: {
      categories: categories.map(cat => ({ slug: cat.slug, en: cat.en, ja: cat.ja, label: categoryNames[cat.slug] || cat.en, mode: cat.mode, count: catCounts.get(cat.slug) || 0,
        children: array(cat.children).map(child => ({ slug: child.slug, en: child.en, ja: child.ja, count: catCounts.get(child.slug) || 0 })) })),
      avatars: sorted(new Map([...avatarMap.keys()].map(slug => [slug, avatarCounts.get(slug) || 0]))).map(([slug, count]) => ({ ...avatarMap.get(slug), image: safeImage(avatarMap.get(slug)?.image || avatarMap.get(slug)?.image_url), count })),
      authors: sorted(authorCounts).map(([name, count]) => ({ name, image: authorMap.get(name), count })),
      tags: sorted(tagCounts).slice(0, 250).map(([name, count]) => ({ ...tagMap.get(name), name, count })),
      features: Object.entries(featureNames).map(([key, name]) => ({ key, name, count: featureCounts.get(key) || 0 })),
      fileTypes: sorted(typeCounts).map(([name, count]) => ({ name, count })),
      localCategories: sorted(localCategoryCounts).map(([name, count]) => ({ name, count })),
    },
  };
}

export function boothToRecord(data, previous = {}, avatars = [], now = Date.now()) {
  const likes = likeCount(data.wish_lists_count), observedAt = new Date(now).toISOString();
  const history = recordLikeHistory(previous, likes, now);
  const tags = array(data.tags).map(tag => typeof tag === 'string' ? tag : tag.name).filter(Boolean);
  const searchable = fold([data.name, ...tags].join(' '));
  const linked = avatars.filter(avatar => [avatar.en, avatar.ja, avatar.ko, avatar.slug, ...array(avatar.aliases)].filter(Boolean).some(name => {
    const n = fold(name); return n.length >= 2 && searchable.includes(n);
  }));
  const variations = array(data.variations).map(v => ({ id: String(v.id), name: text(v.name), price_jpy: number(v.price), status: text(v.status), type: text(v.type) }));
  const prices = variations.map(v => v.price_jpy);
  return {
    ...previous, id: data.id, title: text(data.name), bio: text(data.description, 60000),
    uri: `https://booth.pm/ja/items/${data.id}`, author: text(data.shop?.name), author_uri: text(data.shop?.url), author_icon: safeImage(data.shop?.thumbnail_url),
    category: text(data.category?.name), price_jpy: prices.length ? Math.min(...prices) : number(String(data.price).replace(/[^\d.]/g, '')),
    likes: likes ?? number(previous.likes), like_history: history, likes_observed_at: history.at(-1)?.at || '',
    media: array(data.images).map(image => safeImage(image.original)).filter(Boolean),
    source_media: array(data.images).map(image => safeImage(image.original)).filter(Boolean),
    tags, variations, is_adult: !!data.is_adult, content_rating: data.is_adult ? 'NSFW' : 'SFW',
    published_at: text(data.published_at), scraped_at: observedAt, updated_at: observedAt,
    source: 'booth', linked_avatars: array(previous.linked_avatars).length ? previous.linked_avatars : linked.map(a => ({ ...a, image_url: a.image_url || a.image, verified: false, source: 'listing-text' })),
    // Old translated copy must not override refreshed BOOTH text.
    translations: {}, rank: previous.rank ?? 999999,
  };
}

export class CatalogStore {
  constructor(dataDir, metadata = null) { this.dir = dataDir; this.file = path.join(dataDir, 'catalog.json'); this.queue = Promise.resolve(); this.metadata = metadata; }
  async load() {
    await mkdir(this.dir, { recursive: true });
    try { this.data = JSON.parse(await readFile(this.file, 'utf8')); }
    catch (error) {
      if (error.code !== 'ENOENT') throw new Error(`目录文件无法读取，已保留原文件：${error.message}`);
      try { await copyFile(path.join(this.dir, 'catalog.seed.json'), this.file); }
      catch (seedError) { if (seedError.code !== 'ENOENT') throw seedError; await writeFile(this.file, JSON.stringify({ source: 'BoothNest', categories: [], items: [], capturedAt: new Date().toISOString() })); }
      this.data = JSON.parse(await readFile(this.file, 'utf8'));
    }
    this.reindex(); return this;
  }
  reindex() {
    this.categories = this.metadata?.categories(array(this.data.categories)) || array(this.data.categories);
    this.avatars = this.metadata?.avatars(array(this.data.avatars)) || array(this.data.avatars);
    this.records = this.data.items.map(item => normalizeItem(this.enrich(item), this.categories));
  }
  enrich(item) { return this.metadata?.enrich(item) || item; }
  merge(items) {
    const operation = this.queue.then(async () => {
      if (!Array.isArray(items) || !items.length || items.length > 5000) throw new Error('请导入包含 1–5000 条商品的 JSON。');
      // Validate the whole batch before writing anything.
      for (const item of items) normalizeItem(item, this.categories);
      await mkdir(path.join(this.dir, 'backups'), { recursive: true });
      const stamp = new Date().toISOString().replace(/[:.]/g, '-') + '-' + randomUUID().slice(0, 8);
      await copyFile(this.file, path.join(this.dir, 'backups', `catalog-${stamp}.json`));
      const merged = new Map(this.data.items.map(item => [Number(item.id), item]));
      let added = 0, updated = 0;
      for (const item of items) {
        if (merged.has(Number(item.id))) updated++; else added++;
        merged.set(Number(item.id), { ...item, id: Number(item.id) });
      }
      const next = { ...this.data, updatedAt: new Date().toISOString(), items: [...merged.values()] };
      const tmp = this.file + '.tmp';
      await writeFile(tmp, JSON.stringify(next, null, 2));
      await rename(tmp, this.file);
      this.data = next; this.reindex();
      return { added, updated, total: this.records.length };
    });
    this.queue = operation.catch(() => {});
    return operation;
  }
}
