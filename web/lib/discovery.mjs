import { searchCatalog } from './catalog.mjs';

const fold = value => String(value || '').normalize('NFKC').toLowerCase();

// Search only the local, already indexed catalogue. No BOOTH or model API requests.
export function searchPalette(records, categories, params, avatars = []) {
  const q = (params.get('q') || '').trim().slice(0, 200);
  if (!q) return { items: [], avatars: [], authors: [], tags: [] };
  const adult = ['safe', 'all', 'suggestive', 'adult'].includes(params.get('adult')) ? params.get('adult') : 'safe';
  const visible = records.filter(item => adult === 'all' || (adult === 'safe' ? item.rating !== 'adult' : item.rating === adult));
  const terms = fold(q).split(/\s+/).filter(Boolean);
  const matches = values => terms.every(term => fold(values.filter(Boolean).join(' ')).includes(term));
  const avatarMap = new Map(avatars.map(avatar => [avatar.slug, { ...avatar, count: 0 }]));
  const authorMap = new Map(), tagMap = new Map();
  for (const item of visible) {
    for (const avatar of item.avatars) {
      const previous = avatarMap.get(avatar.slug);
      avatarMap.set(avatar.slug, { ...previous, ...avatar, count: (previous?.count || 0) + 1 });
    }
    if (item.author) authorMap.set(item.author, { name: item.author, count: (authorMap.get(item.author)?.count || 0) + 1 });
    const unified = new Map(item.unifiedTags.map(tag => [fold(tag.en), tag]));
    for (const name of new Set(item.tags)) {
      tagMap.set(name, { ...unified.get(fold(name)), name, count: (tagMap.get(name)?.count || 0) + 1 });
    }
  }
  const top = (entries, fields) => [...entries].filter(entry => entry.count && matches(fields(entry)))
    .sort((a, b) => b.count - a.count).slice(0, 6);
  const result = searchCatalog(visible, categories, new URLSearchParams({ q, adult: 'all', pageSize: '20' }));
  return {
    items: result.items.slice(0, 6).map(item => ({ id: item.id, title: item.title, author: item.author, image: item.media[0] || '', price: item.priceKnown ? item.price : null })),
    avatars: top(avatarMap.values(), avatar => [avatar.en, avatar.ja, avatar.ko, avatar.slug, ...(avatar.aliases || [])])
      .map(avatar => ({ slug: avatar.slug, en: avatar.en, ja: avatar.ja, count: avatar.count })),
    authors: top(authorMap.values(), author => [author.name]),
    tags: top(tagMap.values(), tag => [tag.name, tag.en, tag.ja, tag.ko, ...(tag.aliases || [])])
      .map(tag => ({ name: tag.name, count: tag.count })),
  };
}
