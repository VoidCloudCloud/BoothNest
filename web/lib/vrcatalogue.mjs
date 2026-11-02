import { access } from 'node:fs/promises';

const fold = value => String(value ?? '').normalize('NFKC').toLocaleLowerCase();
const list = value => Array.isArray(value) ? value : [];

export class VRCatalogueIndex {
  constructor(file) {
    this.file = file; this.cache = new Map(); this.enabled = false; this.error = '';
    this.avatarList = []; this.categoryList = []; this.tagNames = new Map(); this.info = {};
  }
  async init() {
    if (!this.file) return this;
    try { await access(this.file); } catch (error) {
      this.error = error.code === 'ENOENT' ? '未找到开放元数据索引；现有目录仍可使用。' : '开放元数据索引无法读取；现有目录仍可使用。';
      return this;
    }
    try {
      const { DatabaseSync } = await import('node:sqlite');
      this.db = new DatabaseSync(this.file, { readOnly: true, enableExtensions: false });
      this.db.exec('PRAGMA query_only=ON; PRAGMA trusted_schema=OFF;');
      this.info = Object.fromEntries(this.db.prepare('SELECT key,value FROM dataset_info').all().map(row => [row.key, row.value]));
      const aliases = new Map();
      for (const { avatar_id, alias } of this.db.prepare('SELECT avatar_id,alias FROM avatar_aliases').all()) {
        if (!aliases.has(avatar_id)) aliases.set(avatar_id, []);
        aliases.get(avatar_id).push(alias);
      }
      this.avatarList = this.db.prepare('SELECT * FROM avatars ORDER BY avatar_id').all().map(row => ({
        id: row.avatar_id, slug: row.slug, en: row.name_en, ja: row.name_ja, ko: row.name_ko,
        aliases: aliases.get(row.avatar_id) || [], gender: row.gender, booth_item_id: row.booth_item_id,
      })).filter(avatar => typeof avatar.slug === 'string' && avatar.slug);
      this.avatarMap = new Map(this.avatarList.map(avatar => [avatar.id, avatar]));
      const children = this.db.prepare('SELECT * FROM subcategories ORDER BY subcategory_id').all();
      this.categoryList = this.db.prepare('SELECT * FROM categories ORDER BY category_id').all().map(row => ({
        id: row.category_id, slug: row.slug, en: row.name_en, ja: row.name_ja, ko: row.name_ko,
        mode: row.slug === '3d-characters' ? 'avatars' : 'items',
        children: children.filter(child => child.category_id === row.category_id).map(child => ({
          id: child.subcategory_id, slug: child.slug, en: child.name_en, ja: child.name_ja, ko: child.name_ko,
          group_en: child.group_en, group_ja: child.group_ja, group_ko: child.group_ko,
        })),
      }));
      this.subcategoryMap = new Map(this.categoryList.flatMap(parent => parent.children.map(child => [child.id, { parent, child }])));
      const unified = this.db.prepare('SELECT * FROM unified_tags').all();
      this.tagMap = new Map(unified.map(row => [row.unified_tag_id, { slug: row.slug, en: row.name_en, ja: row.name_ja, ko: row.name_ko }]));
      for (const row of this.db.prepare('SELECT name,unified_tag_id FROM tags').all()) {
        const tag = this.tagMap.get(row.unified_tag_id);
        (tag.aliases ||= []).push(row.name);
        this.tagNames.set(fold(row.name), tag);
      }
      for (const tag of this.tagMap.values()) for (const name of [tag.en, tag.ja, tag.ko]) if (name) this.tagNames.set(fold(name), tag);
      this.itemQuery = this.db.prepare('SELECT * FROM items WHERE item_id=?');
      this.avatarQuery = this.db.prepare('SELECT avatar_id,verified FROM item_avatar_compatibility WHERE item_id=? ORDER BY verified DESC,avatar_id');
      this.categoryQuery = this.db.prepare('SELECT subcategory_id,is_primary FROM item_categories WHERE item_id=? ORDER BY is_primary DESC,subcategory_id');
      this.enabled = true;
    } catch (error) {
      this.db?.close(); this.db = null;
      this.error = '开放元数据索引未启用，请检查索引文件及 Node.js 22.13+；现有目录仍可使用。';
    }
    return this;
  }
  status() {
    return {
      enabled: this.enabled, error: this.error, source: 'VRCatalogue Open Data',
      revision: this.info.source_revision || '', snapshotAt: this.info.snapshot_at || '',
      license: this.info.license || 'CC-BY-4.0', url: this.info.dataset_url || 'https://huggingface.co/datasets/vrcatalogue/vrcatalogue-open-data',
      licenseUrl: 'https://creativecommons.org/licenses/by/4.0/',
      items: Number(this.info['rows.items']) || 0, avatars: this.avatarList.length,
      sourceAvatarRows: Number(this.info['rows.avatars']) || this.avatarList.length,
      aliases: Number(this.info['rows.avatar_aliases']) || 0,
      matchedItems: [...this.cache.values()].filter(Boolean).length,
    };
  }
  categories(previous = []) {
    const merged = new Map(previous.map(category => [category.slug, category]));
    for (const category of this.categoryList) {
      const old = merged.get(category.slug);
      const children = new Map(list(old?.children).map(child => [child.slug, child]));
      for (const child of category.children) children.set(child.slug, { ...child, ...children.get(child.slug) });
      merged.set(category.slug, { ...category, ...old, children: [...children.values()] });
    }
    return [...merged.values()];
  }
  avatars(previous = []) {
    const merged = new Map(this.avatarList.map(avatar => [avatar.slug, avatar]));
    for (const avatar of previous) merged.set(avatar.slug, { ...merged.get(avatar.slug), ...avatar, aliases: [...new Set([...list(merged.get(avatar.slug)?.aliases), ...list(avatar.aliases)])] });
    return [...merged.values()];
  }
  lookup(id) {
    if (!this.enabled) return null;
    if (this.cache.has(id)) return this.cache.get(id);
    const row = this.itemQuery.get(id);
    if (!row) { this.cache.set(id, null); return null; }
    const avatars = this.avatarQuery.all(id).map(relation => ({ ...this.avatarMap.get(relation.avatar_id), verified: !!relation.verified, source: 'vrcatalogue-open-data' }));
    const categories = this.categoryQuery.all(id).map(relation => {
      const { parent, child } = this.subcategoryMap.get(relation.subcategory_id);
      return {
        category: parent.en, sub_category: child.en, category_slug: parent.slug, subcategory_slug: child.slug,
        category_id: parent.id, subcategory_id: child.id, is_primary: !!relation.is_primary,
        category_ja: parent.ja, sub_category_ja: child.ja, group_en: child.group_en,
      };
    });
    const value = { row, avatars, categories };
    this.cache.set(id, value);
    return value;
  }
  enrich(raw) {
    if (!this.enabled) return raw;
    const metadata = this.lookup(Number(raw.id));
    const tags = list(raw.tags).map(tag => typeof tag === 'string' ? tag : tag?.name).filter(Boolean);
    const unifiedTags = [...new Map(tags.map(tag => this.tagNames.get(fold(tag))).filter(Boolean).map(tag => [tag.slug, tag])).values()];
    const facetTags = [...new Set(tags.map(tag => this.tagNames.get(fold(tag))?.en || tag))];
    if (!metadata) return { ...raw, unified_tags: unifiedTags, facet_tags: facetTags };
    const avatars = new Map(list(raw.linked_avatars).map(avatar => [avatar.slug, avatar]));
    for (const avatar of metadata.avatars) {
      const previous = avatars.get(avatar.slug);
      if (previous?.source === 'manual') continue;
      avatars.set(avatar.slug, { ...previous, ...avatar, image_url: previous?.image_url || previous?.image || '' });
    }
    const current = list(raw.smart_categories).length ? raw.smart_categories : raw.smart_category ? [raw.smart_category] : [];
    const smart = current.length ? current.map(entry => {
      if (entry.subcategory_slug || entry.subcategory_id) return entry;
      const matches = metadata.categories.filter(candidate => fold(candidate.category) === fold(entry.category) && fold(candidate.sub_category) === fold(entry.sub_category));
      return matches.length === 1 ? { ...matches[0], ...entry } : entry;
    }) : metadata.categories;
    const labels = {};
    for (const field of ['quest_compatible','uses_liltoon','uses_poiyomi','uses_vrcfury','uses_modular_avatar']) {
      labels[field] = raw[field] ?? metadata.row[field];
    }
    const ratings = { sfw: 0, suggestive: 1, nsfw: 2 };
    const currentRating = fold(raw.content_rating), snapshotRating = fold(metadata.row.content_rating);
    const rating = (ratings[currentRating] ?? -1) >= (ratings[snapshotRating] ?? -1) ? raw.content_rating : metadata.row.content_rating;
    return {
      ...raw, ...labels, content_rating: rating,
      linked_avatars: [...avatars.values()], smart_categories: smart,
      unified_tags: unifiedTags, facet_tags: facetTags,
      _open_data: { source: 'VRCatalogue Open Data', revision: this.info.source_revision, snapshotAt: this.info.snapshot_at, license: this.info.license },
    };
  }
  close() { this.db?.close(); this.db = null; }
}
