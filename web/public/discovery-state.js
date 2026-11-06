// Shared, dependency-free validation for local browsing preferences.
export const MAX_SAVED_SEARCHES = 50;
export const MAX_RECENT_VIEWS = 500;
const arrays = ['category', 'avatar', 'author', 'tag', 'excludeTag', 'feature', 'fileType', 'localCategory'];
const enums = {
  view: ['items', 'avatars', 'favourites', 'local', 'purchased', 'recent'],
  sort: ['trending', 'newest', 'oldest', 'likes', 'price-asc', 'price-desc', 'title', 'local-size', 'local-newest', 'local-copies'],
  adult: ['safe', 'all', 'suggestive', 'adult'],
  availability: ['all', 'local', 'missing'],
  purchase: ['all', 'recorded', 'missing-local', 'not-recorded'],
};
const folded = value => value.normalize('NFKC').toLowerCase();

// Only filter state is stored. Transient page numbers, paths, tokens and result IDs are never included.
export function savedFilterQuery(input) {
  const source = new URLSearchParams(typeof input === 'string' ? input.slice(0, 16000) : '');
  const result = new URLSearchParams();
  for (const [key, allowed] of Object.entries(enums)) {
    const value = source.get(key);
    if (allowed.includes(value)) result.set(key, value);
  }
  const q = (source.get('q') || '').trim().slice(0, 200);
  if (q) result.set('q', q);
  for (const key of arrays) {
    const seen = new Set();
    for (const value of source.getAll(key).flatMap(value => value.split(','))) {
      const clean = value.trim().slice(0, 200);
      if (!clean || seen.has(clean) || seen.size >= 50) continue;
      if (key === 'tag' && source.getAll('excludeTag').flatMap(value => value.split(',')).some(tag => folded(tag.trim()) === folded(clean))) continue;
      seen.add(clean); result.append(key, clean);
    }
  }
  for (const key of ['free', 'includeMentions', 'duplicates']) if (source.get(key) === '1') result.set(key, '1');
  for (const key of ['min', 'max', 'minBytes']) {
    const value = Number(source.get(key));
    if (source.has(key) && Number.isSafeInteger(value) && value >= 0) result.set(key, String(value));
  }
  if ([20, 40, 60, 100].includes(Number(source.get('pageSize')))) result.set('pageSize', source.get('pageSize'));
  return result.toString();
}

export function privateFilterQuery(input) {
  const query = new URLSearchParams(input);
  return ['local', 'purchased', 'favourites', 'recent'].includes(query.get('view')) ||
    ['local', 'missing'].includes(query.get('availability')) ||
    (query.has('purchase') && query.get('purchase') !== 'all') ||
    ['fileType', 'localCategory', 'minBytes', 'duplicates'].some(key => query.has(key));
}

export function normalizeSavedSearches(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  return value.flatMap(entry => {
    if (!entry || typeof entry !== 'object' || typeof entry.id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(entry.id) ||
      typeof entry.name !== 'string' || !entry.name.trim() || typeof entry.query !== 'string' || entry.query.length > 16000 || seen.has(entry.id)) return [];
    seen.add(entry.id);
    return [{ id: entry.id, name: entry.name.trim().slice(0, 80), query: savedFilterQuery(entry.query) }];
  }).slice(0, MAX_SAVED_SEARCHES);
}

export function normalizeRecentViews(value) {
  if (!Array.isArray(value)) return [];
  const newest = new Map();
  for (const entry of value) {
    if (!entry || !Number.isSafeInteger(entry.id) || entry.id <= 0 || !Number.isSafeInteger(entry.at) || entry.at <= 0 || entry.at > Date.now() + 60000) continue;
    if (!newest.has(entry.id) || newest.get(entry.id).at < entry.at) newest.set(entry.id, { id: entry.id, at: entry.at });
  }
  return [...newest.values()].sort((a, b) => b.at - a.at).slice(0, MAX_RECENT_VIEWS);
}

export function recordRecentView(value, id, now = Date.now()) {
  if (!Number.isSafeInteger(id) || id <= 0) return normalizeRecentViews(value);
  return normalizeRecentViews([{ id, at: now }, ...normalizeRecentViews(value).filter(entry => entry.id !== id)]);
}

export function validDiscoveryPreference(key, value) {
  const normalized = key === 'saved-searches' ? normalizeSavedSearches(value) : normalizeRecentViews(value);
  if (!Array.isArray(value) || normalized.length !== value.length) return false;
  return value.every((entry, index) => {
    const expected = normalized[index];
    const keys = key === 'saved-searches' ? ['id', 'name', 'query'] : ['id', 'at'];
    return entry && Object.keys(entry).length === keys.length && keys.every(field => entry[field] === expected[field]);
  });
}
