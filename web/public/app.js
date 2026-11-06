import { extractLibraryPage } from './purchase-reader.js';
import { initLocalTools } from './local-tools.js';
import { initLocalScan } from './local-scan.js';
import { initPurchaseSync } from './purchase-sync.js';
import { subcategoryLabel } from './category-labels.js';
import { initDiscovery } from './discovery.js';
import { savedFilterQuery } from './discovery-state.js';
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const icons = {
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
  layers: '<path d="m12 3 10 6-10 6L2 9Z"/><path d="m2 13 10 6 10-6M2 17l10 6 10-6"/>',
  hanger: '<path d="M10 6a2 2 0 1 1 4 0c0 2-2 2-2 4l9 6a1 1 0 0 1-.5 2H3.5a1 1 0 0 1-.5-2l9-6"/>',
  avatar: '<circle cx="12" cy="8" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  coins: '<path d="M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
  x: '<path d="m6 6 12 12M6 18 18 6"/>',
  filter: '<path d="M3 5h18l-7 8v6l-4 2v-8Z"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  flame: '<path d="M12 3c1 5 7 6 7 12a7 7 0 0 1-14 0c0-4 3-6 3-6 0 3 2 4 2 4s4-4 2-10Z"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 15v5h16v-5"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  refresh: '<path d="M20 7A9 9 0 0 0 5 5L2 9m0-6v6h6M4 17a9 9 0 0 0 15 2l3-4m0 6v-6h-6"/>',
  plus: '<path d="M12 4v16M4 12h16"/>',
  box: '<path d="m12 2 9 5v10l-9 5-9-5V7Zm0 10v10M3 7l9 5 9-5M7.5 4.5l9 5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  history: '<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v5l3 2"/>',
};
function icon(name, className = '') { return `<svg class="icon ${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.box}</svg>`; }
function hydrateIcons(root = document) { root.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); }); }

const dictionary = {
  zh: {
    browse: '浏览', about: '关于', dataLibrary: '数据管理', noticeTitle: '你的素材探索，不必止步。', noticeBody: '本地目录已就绪，搜索、筛选和收藏均可独立使用。',
    filter: '筛选', categories: '素材分类', clear: '清除', features: '功能与支持', featureNote: '结合开放数据和商品说明识别；请以作者页面为准。',
    content: '内容分级', price: '价格', freeOnly: '仅免费', avatars: '适配模型', authors: '创作者', tags: '标签', localFirst: '本地优先 · 收藏与设置保存在本机',
    footer: '为每一次灵感，找到合适的素材。', items: '素材', models: '模型', favourites: '收藏', noFilters: '尚未设置筛选，探索所有素材', filtersApplied: '项筛选已启用', reset: '重置全部',
    search: '搜索服装、发型、配饰或创作者…', avatarSearch: '搜索模型…', authorSearch: '搜索创作者…', tagSearch: '搜索标签…', results: '件素材', free: '免费', from: '起', metadata: '查看详细信息', variations: '个规格', tagUnit: '个标签',
    saved: '已加入收藏', unsaved: '已取消收藏', save: '收藏', savedLabel: '已收藏', noResults: '没有找到匹配的素材', noResultsHint: '试试其他关键词，或减少一些筛选条件。', emptyFavourites: '把喜欢的素材，留在这里。', emptyFavouritesHint: '点击商品卡片上的爱心，即可加入本地收藏。', explore: '去探索素材',
    noOptions: '暂无匹配选项', count: '件已收录', snapshot: '快照', local: '本地目录', safe: '安全内容', all: '全部内容', suggestive: '仅暗示性内容', adult: '仅成人内容',
    trending: '热门精选', trendingHint: '根据已收录商品的收藏数、近 7 天收藏增长和发布时间排序，随同步更新。', newest: '最新发布', oldest: '最早发布', likes: '最多喜欢', 'price-asc': '价格从低到高', 'price-desc': '价格从高到低', title: '名称 A–Z', perPage: '件 / 页',
    buy: '前往 BOOTH', description: '商品说明', supportedAvatars: '适配模型', variants: '规格与价格', original: '日元原价', approximate: '换算仅供参考', published: '发布于', refresh: '从 BOOTH 更新', updated: '已从 BOOTH 更新',
    dataTitle: '你的本地素材库', dataSubtitle: '保存灵感，也保留继续探索的自由。', addTitle: '添加 BOOTH 商品', addHint: '粘贴商品链接或数字 ID，读取公开商品信息与预览图。', add: '添加 / 更新', adding: '正在读取 BOOTH…',
    backupTitle: '备份与迁移', exportCatalog: '导出目录与收藏', exportFavourites: '仅导出收藏', import: '导入 JSON', importHint: '可导入本工具导出的目录或收藏。目录合并前会自动备份，不覆盖无关商品。',
    dataNote: '目录来自已收录的 BOOTH 商品与本地库存，开放数据补充分类和适配。缓存预览图可离线查看；价格以 BOOTH 页面为准。', close: '关闭', imported: '导入完成', exporting: '正在导出…', added: '已收录', currencyHint: '使用参考汇率；实际价格以 BOOTH 日元标价为准。', error: '操作失败，请重试。', retry: '重试', loadError: '暂时无法读取本地目录', chooseFile: '选择 JSON 文件',
    onlineSearch: '从 BOOTH 搜索并收录', onlineHint: '自动加上 VRChat 关键词，每次读取最多 6 条公开商品。优先收录目录中没有的结果。', onlineBusy: '正在搜索并保存预览图…', onlinePlaceholder: '例如：VRCFury、兔耳、まよ…',
  },
  en: {
    browse: 'Browse', about: 'About', dataLibrary: 'My library', noticeTitle: 'Keep exploring. Keep your finds.', noticeBody: 'Your local catalogue is ready. Search, filter and save independently.',
    filter: 'Filters', categories: 'Categories', clear: 'Clear', features: 'Features & support', featureNote: 'From open metadata and listings; check compatibility with the creator.',
    content: 'Content', price: 'Price', freeOnly: 'Free only', avatars: 'Avatars', authors: 'Creators', tags: 'Tags', localFirst: 'Local first · favourites in this browser',
    footer: 'Find the right asset for your next idea.', items: 'Items', models: 'Avatars', favourites: 'Favourites', noFilters: 'No filters applied. Explore all items.', filtersApplied: 'filters applied', reset: 'Reset all',
    search: 'Search clothes, hair, accessories or creators…', avatarSearch: 'Search avatars…', authorSearch: 'Search creators…', tagSearch: 'Search tags…', results: 'results', free: 'Free', from: '+', metadata: 'View metadata', variations: 'variants', tagUnit: 'tags',
    saved: 'Added to favourites', unsaved: 'Removed from favourites', save: 'Save', savedLabel: 'Saved', noResults: 'No matching finds', noResultsHint: 'Try another keyword or remove a few filters.', emptyFavourites: 'A little space for your favourite finds.', emptyFavouritesHint: 'Tap the heart on any item to save it to your local collection.', explore: 'Explore items',
    noOptions: 'No matching options', count: 'items indexed', snapshot: 'Snapshot', local: 'Local catalogue', safe: 'Safe content', all: 'All content', suggestive: 'Suggestive only', adult: 'Adult only',
    trending: 'Trending selection', trendingHint: 'Ranks collected listings by likes, observed like growth over the last 7 days and publication date. Updates after sync.', newest: 'Newest', oldest: 'Oldest', likes: 'Most likes', 'price-asc': 'Lowest price', 'price-desc': 'Highest price', title: 'Name A–Z', perPage: 'items / page',
    buy: 'View on BOOTH', description: 'Description', supportedAvatars: 'Supported avatars', variants: 'Variants & prices', original: 'Original price (JPY)', approximate: 'Approximate conversion', published: 'Published', refresh: 'Refresh from BOOTH', updated: 'Updated from BOOTH',
    dataTitle: 'Your local library', dataSubtitle: 'Keep your inspiration. Keep exploring.', addTitle: 'Add a BOOTH item', addHint: 'Paste a product URL or numeric ID to fetch its public listing and previews.', add: 'Add / refresh', adding: 'Reading BOOTH…',
    backupTitle: 'Back up & move', exportCatalog: 'Export library & favourites', exportFavourites: 'Export favourites', import: 'Import JSON', importHint: 'Import an exported library or favourites. A backup is made before merging; unrelated items are kept.',
    dataNote: 'The catalogue combines collected BOOTH listings and local inventory. Open data supplements categories and compatibility. Cached previews work offline; check prices on BOOTH.', close: 'Close', imported: 'Import complete', exporting: 'Exporting…', added: 'Added to library', currencyHint: 'Reference exchange rates only. Check actual JPY prices on BOOTH.', error: 'Something went wrong. Please retry.', retry: 'Retry', loadError: 'Could not load the local library', chooseFile: 'Choose a JSON file',
    onlineSearch: 'Search & collect from BOOTH', onlineHint: 'Adds VRChat to your query and reads up to 6 public listings at a time, prioritising new items.', onlineBusy: 'Searching and caching previews…', onlinePlaceholder: 'e.g. VRCFury, bunny ears, まよ…',
  },
};
Object.assign(dictionary.zh, {
  localView: '本地库', localFilters: '本地文件筛选', connectSettings: '连接设置', availability: '商品范围',
  availabilityAll: '全部商品', availabilityLocal: '本地库已收录', availabilityMissing: '扫描中未收录',
  localCategory: '本地文件分类', entryType: '本地文件类型', folder: '文件夹', localSize: '本地体积', anySize: '不限',
  duplicates: '仅有多个本地副本的商品', scanBasis: '依据最近扫描；定位时检查文件是否存在。',
  localScopeHint: '以下文件条件仅匹配本地商品；选择“全部商品”可清除这些条件。通用分类请用上方“素材分类”。',
  'local-size': '本地体积从大到小', 'local-newest': '本地最近修改', 'local-copies': '本地条目最多',
  localUnknown: '本地状态未知', localMissing: '扫描中未收录', localPresent: '本地库已收录',
  entries: '个条目', localLocations: '本地文件位置', reveal: '定位', revealed: '已请求在资源管理器中定位',
  disconnected: '尚未连接本地库', connectLibrary: '连接本地库', libraryConnection: '本地库连接',
  connectionHint: '连接已有库存，或点击「扫描下载目录」建立和更新素材库。外部旧库会在首次扫描时复制到新版数据目录。',
  pathLabel: '数据目录或 dataset.json 绝对路径', connect: '连接', reloadLibrary: '刷新快照', disconnect: '断开连接',
  connectionSaved: '本地库连接已更新', unidentified: '个未识别条目', discovery: '探索目录', localProducts: '本地商品',
  union: '合并去重', scanned: '最近扫描', unknownPrice: '价格未知',
  exportCatalog: '导出探索目录与收藏', importHint: '导入本工具的目录或收藏；合并前自动备份。导出不包含本地库存与文件路径。',
});
Object.assign(dictionary.en, {
  localView: 'Local', localFilters: 'Local file filters', connectSettings: 'Connection', availability: 'Item scope',
  availabilityAll: 'All items', availabilityLocal: 'In local scan', availabilityMissing: 'Absent from scan',
  localCategory: 'Local file categories', entryType: 'Local file type', folder: 'Folder', localSize: 'Local size', anySize: 'Any size',
  duplicates: 'Items with multiple local copies', scanBasis: 'Based on the latest scan. Files are checked when located.',
  localScopeHint: 'File conditions below only match local items. Choose “All items” to clear them. Use Categories above to browse by item type.',
  'local-size': 'Largest local size', 'local-newest': 'Recently modified locally', 'local-copies': 'Most local entries',
  localUnknown: 'Local status unknown', localMissing: 'Absent from scan', localPresent: 'In local scan',
  entries: 'entries', localLocations: 'Local file locations', reveal: 'Locate', revealed: 'Requested location in Explorer',
  disconnected: 'Local library disconnected', connectLibrary: 'Connect local library', libraryConnection: 'Local library connection',
  connectionHint: 'Connect an existing library or use Scan downloads to create and refresh your inventory. External libraries are copied to the managed data directory before scanning.',
  pathLabel: 'Absolute library directory or dataset.json path', connect: 'Connect', reloadLibrary: 'Reload scan', disconnect: 'Disconnect',
  connectionSaved: 'Library connection updated', unidentified: 'unidentified entries', discovery: 'Discovery', localProducts: 'Local products',
  union: 'Unique combined items', scanned: 'Last scan', unknownPrice: 'Price unknown',
  exportCatalog: 'Export discovery & favourites', importHint: 'Import catalogue or favourites with an automatic backup. Exports exclude local inventory and file paths.',
});
Object.assign(dictionary.zh, {
  includeMentions: '包含未确认提及', avatarBasis: '已确认关系与原有记录优先；未确认提及需单独启用。',
  confirmedMatch: '已确认', legacyMatch: '原有记录', mentionedAvatars: '仅在商品中提及',
  mentionBasis: '这些模型在商品中出现过，尚未确认适配。', openDataTitle: 'VRCatalogue 开放数据',
  openDataBasis: '补充分类、适配、别名与自动识别的功能信息；具体兼容性以作者页面为准。',
  openDataItems: '件元数据', openDataMatched: '件已匹配', openDataModels: '个模型', openDataSnapshot: '数据快照',
  openDataSource: '数据来源', openDataLicense: '许可与署名',
});
Object.assign(dictionary.en, {
  includeMentions: 'Include unconfirmed mentions', avatarBasis: 'Confirmed matches and legacy records are shown first. Mentions are optional.',
  confirmedMatch: 'Confirmed', legacyMatch: 'Legacy record', mentionedAvatars: 'Mentioned in the listing',
  mentionBasis: 'These avatars were mentioned; compatibility has not been confirmed.', openDataTitle: 'VRCatalogue Open Data',
  openDataBasis: 'Supplementary categories, compatibility, aliases and automatically labelled features. Check the creator’s listing.',
  openDataItems: 'metadata records', openDataMatched: 'matched items', openDataModels: 'avatars', openDataSnapshot: 'Snapshot',
  openDataSource: 'Data source', openDataLicense: 'License & attribution',
});
const filterArrays = ['category', 'avatar', 'author', 'tag', 'excludeTag', 'feature', 'fileType', 'localCategory'];
Object.assign(dictionary.zh, { excluded: '排除', includeTag: '包含标签', excludeTag: '排除标签', tagRules: '包含全部所选标签；排除任一指定标签。', recent: '最近浏览顺序', viewed: '已浏览', removeView: '移除浏览记录', emptyRecent: '还没有浏览记录', emptyRecentHint: '打开商品详情后，可在这里找回它。' });
Object.assign(dictionary.en, { excluded: 'Exclude', includeTag: 'Include tag', excludeTag: 'Exclude tag', tagRules: 'Match all included tags; exclude any selected tag.', recent: 'Recently viewed order', viewed: 'Viewed', removeView: 'Remove from recent views', emptyRecent: 'No recently viewed items', emptyRecentHint: 'Open an item to find it here later.' });
let discoveryUI = null;
Object.assign(dictionary.zh, {
  purchased: '已购', purchaseFilter: '已购记录', purchaseAll: '不限', purchaseRecorded: '已同步已购', purchaseMissingLocal: '已购且本地未收录', purchaseNotRecorded: '未同步已购记录',
  purchaseTitle: '同步 BOOTH 已购清单', purchaseBadge: '已购记录', purchaseEmpty: '尚未同步已购清单', purchaseEmptyHint: '从已登录的 BOOTH 下载库导出商品清单，在数据管理中导入。',
  purchaseBasis: '仅数字下载库，包含免费获取的商品，不含实体订单；不代表实时订单或退款状态。',
  purchaseSteps: '先设置采集书签，再在已登录的 BOOTH 下载库点击书签运行。GUI 中的设置按钮不会直接采集；完成后将导出的 JSON 导入这里。',
  purchaseBookmark: '采集 BOOTH 已购', purchaseOpen: '打开 BOOTH 下载库', purchaseImport: '导入已购 JSON / HTML', purchaseExport: '备份已购记录', purchaseCopy: '复制书签地址',
  purchaseImportHint: '多次导入按商品 ID 合并；只保留商品信息，已有本地文件和分类不受影响。已购记录单独存储，探索目录导出不包含这些记录。',
  bookmarkHint: '请将这个链接拖到普通浏览器的书签栏，再在 BOOTH 下载库页面点击书签。', purchaseCopied: '书签地址已复制。请粘贴到书签的网址栏，再去 BOOTH 下载库点击书签。', purchaseImported: '已购清单已同步',
});
Object.assign(dictionary.en, {
  purchased: 'Bought', purchaseFilter: 'Purchase records', purchaseAll: 'Any', purchaseRecorded: 'Imported purchases', purchaseMissingLocal: 'Bought, absent locally', purchaseNotRecorded: 'No imported record',
  purchaseTitle: 'Sync BOOTH purchase library', purchaseBadge: 'Purchase record', purchaseEmpty: 'No purchase list imported', purchaseEmptyHint: 'Export your signed-in BOOTH library, then import the list here.',
  purchaseBasis: 'Digital download library, including free acquisitions; physical orders are excluded. Order and refund status are not live.',
  purchaseSteps: 'Set up the bookmark, then run it in your signed-in BOOTH library. The setup button does not collect purchases. Import the exported JSON here when collection finishes.',
  purchaseBookmark: 'Collect BOOTH library', purchaseOpen: 'Open BOOTH library', purchaseImport: 'Import purchases JSON / HTML', purchaseExport: 'Back up purchases', purchaseCopy: 'Copy bookmark URL',
  purchaseImportHint: 'Imports merge by item ID, preserving local files and categories. Purchase records are stored separately and excluded from discovery exports.',
  bookmarkHint: 'Drag this link to your browser bookmarks bar, then use it on the BOOTH library page.', purchaseCopied: 'Bookmark URL copied. Paste it into a new bookmark.', purchaseImported: 'Purchase list imported',
});
Object.assign(dictionary.zh, {
  syncTitle: '自动同步', syncHeading: 'BOOTH 公开商品自动同步', syncHint: '按关键词收录 VRChat / 3D 素材，包含最新商品和历史页；更新过期的商品信息。关键词搜索不保证全站覆盖。',
  syncService: '程序运行时才会定时同步。GUI 关闭窗口会停止后台；网页模式需保持服务窗口运行。',
  syncEnabled: '启用定时同步', syncQueries: '搜索关键词（每行一个，最多 5 个）', syncInterval: '同步间隔（分钟）', syncBatch: '每批商品上限', syncRefresh: '信息更新周期（小时）',
  syncSave: '保存设置', syncRun: '立即同步一批', syncStop: '停止本批', syncPause: '暂停自动同步', syncSaved: '同步设置已保存',
  syncOff: '自动同步已关闭', syncWaiting: '等待下一次同步', syncSearch: '正在查询公开商品', syncItems: '正在读取商品', syncSaving: '正在保存本批', syncStopping: '正在停止并保存进度',
  syncNext: '下次同步', syncPending: '待处理', syncLast: '上次完成', syncAdded: '新增', syncUpdated: '更新', syncSkipped: '跳过', syncFailed: '失败', syncNone: '尚未执行',
});
Object.assign(dictionary.en, {
  syncTitle: 'Auto sync', syncHeading: 'Sync public BOOTH listings', syncHint: 'Collect VRChat / 3D listings by keyword from new and historical results, and refresh stale metadata. Keyword search cannot guarantee complete coverage.',
  syncService: 'Scheduled sync runs while the app is open. Closing the GUI stops its server; in web mode keep the server running.',
  syncEnabled: 'Enable scheduled sync', syncQueries: 'Search keywords (one per line, up to 5)', syncInterval: 'Interval (minutes)', syncBatch: 'Items per batch', syncRefresh: 'Refresh metadata after (hours)',
  syncSave: 'Save settings', syncRun: 'Sync one batch now', syncStop: 'Stop this batch', syncPause: 'Pause automatic sync', syncSaved: 'Sync settings saved',
  syncOff: 'Automatic sync off', syncWaiting: 'Waiting for next sync', syncSearch: 'Searching public listings', syncItems: 'Reading listings', syncSaving: 'Saving batch', syncStopping: 'Stopping and saving progress',
  syncNext: 'Next run', syncPending: 'Pending', syncLast: 'Last completed', syncAdded: 'Added', syncUpdated: 'Updated', syncSkipped: 'Skipped', syncFailed: 'Failed', syncNone: 'Not run yet',
});
let syncState = null, syncPollTimer;
let serverPreferences = {}, preferenceTimer, preferenceChanges = {}, preferenceWrites = Promise.resolve();
try { serverPreferences = await fetch('/api/preferences').then(r => r.ok ? r.json() : {}); } catch {}
function readStorage(key, fallback) { try { return serverPreferences[key] ?? JSON.parse(localStorage.getItem('vrc-local-' + key)) ?? fallback; } catch { return fallback; } }
function writeStorage(key, value) {
  serverPreferences[key] = value;
  try { localStorage.setItem('vrc-local-' + key, JSON.stringify(value)); } catch {}
  preferenceChanges[key] = value;
  clearTimeout(preferenceTimer); preferenceTimer = setTimeout(flushPreferences, 150);
}
function flushPreferences() {
  const changes = preferenceChanges; preferenceChanges = {};
  if (!Object.keys(changes).length) return;
  preferenceWrites = preferenceWrites.then(() => fetch('/api/preferences', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(changes), keepalive: true }).then(r => { if (!r.ok) throw new Error(); })).catch(() => toast(lang === 'en' ? 'Could not save settings on this device.' : '界面设置保存失败'));
}
window.addEventListener('pagehide', flushPreferences);
let lang = readStorage('language', 'zh');
if (!dictionary[lang]) lang = 'zh';
let currency = readStorage('currency', 'JPY');
if (!['JPY', 'CNY', 'USD'].includes(currency)) currency = 'JPY';
let theme = readStorage('theme', 'charcoal');
if (!['charcoal', 'cloud'].includes(theme)) theme = 'charcoal';
const favourites = new Set((Array.isArray(readStorage('favourites', [])) ? readStorage('favourites', []) : []).map(Number).filter(n => Number.isSafeInteger(n) && n > 0));
// Import old per-browser settings once; shared desktop settings then survive origin changes.
let importedBrowserPreferences = false;
for (const key of ['language','currency','theme','favourites','compact','notice-dismissed','saved-searches','recent-views']) {
  if (serverPreferences[key] !== undefined) continue;
  try { const value = JSON.parse(localStorage.getItem('vrc-local-' + key)); if (value !== null) { serverPreferences[key] = value; importedBrowserPreferences = true; } } catch {}
}
if (importedBrowserPreferences) fetch('/api/preferences', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(serverPreferences), keepalive: true }).catch(() => {});
const t = key => dictionary[lang][key] ?? key;
let state = stateFromUrl();
let data = null, allFacets = null, status = null, aborter = null, requestNumber = 0;
let detail = null, detailIndex = 0, detailRequest = 0, toastTimer;
const expandedCategories = new Set();
const locale = () => lang === 'zh' ? 'zh-CN' : 'en-US';
const formatNumber = value => Number(value).toLocaleString(locale());
const date = value => value ? new Date(value).toLocaleDateString(locale(), { year: 'numeric', month: '2-digit', day: '2-digit' }) : '—';
function money(value) {
  if (value === null || value === undefined) return t('unknownPrice');
  if (value === 0) return t('free');
  // Explicit reference rates, not a live quotation.
  const rates = { JPY: 1, CNY: 0.048, USD: 0.0067 };
  return new Intl.NumberFormat(locale(), { style: 'currency', currency, currencyDisplay: 'narrowSymbol', maximumFractionDigits: currency === 'JPY' ? 0 : 2 }).format(value * rates[currency]);
}
function bytes(value) {
  const n = Math.max(0, Number(value) || 0);
  const i = n ? Math.min(4, Math.floor(Math.log(n) / Math.log(1024))) : 0;
  return new Intl.NumberFormat(locale(), { maximumFractionDigits: i ? 1 : 0 }).format(n / 1024 ** i) + ' ' + ['B', 'KiB', 'MiB', 'GiB', 'TiB'][i];
}
function itemPrice(item) { return money(item.priceKnown ? item.price : null); }
function localLabel(item) { return t(!item.local?.known ? 'localUnknown' : item.local.copies ? 'localPresent' : 'localMissing'); }
const itemTitle = item => lang === 'en' && item.translations?.en?.title ? item.translations.en.title : item.title;
const itemBio = item => lang === 'en' && item.translations?.en?.bio ? item.translations.en.bio : item.bio;

function hasLocalFileFilters(value = state) {
  return value.localCategory.length > 0 || value.fileType.length > 0 || value.minBytes > 0 || value.duplicates;
}
function effectiveAvailability() {
  return state.view === 'local' || hasLocalFileFilters() ? 'local' : state.availability;
}
function clearLocalFileFilters() {
  state.localCategory = []; state.fileType = []; state.minBytes = 0; state.duplicates = false;
}
function stateFromUrl(query = location.search) {
  const params = new URLSearchParams(query);
  const list = key => params.getAll(key).flatMap(v => v.split(',')).filter(Boolean).slice(0, 50);
  const value = {
    view: ['items', 'avatars', 'favourites', 'local', 'purchased', 'recent'].includes(params.get('view')) ? params.get('view') : 'items',
    q: (params.get('q') || '').slice(0, 200), sort: params.get('sort') === 'recent' ? 'trending' : params.get('sort') || 'trending', page: Math.max(1, Number(params.get('page')) || 1),
    pageSize: [20, 40, 60, 100].includes(Number(params.get('pageSize'))) ? Number(params.get('pageSize')) : 20,
    category: list('category'), avatar: list('avatar'), author: list('author'), tag: list('tag'), excludeTag: list('excludeTag'), feature: list('feature'),
    fileType: list('fileType'), localCategory: list('localCategory'),
    includeMentions: params.get('includeMentions') === '1',
    availability: ['local', 'missing'].includes(params.get('availability')) ? params.get('availability') : 'all',
    minBytes: Math.max(0, Number(params.get('minBytes')) || 0), duplicates: params.get('duplicates') === '1',
    purchase: ['recorded', 'missing-local', 'not-recorded'].includes(params.get('purchase')) ? params.get('purchase') : 'all',
    min: Math.max(0, Number(params.get('min')) || 0), max: params.has('max') ? Math.max(0, Number(params.get('max')) || 0) : null,
    free: params.get('free') === '1', adult: ['safe', 'all', 'suggestive', 'adult'].includes(params.get('adult')) ? params.get('adult') : 'safe',
  };
  value.tag = value.tag.filter(tag => !value.excludeTag.some(excluded => excluded.normalize('NFKC').toLowerCase() === tag.normalize('NFKC').toLowerCase()));
  if ((value.view === 'local' || hasLocalFileFilters(value)) && value.availability === 'missing') value.availability = 'all';
  return value;
}
function paramsForState(includeIds = false) {
  const p = new URLSearchParams();
  if (state.view !== 'items') p.set('view', state.view);
  if (state.q.trim()) p.set('q', state.q.trim());
  if (state.sort !== 'trending') p.set('sort', state.sort);
  if (state.page > 1) p.set('page', state.page);
  if (state.pageSize !== 20) p.set('pageSize', state.pageSize);
  for (const key of filterArrays) for (const value of state[key]) p.append(key, value);
  if (state.availability !== 'all') p.set('availability', state.availability);
  if (state.minBytes) p.set('minBytes', state.minBytes);
  if (state.duplicates) p.set('duplicates', '1');
  if (state.includeMentions) p.set('includeMentions', '1');
  if (state.purchase !== 'all') p.set('purchase', state.purchase);
  if (state.min) p.set('min', state.min);
  if (state.max !== null) p.set('max', state.max);
  if (state.free) p.set('free', '1');
  if (state.adult !== 'safe') p.set('adult', state.adult);
  if (includeIds && state.view === 'favourites') p.set('ids', [...favourites].join(','));
  if (includeIds && state.view === 'recent') p.set('ids', (discoveryUI?.recentIds() || []).join(','));
  return p;
}
function syncUrl(replace = false) {
  const q = paramsForState().toString();
  const url = location.pathname + (q ? '?' + q : '');
  if (url !== location.pathname + location.search) history[replace ? 'replaceState' : 'pushState']({}, '', url);
}
function filterCount() { return filterArrays.reduce((n, k) => n + state[k].length, 0) + Number(state.free) + Number(state.min > 0) + Number(state.max !== null) + Number(!!state.q.trim()) + Number(state.adult !== 'safe') + Number(state.availability !== 'all') + Number(state.minBytes > 0) + Number(state.duplicates) + Number(state.purchase !== 'all') + Number(state.includeMentions); }
function change(key, value, { replace = false, keepPage = false } = {}) {
  if (key === 'availability' && value !== 'local') {
    clearLocalFileFilters();
    if (state.view === 'local') state.view = 'items';
  }
  if (key === 'view' && value === 'items') {
    clearLocalFileFilters(); state.availability = 'all';
  }
  state[key] = value;
  if (hasLocalFileFilters() && state.availability === 'missing') state.availability = 'all';
  if (!keepPage) state.page = 1;
  syncUrl(replace); syncInputs(); fetchItems();
}
function toggleFilter(key, value) {
  if (state[key].includes(value)) state[key] = state[key].filter(v => v !== value);
  else if (state[key].length < 50) {
    state[key].push(value);
    if (key === 'tag' || key === 'excludeTag') {
      const other = key === 'tag' ? 'excludeTag' : 'tag';
      state[other] = state[other].filter(tag => tag.normalize('NFKC').toLowerCase() !== value.normalize('NFKC').toLowerCase());
    }
  }
  if (hasLocalFileFilters() && state.availability === 'missing') state.availability = 'all';
  state.page = 1; syncUrl(); syncInputs(); fetchItems();
}
function resetFilters() {
  const { view, sort, pageSize } = state;
  state = { ...state, view, sort, pageSize, q: '', page: 1, ...Object.fromEntries(filterArrays.map(key => [key, []])), min: 0, max: null, free: false, adult: 'safe', availability: 'all', minBytes: 0, duplicates: false, purchase: 'all', includeMentions: false };
  ['#avatar-search', '#author-search', '#tag-search'].forEach(s => $(s).value = '');
  syncUrl(); syncInputs(); fetchItems();
}
function syncInputs() {
  $('#search').value = state.q;
  $('#sort').value = state.view === 'recent' ? 'recent' : state.sort;
  $('#sort').disabled = state.view === 'recent';
  $('#sort option[value="recent"]').hidden = state.view !== 'recent';
  $('#sort').title = state.sort === 'trending' ? t('trendingHint') : '';
  $('#page-size').value = state.pageSize;
  $('#adult').value = state.adult;
  $('#free').checked = state.free;
  $('#include-mentions').checked = state.includeMentions;
  $('#price-min').value = state.min;
  $('#price-max').value = state.max ?? '';
  $('#price-range').value = state.max ?? 15000;
  $('#availability').value = effectiveAvailability();
  const sizes = $('#min-bytes');
  [...sizes.options].filter(option => option.dataset.custom).forEach(option => option.remove());
  if (![...sizes.options].some(option => Number(option.value) === state.minBytes)) {
    const option = new Option('≥ ' + bytes(state.minBytes), state.minBytes); option.dataset.custom = '1'; sizes.add(option);
  }
  sizes.value = state.minBytes;
  $('#duplicates').checked = state.duplicates;
  $('#purchase-filter').value = state.purchase;
}

function applyLanguage() {
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  $$('[data-i18n]').forEach(el => el.textContent = t(el.dataset.i18n));
  $('#search').placeholder = t('search');
  $('#avatar-search').placeholder = t('avatarSearch'); $('#author-search').placeholder = t('authorSearch'); $('#tag-search').placeholder = t('tagSearch');
  [...$('#sort').options].forEach(option => option.textContent = t(option.value));
  $('#sort').title = state.sort === 'trending' ? t('trendingHint') : '';
  [...$('#page-size').options].forEach(option => option.textContent = option.value + ' ' + t('perPage'));
  [...$('#adult').options].forEach(option => option.textContent = t(option.value));
  [...$('#availability').options].forEach(option => option.textContent = t('availability' + ({ all: 'All', local: 'Local', missing: 'Missing' }[option.value])));
  $('#min-bytes').options[0].textContent = t('anySize');
  [...$('#purchase-filter').options].forEach(option => option.textContent = purchaseFilterLabel(option.value));
  $('#language').value = lang; $('#currency').value = currency; $('#theme').value = theme;
  $('#currency').title = t('currencyHint');
  hydrateIcons();
  discoveryUI?.refresh();
}
function toast(message) {
  clearTimeout(toastTimer);
  const element = $('#toast') || Object.assign(document.createElement('div'), { id: 'toast', className: 'toast' });
  element.setAttribute('popover', 'manual'); element.setAttribute('role', 'status'); element.setAttribute('aria-live', 'polite'); element.textContent = message;
  if (element.matches(':popover-open')) element.hidePopover();
  // A body sibling of a modal remains inert, even when promoted to the top layer.
  ($$('dialog[open]').at(-1) || document.body).append(element);
  if (element.showPopover) element.showPopover();
  element.classList.add('visible');
  toastTimer = setTimeout(() => { element.classList.remove('visible'); if (element.matches(':popover-open')) element.hidePopover(); document.body.append(element); }, 5000);
}
async function api(url, options = {}) {
  const response = await fetch(url, options);
  let body;
  try { body = await response.json(); } catch { throw new Error(t('error')); }
  if (!response.ok) throw new Error(body.error || t('error'));
  return body;
}
function skeleton() { return Array.from({ length: 9 }, () => '<article class="product-card skeleton"><div class="skeleton-image"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div><div class="skeleton-foot"></div></article>').join(''); }
async function fetchItems() {
  const request = ++requestNumber;
  aborter?.abort(); aborter = new AbortController();
  $('#grid').setAttribute('aria-busy', 'true');
  if (!data) $('#grid').innerHTML = skeleton();
  try {
    const response = await api('/api/items?' + paramsForState(true), { signal: aborter.signal, priority: 'high' });
    if (request !== requestNumber) return;
    data = response;
    if (!allFacets) allFacets = data.facets;
    state.page = data.page; syncUrl(true);
    render();
  } catch (error) {
    if (error.name === 'AbortError') return;
    $('#grid').innerHTML = `<div class="empty-state">${icon('database')}<h2>${t('loadError')}</h2><p>${escape(error.message)}</p><button class="btn primary" data-action="retry">${t('retry')}</button></div>`;
    $('#result-count').textContent = '—';
  } finally { if (request === requestNumber) $('#grid').setAttribute('aria-busy', 'false'); }
}

function renderTabs() {
  $('#sidebar-tabs').innerHTML = [['items', 'hanger', 'items'], ['local', 'database', 'localView'], ['purchased', 'check', 'purchased'], ['avatars', 'avatar', 'models'], ['favourites', 'heart', 'favourites']].map(([view, symbol, label]) => `<button type="button" class="view-tab ${state.view === view ? 'active' : ''}" data-action="view" data-view="${view}" aria-pressed="${state.view === view}">${icon(symbol)}${t(label)}${view === 'favourites' && favourites.size ? `<span class="tab-count">${favourites.size}</span>` : ''}</button>`).join('');
}
function purchaseFilterLabel(value) { return t(({ all: 'purchaseAll', recorded: 'purchaseRecorded', 'missing-local': 'purchaseMissingLocal', 'not-recorded': 'purchaseNotRecorded' })[value] || 'purchaseAll'); }
function checked(key, value) { return state[key].includes(value) ? ' checked' : ''; }
function categoryLabel(category) { return lang === 'zh' ? category.label : category.en; }
function renderSidebar() {
  renderTabs();
  const count = filterCount();
  $('#filter-summary').innerHTML = count ? `<span><strong>${count}</strong> ${t('filtersApplied')}</span><button class="text-button accent" data-action="reset">${t('reset')}</button>` : `<span>${t('noFilters')}</span>`;
  $('#mobile-filter-count').textContent = count || '';
  for (const [key, facet, selector] of [['localCategory', 'localCategories', '#local-categories'], ['fileType', 'fileTypes', '#file-types']]) {
    const options = new Map((data.facets[facet] || []).map(option => [option.name, option]));
    for (const name of state[key]) if (!options.has(name)) options.set(name, { name, count: 0 });
    $(selector).innerHTML = [...options.values()].map(option => `<label class="check-label"><input type="checkbox" data-filter="${key}" value="${escape(option.name)}"${checked(key, option.name)}><span>${escape(option.name === 'folder' ? t('folder') : option.name)}</span><span class="option-count">${formatNumber(option.count)}</span></label>`).join('') || `<p class="no-options">${t(data.library?.connected ? 'noOptions' : 'disconnected')}</p>`;
  }
  const childrenSelected = slug => state.category.some(value => value.startsWith(slug + '--'));
  $('#categories').innerHTML = data.facets.categories.filter(cat => state.view !== 'avatars' || cat.mode === 'avatars').map(cat => {
    const expanded = expandedCategories.has(cat.slug) || childrenSelected(cat.slug);
    return `<div class="category-group ${expanded ? 'expanded' : ''}"><div class="category-row"><button class="category-expand" type="button" data-action="expand-category" data-value="${escape(cat.slug)}" aria-label="${escape(categoryLabel(cat))}" aria-expanded="${expanded}">${icon('chevron')}</button><label class="check-label"><input type="checkbox" data-filter="category" value="${escape(cat.slug)}"${checked('category', cat.slug)}><span>${escape(categoryLabel(cat))}</span><span class="option-count">${formatNumber(cat.count)}</span></label></div><div class="category-children" ${expanded ? '' : 'hidden'}>${cat.children.filter(child => child.count || state.category.includes(child.slug)).map(child => `<label class="check-label"><input type="checkbox" data-filter="category" value="${escape(child.slug)}"${checked('category', child.slug)}><span>${escape(subcategoryLabel(child, lang))}</span><span class="option-count">${child.count}</span></label>`).join('') || `<p class="no-options">${t('noOptions')}</p>`}</div></div>`;
  }).join('');
  $('#features').innerHTML = data.facets.features.map(feature => `<label class="check-label"><input type="checkbox" data-filter="feature" value="${feature.key}"${checked('feature', feature.key)}><span>${escape(feature.name)}</span><span class="option-count">${formatNumber(feature.count)}</span></label>`).join('');
  $('#avatar-selected').textContent = state.avatar.length ? ` (${state.avatar.length})` : '';
  renderOptions('avatar'); renderOptions('author'); renderOptions('tag');
}
function renderOptions(key) {
  if (!data) return;
  const plural = { avatar: 'avatars', author: 'authors', tag: 'tags' }[key];
  const identifier = value => key === 'avatar' ? value.slug : value.name;
  const current = new Map(data.facets[plural].map(value => [identifier(value), value]));
  const all = new Map([...(allFacets?.[plural] || []), ...data.facets[plural]].map(value => [identifier(value), value]));
  const query = $('#' + key + '-search').value.normalize('NFKC').toLowerCase().trim();
  if (key === 'tag') for (const name of [...state.tag, ...state.excludeTag]) if (!all.has(name)) all.set(name, { name, count: 0 });
  const selected = value => state[key].includes(value) || (key === 'tag' && state.excludeTag.includes(value));
  const options = [...all.values()].filter(value => key === 'avatar' ? query || current.get(identifier(value))?.count > 0 || selected(identifier(value)) : current.has(identifier(value)) || selected(identifier(value)))
    .filter(value => [value.name, value.en, value.ja, value.ko, value.slug, ...(value.aliases || [])].some(v => v?.normalize('NFKC').toLowerCase().includes(query)))
    .sort((a, b) => Number(selected(identifier(b))) - Number(selected(identifier(a))) || (current.get(identifier(b))?.count || 0) - (current.get(identifier(a))?.count || 0)).slice(0, key === 'tag' ? 40 : 80);
  const list = $('#' + key + '-list');
  list.innerHTML = options.length ? options.map(option => {
    const value = identifier(option), count = current.get(value)?.count || 0;
    if (key === 'tag') return `<div class="tag-filter-option ${state.excludeTag.includes(value) ? 'excluded' : ''}"><button type="button" class="filter-tag ${state.tag.includes(value) ? 'selected' : ''}" data-action="tag" data-value="${escape(value)}" aria-label="${t('includeTag')} ${escape(value)}" aria-pressed="${state.tag.includes(value)}">${escape(value)}<span>${count}</span></button><button type="button" class="exclude-tag" data-action="exclude-tag" data-value="${escape(value)}" title="${t('excludeTag')} ${escape(value)}" aria-label="${t('excludeTag')} ${escape(value)}" aria-pressed="${state.excludeTag.includes(value)}">−</button></div>`;
    return `<label class="check-label option-row"><input type="checkbox" data-filter="${key}" value="${escape(value)}"${checked(key, value)}>${option.image ? `<img loading="lazy" src="${escape(option.image)}" alt="" width="25" height="25">` : '<span class="avatar-placeholder">' + icon(key === 'avatar' ? 'avatar' : 'box') + '</span>'}<span class="option-text">${escape(key === 'avatar' ? option.en : option.name)}${key === 'avatar' && option.ja && option.ja !== option.en ? `<small>${escape(option.ja)}</small>` : ''}</span><span class="option-count">${count}</span></label>`;
  }).join('') : `<p class="no-options">${t('noOptions')}</p>`;
}
function labelFor(key, value) {
  if (key === 'excludeTag') return `${t('excluded')}: ${value}`;
  if (key === 'localCategory') return `${t('localCategory')}: ${value}`;
  if (key === 'fileType') return `${t('entryType')}: ${value === 'folder' ? t('folder') : value}`;
  if (key === 'category') {
    for (const cat of data.facets.categories) {
      if (cat.slug === value) return categoryLabel(cat);
      const child = cat.children.find(child => child.slug === value); if (child) return subcategoryLabel(child, lang);
    }
  }
  if (key === 'avatar') return [...data.facets.avatars, ...allFacets.avatars].find(a => a.slug === value)?.en || value;
  if (key === 'feature') return data.facets.features.find(f => f.key === value)?.name || value;
  return value;
}
function renderActiveFilters() {
  const chips = [];
  if (state.q) chips.push(`<button class="filter-chip" data-action="remove-q">${icon('search')}${escape(state.q)}${icon('x')}</button>`);
  for (const key of filterArrays) for (const value of state[key]) chips.push(`<button class="filter-chip ${key === 'excludeTag' ? 'excluded' : ''}" data-action="remove-filter" data-key="${key}" data-value="${escape(value)}">${escape(labelFor(key, value))}${icon('x')}</button>`);
  if (state.availability !== 'all') chips.push(`<button class="filter-chip" data-action="remove-local" data-key="availability">${t(state.availability === 'local' ? 'localPresent' : 'localMissing')}${icon('x')}</button>`);
  if (state.minBytes) chips.push(`<button class="filter-chip" data-action="remove-local" data-key="minBytes">≥ ${bytes(state.minBytes)}${icon('x')}</button>`);
  if (state.duplicates) chips.push(`<button class="filter-chip" data-action="remove-local" data-key="duplicates">${t('duplicates')}${icon('x')}</button>`);
  if (state.purchase !== 'all') chips.push(`<button class="filter-chip" data-action="remove-purchase">${purchaseFilterLabel(state.purchase)}${icon('x')}</button>`);
  if (state.free) chips.push(`<button class="filter-chip" data-action="remove-free">${t('freeOnly')}${icon('x')}</button>`);
  if (state.includeMentions) chips.push(`<button class="filter-chip" data-action="remove-mentions">${t('includeMentions')}${icon('x')}</button>`);
  if (state.min || state.max !== null) chips.push(`<button class="filter-chip" data-action="remove-price">¥${state.min} – ${state.max === null ? '∞' : '¥' + state.max}${icon('x')}</button>`);
  $('#active-filters').innerHTML = chips.join('');
}
function renderPagination() {
  const current = data.page, total = data.totalPages;
  const pages = [...new Set([1, current - 1, current, current + 1, total].filter(n => n >= 1 && n <= total))].sort((a, b) => a - b);
  let last = 0;
  const links = pages.map(page => { const gap = last && page - last > 1 ? '<span class="page-ellipsis">…</span>' : ''; last = page; return gap + `<button type="button" class="page-number ${current === page ? 'active' : ''}" data-action="page" data-page="${page}" ${current === page ? 'aria-current="page"' : ''}>${page}</button>`; }).join('');
  const html = `<button type="button" class="page-arrow prev" data-action="page" data-page="${current - 1}" aria-label="${lang === 'zh' ? '上一页' : 'Previous page'}" ${current === 1 ? 'disabled' : ''}>${icon('chevron')}</button>${links}<button type="button" class="page-arrow" data-action="page" data-page="${current + 1}" aria-label="${lang === 'zh' ? '下一页' : 'Next page'}" ${current === total ? 'disabled' : ''}>${icon('chevron')}</button>`;
  $$('.pagination').forEach(el => el.innerHTML = html);
}
function categoryFor(item) { const category = data.facets.categories.find(cat => cat.slug === item.categorySlugs[0]); return category ? categoryLabel(category) : item.category || (lang === 'zh' ? '未分类' : 'Unclassified'); }
function renderCard(item) {
  const saved = favourites.has(item.id), title = itemTitle(item), bio = itemBio(item);
  return `<article class="product-card" data-item-id="${item.id}">
    <div class="card-media"><button type="button" class="card-image-button" data-action="detail" data-id="${item.id}" aria-label="${escape(title)}"><img data-image-candidates="${escape(JSON.stringify(item.media.slice(1)))}" src="${escape(item.media[0] || '/placeholder.svg')}" alt="${escape(title)}" loading="lazy" decoding="async" width="400" height="400"></button>${item.purchase?.recorded ? `<span class="purchase-badge" title="${t('purchaseBasis')}">${icon('check')}${t('purchased')}</span>` : ''}<span class="price-badge ${item.priceKnown && item.price === 0 ? 'is-free' : ''}" title="${item.priceKnown ? 'JPY ' + formatNumber(item.price) : t('unknownPrice')}">${escape(itemPrice(item))}</span><button type="button" class="card-save ${saved ? 'saved' : ''}" data-action="favourite" data-id="${item.id}" aria-pressed="${saved}" aria-label="${t(saved ? 'savedLabel' : 'save')} ${escape(title)}">${icon('heart')}</button>${item.media.length > 1 ? `<span class="image-count">${icon('layers')}${item.media.length}</span>` : ''}</div>
    <div class="card-body"><button type="button" class="card-title" data-action="detail" data-id="${item.id}" title="${escape(title)}">${escape(title)}</button><div class="card-meta"><button type="button" data-action="card-category" data-value="${escape(item.categorySlugs[0] || '')}" ${item.categorySlugs.length ? '' : 'disabled'}>${escape(categoryFor(item))}</button><span>·</span><time datetime="${escape(item.publishedAt || '')}">${date(item.publishedAt)}</time></div><p class="card-bio">${escape(bio.slice(0, 600) || '—')}</p></div>
    <button type="button" class="card-local ${item.local?.known && item.local.copies ? 'present' : ''}" data-action="detail" data-id="${item.id}" title="${t('scanBasis')}">${icon(item.local?.copies ? 'check' : 'database')}<span>${localLabel(item)}</span>${item.local?.copies ? `<small>${item.local.copies} · ${bytes(item.local.bytes)}</small>` : ''}</button>
    <details class="card-details"><summary><span>${t('metadata')}</span><span class="metadata-badges"><span>${item.tags.length} ${t('tagUnit')}</span><span>${item.variations.length} ${t('variations')}</span></span>${icon('chevron')}</summary><div class="card-details-body"><p>${escape(bio.slice(0, 600))}</p><div class="tag-cloud">${item.tags.slice(0, 20).map(tag => `<button data-action="tag" data-value="${escape(tag)}">${escape(tag)}</button>`).join('')}</div><button class="text-button accent" data-action="detail" data-id="${item.id}">${t('description')} ${icon('arrow')}</button></div></details>
    <div class="card-footer"><a class="card-author" href="${escape(item.authorUrl || item.url)}" target="_blank" rel="noopener noreferrer">${item.authorIcon ? `<img src="${escape(item.authorIcon)}" alt="" loading="lazy" width="17" height="17">` : icon('avatar')}<span>${escape(item.author)}</span></a><span class="card-likes" title="BOOTH likes">${icon('heart')}${formatNumber(item.likes)}</span><button class="avatar-count" data-action="detail" data-id="${item.id}" title="${t('supportedAvatars')}">${icon('avatar')}${item.avatars.length}</button></div>
    ${discoveryUI?.hasViewed(item.id) ? `<div class="recent-card-actions"><span>${icon('history')} ${t('viewed')}</span>${state.view === 'recent' ? `<button type="button" class="text-button" data-discovery="remove-view" data-id="${item.id}">${t('removeView')}</button>` : ''}</div>` : ''}
  </article>`;
}
function renderGrid() {
  if (data.items.length) $('#grid').innerHTML = data.items.map(renderCard).join('');
  else {
    if (state.view === 'recent' && !discoveryUI?.recentIds().length) {
      $('#grid').innerHTML = `<div class="empty-state">${icon('history')}<h2>${t('emptyRecent')}</h2><p>${t('emptyRecentHint')}</p><button class="btn primary" data-action="view" data-view="items">${t('explore')}</button></div>`; return;
    }
    if (state.view === 'purchased' && !data.purchases?.products) {
      $('#grid').innerHTML = `<div class="empty-state">${icon('check')}<h2>${t('purchaseEmpty')}</h2><p>${t('purchaseEmptyHint')}</p><button class="btn primary" data-action="purchase-settings">${t('purchaseTitle')}</button></div>`; return;
    }
    const emptyFav = state.view === 'favourites' && !favourites.size;
    $('#grid').innerHTML = `<div class="empty-state">${icon(emptyFav ? 'heart' : 'search')}<h2>${t(emptyFav ? 'emptyFavourites' : 'noResults')}</h2><p>${t(emptyFav ? 'emptyFavouritesHint' : 'noResultsHint')}</p><button class="btn primary" data-action="${emptyFav ? 'view' : 'reset'}" data-view="items">${t(emptyFav ? 'explore' : 'reset')}</button></div>`;
  }
}
function render() {
  renderSidebar(); renderGrid(); renderPagination(); renderActiveFilters();
  discoveryUI?.refresh();
  $('#result-count').innerHTML = `<span class="speed">${icon('flame')}${data.elapsedMs}ms</span><strong>${formatNumber(data.count)}</strong><span>${t('results')}</span>`;
  const library = data.library;
  $('#catalog-status').textContent = `${t('discovery')} ${formatNumber(data.discoveryRecords)} · ${t('localProducts')} ${library?.connected ? formatNumber(library.products) : '—'} · ${t('union')} ${formatNumber(data.totalRecords)}`;
  $('#catalog-status').textContent += ` · ${t('purchased')} ${formatNumber(data.purchases?.products || 0)}`;
  $('#local-overview').innerHTML = library?.connected
    ? `<span class="overview-icon">${icon('database')}</span><div><strong>${t('localView')} <b>${formatNumber(library.products)}</b></strong><p>${formatNumber(library.entries)} ${t('entries')} · ${bytes(library.bytes)} · ${t('scanned')} ${date(library.generatedAt)}${library.unidentified ? ` · ${formatNumber(library.unidentified)} ${t('unidentified')}` : ''}</p></div><button class="btn tools-overview-button" data-tools-open>${icon('database')}${lang === 'zh' ? '本地管理' : 'Local management'}</button><button class="btn ${state.view === 'local' ? 'selected' : ''}" data-action="view" data-view="${state.view === 'local' ? 'items' : 'local'}">${t(state.view === 'local' ? 'explore' : 'localView')}${icon('arrow')}</button>`
    : `<span class="overview-icon">${icon('database')}</span><div><strong>${t('disconnected')}</strong><p>${escape(library?.error || t('connectionHint'))}</p></div><button class="btn" data-action="data">${t('connectLibrary')}</button>`;
}

function toggleFavourite(id) {
  if (favourites.has(id)) { favourites.delete(id); toast(t('unsaved')); } else { favourites.add(id); toast(t('saved')); }
  writeStorage('favourites', [...favourites]); renderTabs();
  if (state.view === 'favourites') fetchItems();
  else $$(`[data-action="favourite"][data-id="${id}"]`).forEach(button => { const saved = favourites.has(id); button.classList.toggle('saved', saved); button.setAttribute('aria-pressed', saved); button.setAttribute('aria-label', t(saved ? 'savedLabel' : 'save')); });
  if ($('#detail-dialog').open && detail?.id === id) renderDetail();
}
async function openDetail(id) {
  const request = ++detailRequest;
  try {
    const item = data?.items.find(item => item.id === id) || await api('/api/items/' + id);
    if (request !== detailRequest) return;
    detail = item; detailIndex = 0;
    renderDetail(); $('#detail-dialog').showModal();
    discoveryUI?.recordView(id);
  } catch (error) { toast(error.message); }
}
function renderLocalDetail(item) {
  const local = item.local;
  return `<section class="detail-section local-detail"><h2>${icon('database')}${localLabel(item)}${local?.copies ? `<span>${local.copies} ${t('entries')} · ${bytes(local.bytes)}</span>` : ''}</h2><p class="feature-note">${t('scanBasis')}</p>${local?.copies ? `<ul class="local-entries">${local.entries.map((entry, index) => `<li><div><code>${escape(entry.folder)}</code><small>${escape(entry.type === 'folder' ? t('folder') : entry.type)} · ${bytes(entry.bytes)} · ${date(entry.mtime ? entry.mtime * 1000 : '')}</small></div><button class="btn" data-action="reveal-local" data-index="${index}">${t('reveal')}${icon('external')}</button></li>`).join('')}</ul>` : ''}</section>`;
}
function renderAvatarDetails(item) {
  const chip = (avatar, mention = false) => `<button type="button" data-action="${mention ? 'detail-avatar-mention' : 'detail-avatar'}" data-value="${escape(avatar.slug)}">${avatar.image ? `<img src="${escape(avatar.image)}" alt="" width="22" height="22" loading="lazy">` : ''}${escape(avatar.en || avatar.ja)}${mention ? '' : `<span class="compatibility-state ${avatar.verified === true ? 'confirmed' : ''}">${t(avatar.verified === true ? 'confirmedMatch' : 'legacyMatch')}</span>`}</button>`;
  return `<div class="detail-section"><h2>${t('supportedAvatars')}<span>${item.avatars.length}</span></h2><div class="avatar-chips">${item.avatars.map(avatar => chip(avatar)).join('') || `<p class="muted">${lang === 'zh' ? '未收录明确的模型适配信息' : 'No explicit avatar metadata indexed'}</p>`}</div>${item.avatarMentions?.length ? `<details class="avatar-mentions"><summary>${t('mentionedAvatars')} (${item.avatarMentions.length})</summary><p class="feature-note">${t('mentionBasis')}</p><div class="avatar-chips">${item.avatarMentions.map(avatar => chip(avatar, true)).join('')}</div></details>` : ''}${item.openData ? `<p class="feature-note metadata-source">${t('openDataTitle')} · ${t('openDataSnapshot')} ${date(item.openData.snapshotAt)}<br>${t('openDataBasis')}</p>` : ''}</div>`;
}
function renderOpenDataSection() {
  const metadata = status?.openData;
  if (!metadata?.enabled) return metadata?.error ? `<p class="form-feedback error">${escape(metadata.error)}</p>` : '';
  return `<section class="data-section open-data-section"><h2>${t('openDataTitle')}</h2><p>${t('openDataBasis')}</p><p class="open-data-counts">${formatNumber(metadata.items)} ${t('openDataItems')} · ${formatNumber(metadata.matchedItems)} ${t('openDataMatched')} · ${metadata.avatars} ${t('openDataModels')}</p><p class="feature-note">${t('openDataSnapshot')}: ${date(metadata.snapshotAt)} · CC BY 4.0 · VRCatalogue</p><div class="data-actions"><a class="btn" href="https://huggingface.co/datasets/vrcatalogue/vrcatalogue-open-data" target="_blank" rel="noopener noreferrer">${t('openDataSource')}${icon('external')}</a><a class="btn" href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer">${t('openDataLicense')}${icon('external')}</a></div></section>`;
}
function renderDetail() {
  if (!detail) return;
  const item = detail, saved = favourites.has(item.id), count = Math.max(1, item.media.length);
  $('#detail-dialog').innerHTML = `<button type="button" class="dialog-close icon-btn" data-action="close-dialog" aria-label="${t('close')}">${icon('x')}</button><div class="detail-layout"><div class="detail-gallery"><div class="detail-image"><img data-image-candidates="${escape(JSON.stringify(item.media.filter((_,index)=>index!==detailIndex)))}" src="${escape(item.media[detailIndex] || '/placeholder.svg')}" alt="${escape(itemTitle(item))}" width="700" height="700">${count > 1 ? `<button type="button" class="gallery-arrow prev" data-action="gallery-prev" aria-label="Previous image">${icon('chevron')}</button><button type="button" class="gallery-arrow" data-action="gallery-next" aria-label="Next image">${icon('chevron')}</button><span class="gallery-counter">${detailIndex + 1} / ${count}</span>` : ''}</div><div class="gallery-thumbs">${item.media.slice(0, 30).map((src, index) => `<button type="button" class="${detailIndex === index ? 'active' : ''}" data-action="gallery-index" data-index="${index}" aria-label="Image ${index + 1}" aria-pressed="${detailIndex === index}"><img src="${escape(src)}" alt="" loading="lazy" width="56" height="56"></button>`).join('')}</div></div><div class="detail-info"><span class="detail-category">${escape(categoryFor(item))}</span><h1>${escape(itemTitle(item))}</h1><a class="detail-author" href="${escape(item.authorUrl || item.url)}" target="_blank" rel="noopener noreferrer">${item.authorIcon ? `<img src="${escape(item.authorIcon)}" alt="" width="28" height="28">` : ''}${escape(item.author)}${icon('external')}</a><div class="detail-price">${escape(itemPrice(item))}<span>${item.variations.length > 1 ? t('from') : ''}</span></div>${currency !== 'JPY' && item.priceKnown ? `<p class="currency-note">${t('approximate')} · JPY ¥${formatNumber(item.price)}</p>` : ''}<div class="detail-actions"><a class="btn primary" href="${escape(item.url)}" target="_blank" rel="noopener noreferrer">${t('buy')}${icon('external')}</a><button type="button" class="btn favourite-button ${saved ? 'saved' : ''}" data-action="favourite" data-id="${item.id}" aria-pressed="${saved}">${icon('heart')}${t(saved ? 'savedLabel' : 'save')}</button></div>${item.purchase?.recorded ? `<section class="detail-section purchase-detail"><h2>${icon('check')}${t('purchaseBadge')}</h2><p class="feature-note">${t('purchaseBasis')} · ${date(item.purchase.importedAt)}</p></section>` : ''}${renderLocalDetail(item)}${renderAvatarDetails(item)}<div class="detail-section"><h2>${t('variants')}</h2><div class="variant-list">${item.variations.map(variant => `<div><span>${escape(variant.name)}</span><strong>${escape(money(variant.price))}</strong></div>`).join('') || '<p class="muted">—</p>'}</div></div><div class="detail-section"><h2>${t('description')}</h2><p class="detail-description">${escape(itemBio(item))}</p></div><div class="detail-section"><h2>${t('tags')}</h2><div class="tag-cloud">${item.tags.map(tag => `<button data-action="detail-tag" data-value="${escape(tag)}">${escape(tag)}</button>`).join('')}</div></div><div class="detail-bottom"><span>${t('published')} ${date(item.publishedAt)} · #${item.id}</span><button type="button" class="text-button" data-action="refresh-item" data-id="${item.id}">${icon('refresh')}${t('refresh')}</button></div></div></div>`;
}
function openData() {
  $('#data-dialog').innerHTML = `<div class="dialog-heading"><div class="dialog-heading-icon">${icon('database')}</div><div><h1>${t('dataTitle')}</h1><p>${t('dataSubtitle')}</p></div><button class="icon-btn" data-action="close-dialog" aria-label="${t('close')}">${icon('x')}</button></div><div class="library-stats"><div><strong>${formatNumber(status?.items ?? data?.totalRecords ?? 0)}</strong><span>${t('count')}</span></div><div><strong>${favourites.size}</strong><span>${t('favourites')}</span></div><div><strong>${date(status?.capturedAt)}</strong><span>${t('snapshot')}</span></div></div><section class="data-section"><h2>${icon('plus')}${t('addTitle')}</h2><p>${t('addHint')}</p><form id="booth-form"><label class="sr-only" for="booth-url">BOOTH URL / ID</label><input id="booth-url" type="text" required placeholder="https://booth.pm/ja/items/…" autocomplete="off"><button class="btn primary" type="submit">${t('add')}</button></form><p id="booth-feedback" class="form-feedback" role="status"></p></section>${renderOpenDataSection()}<section class="data-section"><h2>${icon('download')}${t('backupTitle')}</h2><p>${t('importHint')}</p><div class="data-actions"><button class="btn" data-action="export-catalog">${icon('download')}${t('exportCatalog')}</button><button class="btn" data-action="export-favourites">${icon('heart')}${t('exportFavourites')}</button><label class="btn import-label" tabindex="0">${icon('upload')}${t('import')}<input id="import-file" type="file" accept=".json,application/json" aria-label="${t('chooseFile')}"></label></div><p id="import-feedback" class="form-feedback" role="status"></p></section><p class="data-note">${icon('info')}${t('dataNote')}</p>`;
  const connectionSection = document.createElement('section');
  connectionSection.className = 'data-section connection-section';
  connectionSection.id = 'connection-section';
  $('#data-dialog .library-stats').after(connectionSection);
  renderConnection();
  const purchaseSection = document.createElement('section'); purchaseSection.className = 'data-section purchase-section'; purchaseSection.id = 'purchase-section';
  $('#data-dialog .library-stats').after(purchaseSection); renderPurchaseSection();
  const syncSection = document.createElement('section'); syncSection.className = 'data-section sync-section'; syncSection.id = 'sync-section';
  $('#data-dialog .library-stats').after(syncSection); renderSyncSection(); scheduleSyncPoll(100);
  const onlineSection = document.createElement('section');
  onlineSection.className = 'data-section';
  onlineSection.innerHTML = `<h2>${icon('search')}${t('onlineSearch')}</h2><p>${t('onlineHint')}</p><form id="online-form"><label class="sr-only" for="online-query">BOOTH search</label><input id="online-query" type="search" required minlength="2" maxlength="100" placeholder="${t('onlinePlaceholder')}" value="${escape(state.q)}"><button class="btn primary" type="submit">${icon('search')}${lang === 'zh' ? '搜索并收录' : 'Search & collect'}</button></form><p id="online-feedback" class="form-feedback" role="status"></p>`;
  $('#booth-form').closest('.data-section').after(onlineSection);
  $('#data-dialog').showModal();
}
const timestamp = value => value ? new Date(value).toLocaleString(locale(), { timeZone: 'Asia/Shanghai', hour12: false }) : '—';
function renderSyncSection() {
  const section = $('#sync-section'); if (!section) return;
  const s = syncState || status?.sync;
  if (!s) return;
  const config = s.config;
  section.innerHTML = `<h2>${icon('refresh')}${t('syncHeading')}</h2><p>${t('syncHint')}</p><div id="sync-state" class="sync-state" role="status" aria-live="polite"></div><form id="sync-form"><label class="check-label"><input id="sync-enabled" type="checkbox" ${config.enabled ? 'checked' : ''}><span>${t('syncEnabled')}</span></label><label class="sync-query-label" for="sync-queries">${t('syncQueries')}</label><textarea id="sync-queries" rows="2" maxlength="504" required>${escape(config.queries.join('\n'))}</textarea><div class="sync-number-grid"><label>${t('syncInterval')}<input id="sync-interval" type="number" min="15" max="1440" required value="${config.intervalMinutes}"></label><label>${t('syncBatch')}<input id="sync-batch" type="number" min="1" max="60" required value="${config.batchSize}"></label><label>${t('syncRefresh')}<input id="sync-refresh" type="number" min="1" max="720" required value="${config.refreshHours}"></label></div><button class="btn" type="submit">${t('syncSave')}</button></form><div class="data-actions"><button class="btn primary" data-action="sync-run">${icon('refresh')}${t('syncRun')}</button><button class="btn" data-action="sync-stop">${t('syncStop')}</button><button class="btn" data-action="sync-pause">${t('syncPause')}</button></div><p class="purchase-import-note">${t('syncService')}</p><p id="sync-feedback" class="form-feedback" role="status"></p>`;
  updateSyncState(s);
}
function updateSyncState(s) {
  syncState = s;
  const dot = $('#sync-dot'); dot.classList.toggle('enabled', s.config.enabled); dot.classList.toggle('running', s.running); dot.classList.toggle('blocked', !!(s.pausedReason || s.error));
  $('.sync-button').title = s.pausedReason || s.error || (s.running ? t('syncItems') : s.config.enabled ? `${t('syncNext')} ${timestamp(s.nextRunAt)}` : t('syncOff'));
  const el = $('#sync-state'); if (!el) return;
  const label = s.stopping ? t('syncStopping') : s.running ? t(({ search: 'syncSearch', items: 'syncItems', saving: 'syncSaving' })[s.phase] || 'syncItems') : s.config.enabled ? t('syncWaiting') : t('syncOff');
  const last = s.lastResult;
  el.innerHTML = `<strong>${escape(s.error || s.pausedReason || label)}</strong>${s.running ? `<span>${s.progress.processed} / ${s.progress.total || '…'}${s.progress.id ? ' · #' + s.progress.id : ''}</span>` : ''}<p>${t('syncPending')} ${s.pending} · ${t('syncNext')} ${timestamp(s.nextRunAt)}</p><p>${last ? `${t('syncLast')} ${timestamp(last.finishedAt)}<br>${t('syncAdded')} ${last.added} · ${t('syncUpdated')} ${last.updated} · ${t('syncSkipped')} ${last.skipped} · ${t('syncFailed')} ${last.failed}` : t('syncNone')}</p>${last?.errors?.length ? `<p class="sync-errors">${last.errors.map(error => escape(error.message)).join('<br>')}</p>` : ''}`;
  $$('#sync-form input, #sync-form textarea, #sync-form button').forEach(input => input.disabled = s.running || !!s.error);
  $('[data-action="sync-run"]').disabled = s.running || !!s.error;
  $('[data-action="sync-stop"]').disabled = !s.running || s.stopping;
  $('[data-action="sync-pause"]').disabled = !s.config.enabled || !!s.error;
}
function scheduleSyncPoll(ms = 15000) { clearTimeout(syncPollTimer); syncPollTimer = setTimeout(pollSync, ms); }
async function pollSync() {
  if (!$('#data-dialog').open && !syncState?.config.enabled && !syncState?.running) return;
  try {
    const previousFinish = syncState?.lastResult?.finishedAt, s = await api('/api/sync/status'); updateSyncState(s);
    if (s.lastResult?.finishedAt && s.lastResult.finishedAt !== previousFinish) { allFacets = null; await refreshStatus(); await fetchItems(); }
  } catch {}
  scheduleSyncPoll(syncState?.running ? 1500 : 15000);
}
let bookmarkPromise;
async function purchaseBookmarkUrl() {
  if (!bookmarkPromise) bookmarkPromise = fetch('/purchase-reader.js').then(async response => {
    if (!response.ok) throw new Error(t('error'));
    const source = (await response.text()).replace(/^export /gm, '');
    return 'javascript:' + encodeURIComponent('void(async()=>{' + source + '\nawait (' + runBoothPurchaseExport.toString() + ')();})()');
  }).catch(error => { bookmarkPromise = null; throw error; });
  return bookmarkPromise;
}
async function runBoothPurchaseExport() {
  const previous = document.getElementById('vrc-purchase-export-status');
  if (previous?.dataset.collectionState === 'running') { if (!previous.open) previous.showModal(); previous.focus(); return; }
  if (previous) { previous.querySelector('button')?.click(); previous.remove(); }
  const dialog = document.createElement('dialog'); dialog.id = 'vrc-purchase-export-status'; dialog.setAttribute('aria-label', 'BOOTH 已购清单采集');
  dialog.dataset.collectionState = 'running';
  dialog.style.cssText = 'box-sizing:border-box;width:560px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);overflow:auto;padding:24px;border:2px solid #ed8589;border-radius:12px;background:#212125;color:#e0dfe5;box-shadow:0 20px 80px #0009;font:15px/1.8 system-ui,sans-serif';
  const heading = document.createElement('h2'); heading.textContent = 'BOOTH 已购清单采集';
  const message = document.createElement('p'), close = document.createElement('button'), controller = new AbortController(), progress = document.createElement('progress'), link = document.createElement('a');
  let downloadUrl;
  message.setAttribute('role', 'status'); message.setAttribute('aria-live', 'polite'); message.textContent = '采集已启动，正在读取 BOOTH 下载库…';
  progress.setAttribute('aria-label', '已购清单采集进度'); progress.style.cssText = 'display:block;width:100%;margin:16px 0';
  close.style.cssText = 'padding:8px 16px;border:1px solid #ed8589;border-radius:6px;background:#392629;color:#e0dfe5;cursor:pointer;font:inherit';
  link.style.cssText = 'display:block;margin:16px 0;color:#ed8589;text-decoration:underline;font-weight:bold'; link.hidden = true; link.style.display = 'none';
  const cleanup = () => { controller.abort(); if (downloadUrl) URL.revokeObjectURL(downloadUrl); dialog.remove(); };
  close.textContent = '取消采集'; close.addEventListener('click', cleanup); dialog.addEventListener('cancel', event => { event.preventDefault(); cleanup(); });
  dialog.append(heading, message, progress, link, close); document.body.append(dialog); dialog.showModal();
  try {
    const result = await collectLibraryPages({ initialDocument: document, signal: controller.signal, onProgress: current => { message.textContent = `正在读取第 ${current.page} / ${current.pages} 页，已找到 ${current.products} 个商品。`; progress.max = Math.max(current.pages, current.page); progress.value = Math.max(0, current.page - 1); } });
    if (!dialog.isConnected || controller.signal.aborted) return;
    downloadUrl = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
    link.href = downloadUrl; link.download = 'booth-purchases-' + new Date().toISOString().slice(0, 10) + '.json'; link.textContent = '下载已购清单 JSON'; link.hidden = false; link.style.display = 'block'; link.click();
    progress.value = progress.max;
    dialog.dataset.collectionState = 'complete';
    message.textContent = `采集完成：${result.products.length} 个商品，共 ${result.pages} 页。已尝试下载 JSON；如未下载，请点击下方链接。然后回 BoothNest「数据管理」导入。`; close.textContent = '完成 / 关闭';
  } catch (error) { if (dialog.isConnected) { dialog.dataset.collectionState = 'error'; progress.hidden = true; progress.style.display = 'none'; message.textContent = '采集未完成，没有导出文件：' + error.message; close.textContent = '关闭'; } }
}
async function openPurchaseGuide() {
  const dialog = $('#purchase-guide-dialog'), zh = lang === 'zh';
  dialog.innerHTML = `<div class="dialog-heading"><div><h1>${zh ? '设置 BOOTH 已购采集' : 'Set up BOOTH purchase collection'}</h1><p>${zh ? '设置一次，以后在 BOOTH 下载库点击书签即可更新清单。' : 'Set up once, then run the bookmark in your BOOTH library.'}</p></div><button class="icon-btn" data-action="close-dialog" aria-label="${t('close')}">${icon('x')}</button></div><p class="purchase-guide-status" role="status">${zh ? '尚未开始采集。请在已登录 BOOTH 的普通浏览器页面运行书签；此处用于设置。' : 'Collection has not started. Run the bookmark in your signed-in BOOTH browser tab.'}</p><ol><li>${zh ? '在已登录 BOOTH 的 Chrome / Edge 中按 Ctrl+Shift+B，显示书签栏。' : 'In the Chrome / Edge browser signed into BOOTH, press Ctrl+Shift+B to show the bookmarks bar.'}</li><li>${zh ? '把下面的「采集 BOOTH 已购」拖到那个浏览器的书签栏。' : 'Drag the bookmark below to that browser’s bookmarks bar.'}<div class="data-actions"><a class="btn primary" id="purchase-guide-bookmark" href="#" draggable="true" data-action="bookmark-guide-help">${t('purchaseBookmark')}</a></div></li><li>${zh ? '打开 BOOTH 下载库，点击刚保存的书签。BOOTH 页面应出现采集进度窗口，并在完成后提供 JSON 下载。' : 'Open your BOOTH library and click the saved bookmark. A progress window appears there and provides a JSON download when complete.'}</li><li>${zh ? '回到这里关闭此说明，点「导入已购 JSON / HTML」，选择下载的 JSON。' : 'Return here, close this guide, and import the downloaded JSON.'}</li></ol><div class="data-actions"><button class="btn" data-action="copy-purchase-bookmark">${t('purchaseCopy')}</button><button class="btn" data-action="download-purchase-bookmark">${zh ? '下载书签文件' : 'Download bookmark file'}</button><a class="btn" href="https://accounts.booth.pm/library" target="_blank" rel="noopener noreferrer">${t('purchaseOpen')}${icon('external')}</a></div><details><summary>${zh ? '无法拖动或复制时，手动添加书签' : 'Add the bookmark manually'}</summary><p>${zh ? '新建一个书签，把下方完整内容粘贴为网址。也可下载书签文件，在普通浏览器的书签管理器中选择「导入书签」。' : 'Create a bookmark and paste the full text below as its URL, or import the downloaded bookmark file using your browser’s bookmarks manager.'}</p><textarea id="purchase-bookmark-address" readonly aria-label="${zh ? '完整书签地址' : 'Full bookmark URL'}" spellcheck="false"></textarea></details><p id="purchase-guide-feedback" class="form-feedback" role="status"></p>`;
  dialog.showModal();
  try { const url = await purchaseBookmarkUrl(); $('#purchase-guide-bookmark').href = url; $('#purchase-bookmark-address').value = url; }
  catch (error) { $('#purchase-guide-feedback').textContent = error.message; }
}

async function downloadPurchaseBookmark() {
  const url = await purchaseBookmarkUrl();
  const html = '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n<TITLE>BoothNest</TITLE>\n<H1>BoothNest</H1>\n<DL><p>\n<DT><A HREF="' + escape(url) + '">采集 BOOTH 已购</A>\n</DL><p>\n';
  const blobUrl = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' })), link = document.createElement('a');
  link.href = blobUrl; link.download = 'BoothNest-已购采集书签.html'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
  toast(lang === 'zh' ? '已下载书签文件。请在已登录 BOOTH 的浏览器书签管理器中导入。' : 'Import the downloaded bookmark file in your BOOTH browser’s bookmarks manager.');
}
function renderPurchaseSection() {
  const section = $('#purchase-section'); if (!section) return;
  const purchases = data?.purchases || status?.purchases || {};
  section.innerHTML = `<h2>${icon('check')}${t('purchaseTitle')}<span class="connection-state">${formatNumber(purchases.products || 0)} ${t('results')}</span></h2><h3 class="purchase-manual-title">${lang === 'zh' ? '手动采集与导入' : 'Manual collection and import'}</h3><p>${t('purchaseBasis')}</p><p class="purchase-steps">${t('purchaseSteps')}</p>${purchases.error ? `<p class="form-feedback error">${escape(purchases.error)}</p>` : ''}<div class="data-actions"><a class="btn primary" id="purchase-bookmark" data-action="bookmark-help" href="#" draggable="true">${icon('check')}${lang === 'zh' ? '设置采集书签' : 'Set up collection bookmark'}</a><button class="btn" data-action="copy-purchase-bookmark">${t('purchaseCopy')}</button><a class="btn" href="https://accounts.booth.pm/library" target="_blank" rel="noopener noreferrer">${t('purchaseOpen')}${icon('external')}</a></div><div class="data-actions"><label class="btn import-label" tabindex="0">${icon('upload')}${t('purchaseImport')}<input id="purchase-files" type="file" accept=".json,.html,.htm,application/json,text/html" multiple aria-label="${t('purchaseImport')}"></label><button class="btn" data-action="export-purchases" ${purchases.products ? '' : 'disabled'}>${icon('download')}${t('purchaseExport')}</button></div><p class="purchase-import-note">${t('purchaseImportHint')}</p><p id="purchase-feedback" class="form-feedback" role="status"></p>`;
  purchaseBookmarkUrl().then(url => { if (section.isConnected) section.querySelector('#purchase-bookmark').href = url; }).catch(error => { if (section.isConnected) section.querySelector('#purchase-feedback').textContent = error.message; });
  purchaseSyncUI.mount(section);
}
async function importPurchaseFiles(files) {
  const feedback = $('#purchase-feedback');
  feedback.textContent = ''; feedback.classList.remove('error');
  try {
    if ([...files].reduce((sum, file) => sum + file.size, 0) > 20000000) throw new Error('已购文件总大小不能超过 20 MB。');
    const products = [];
    for (const file of files) {
      const text = await file.text(); let value;
      if (/\.html?$/i.test(file.name)) value = { type: 'vrcatalogue-booth-purchases', schemaVersion: 1, source: 'https://accounts.booth.pm/library', products: extractLibraryPage(new DOMParser().parseFromString(text, 'text/html'), 'https://accounts.booth.pm/library').products };
      else value = JSON.parse(text);
      if (value?.type !== 'vrcatalogue-booth-purchases' || value.schemaVersion !== 1 || !['https://accounts.booth.pm/library', 'https://booth.pm/library'].includes(value.source) || !Array.isArray(value.products)) throw new Error('文件不是本工具支持的 BOOTH 已购清单。');
      products.push(...value.products);
    }
    const result = await api('/api/purchases/import', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ type: 'vrcatalogue-booth-purchases', schemaVersion: 1, source: 'https://accounts.booth.pm/library', products }) });
    await refreshStatus(); allFacets = null; await fetchItems(); toast(t('purchaseImported'));
    feedback.textContent = `${t('purchaseImported')} · +${result.added} / ↻${result.updated} · ${result.total} ${t('results')}`; feedback.classList.remove('error');
    const count = $('#purchase-section .connection-state'); if (count) count.textContent = `${result.total} ${t('results')}`;
    const exportButton = $('[data-action="export-purchases"]'); if (exportButton) exportButton.disabled = false;
  } catch (error) { feedback.textContent = error.message; feedback.classList.add('error'); }
}
function renderConnection() {
  const section = $('#connection-section'); if (!section) return;
  const library = data?.library || status?.library || {};
  section.innerHTML = `<h2>${icon('database')}${t('libraryConnection')}<span class="connection-state ${library.connected ? 'connected' : ''}">${t(library.connected ? 'localPresent' : 'disconnected')}</span></h2><p>${t('connectionHint')}</p>${library.connected ? `<p class="connection-summary"><strong>${formatNumber(library.products)}</strong> ${t('localProducts')} · ${formatNumber(library.entries)} ${t('entries')} · ${bytes(library.bytes)}<br>${t('scanned')} ${date(library.generatedAt)} · ${formatNumber(library.unidentified)} ${t('unidentified')}</p><p class="connection-path">${escape(library.path)}</p><p class="connection-path">${escape(library.root)}</p>` : ''}${library.error ? `<p class="form-feedback error">${escape(library.error)}</p>` : ''}<form id="library-form"><label class="sr-only" for="library-path">${t('pathLabel')}</label><input id="library-path" type="text" required placeholder="${t('pathLabel')}" value="${escape(library.path)}" autocomplete="off"><button class="btn primary" type="submit">${t('connect')}</button></form><div class="data-actions"><button class="btn" data-action="reload-library" ${library.path ? '' : 'disabled'}>${icon('refresh')}${t('reloadLibrary')}</button><button class="btn" data-action="disconnect-library" ${library.path ? '' : 'disabled'}>${t('disconnect')}</button></div><p id="library-feedback" class="form-feedback" role="status"></p>`;
}
async function updateLibrary(action, body = {}) {
  await api('/api/local/' + action, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  allFacets = null; await refreshStatus(); await fetchItems(); renderConnection(); toast(t('connectionSaved'));
}
function openAbout() {
  $('#about-dialog').innerHTML = `<button class="dialog-close icon-btn" data-action="close-dialog" aria-label="${t('close')}">${icon('x')}</button><img src="/favicon.svg" alt="" width="52" height="52"><h1>Booth<span>Nest</span></h1><p>${lang === 'zh' ? '一个可以留在你电脑里的 BOOTH / VRChat 素材探索页。独立实现，参考 VRCatalogue 的网格浏览与筛选体验。' : 'A BOOTH / VRChat asset explorer that stays on your computer. Independently implemented, inspired by VRCatalogue’s grid and filtering experience.'}</p><p>${t('dataNote')}</p><p>${lang === 'zh' ? '收藏和界面设置保存在本机数据目录，可在「数据管理」中导出。CNY / USD 使用固定参考汇率，不是实时报价。分类与适配结合 VRCatalogue 开放数据和商品说明，自动标注请以作者声明为准。VRCatalogue Open Data 采用 CC BY 4.0 许可。' : 'Favourites and preferences persist in the local data directory and can be exported from My library. CNY / USD use fixed reference rates, not live quotations. Categories and compatibility use VRCatalogue Open Data and listing text. Confirm automatic labels with the creator. VRCatalogue Open Data is licensed under CC BY 4.0.'}</p><p class="muted">${lang === 'zh' ? '本项目不是 VRCatalogue 官方网站，与 BOOTH、VRChat 及所列创作者无关联。商品及预览图版权归原作者所有。' : 'An unofficial independent project. Not affiliated with VRCatalogue, BOOTH, VRChat or listed creators. Products and previews belong to their respective creators.'}</p><a class="btn" href="https://booth.pm/" target="_blank" rel="noopener noreferrer">BOOTH ${icon('external')}</a><span class="version-label">v2.0.0-beta.5 · Local first</span>`;
  $('#about-dialog').showModal();
}
async function refreshStatus() {
  try {
    status = await api('/api/status');
    if (status.sync) { updateSyncState(status.sync); if (status.sync.config.enabled || status.sync.running) scheduleSyncPoll(status.sync.running ? 1500 : 15000); }
    const fields = $$('#data-dialog .library-stats strong');
    if (fields.length) { fields[0].textContent = formatNumber(status.items); fields[1].textContent = favourites.size; }
  } catch {}
}
function downloadJson(value, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = filename; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function importFile(file) {
  const feedback = $('#import-feedback');
  try {
    if (file.size > 20000000) throw new Error(lang === 'zh' ? '文件不能超过 20 MB。' : 'File must be under 20 MB.');
    const value = JSON.parse(await file.text());
    let result;
    if (value.type === 'vrcatalogue-favourites') result = { added: 0, updated: 0 };
    else result = await api('/api/import', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(value) });
    const ids = value.type === 'vrcatalogue-favourites' ? value.ids : value.favourites;
    if (Array.isArray(ids)) { ids.map(Number).filter(id => Number.isSafeInteger(id) && id > 0).forEach(id => favourites.add(id)); writeStorage('favourites', [...favourites]); }
    feedback.textContent = `${t('imported')} · +${result.added} / ↻${result.updated}`; feedback.classList.remove('error');
    await refreshStatus(); allFacets = null; await fetchItems(); toast(t('imported'));
  } catch (error) { feedback.textContent = error.message; feedback.classList.add('error'); }
}

document.addEventListener('click', async event => {
  const button = event.target.closest('[data-action]');
  if (!button || button.disabled) return;
  const action = button.dataset.action;
  if (action === 'view') { if (button.dataset.view === 'local') state.availability = 'all'; if (button.dataset.view === 'purchased' && state.purchase === 'not-recorded') state.purchase = 'all'; change('view', button.dataset.view); document.body.classList.remove('filters-open'); }
  else if (action === 'page') { change('page', Number(button.dataset.page), { keepPage: true }); $('#results').scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  else if (action === 'clear') change(button.dataset.key, []);
  else if (action === 'clear-tags') { state.excludeTag = []; change('tag', []); }
  else if (action === 'reset') resetFilters();
  else if (action === 'remove-filter') toggleFilter(button.dataset.key, button.dataset.value);
  else if (action === 'remove-q') change('q', '');
  else if (action === 'remove-free') change('free', false);
  else if (action === 'remove-mentions') change('includeMentions', false);
  else if (action === 'remove-price') { state.min = 0; change('max', null); }
  else if (action === 'remove-local') change(button.dataset.key, { availability: 'all', minBytes: 0, duplicates: false }[button.dataset.key]);
  else if (action === 'remove-purchase') change('purchase', 'all');
  else if (action === 'purchase-settings') { openData(); $('#purchase-section').scrollIntoView({ block: 'start' }); }
  else if (action === 'sync-settings') { openData(); $('#sync-section').scrollIntoView({ block: 'start' }); }
  else if (action === 'sync-run' || action === 'sync-stop' || action === 'sync-pause') {
    button.disabled = true;
    try {
      const suffix = action === 'sync-pause' ? 'config' : action === 'sync-run' ? 'run' : 'stop';
      const s = await api('/api/sync/' + suffix, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(action === 'sync-pause' ? { enabled: false } : {}) });
      updateSyncState(s); if (action === 'sync-pause') $('#sync-enabled').checked = false;
      if (action === 'sync-stop') { await refreshStatus(); allFacets = null; await fetchItems(); }
      scheduleSyncPoll(300);
    } catch (error) { toast(error.message); button.disabled = false; }
  }
  else if (action === 'bookmark-help') { event.preventDefault(); await openPurchaseGuide(); }
  else if (action === 'bookmark-guide-help') { event.preventDefault(); toast(t('bookmarkHint')); }
  else if (action === 'download-purchase-bookmark') { try { await downloadPurchaseBookmark(); } catch (error) { toast(error.message); } }
  else if (action === 'copy-purchase-bookmark') {
    try { await navigator.clipboard.writeText(await purchaseBookmarkUrl()); toast(t('purchaseCopied')); }
    catch { if (!$('#purchase-guide-dialog').open) await openPurchaseGuide(); const field = $('#purchase-bookmark-address'); field.closest('details').open = true; field.focus(); field.select(); toast(lang === 'zh' ? '自动复制不可用。已选中完整书签地址，请按 Ctrl+C。' : 'Copy is unavailable. Press Ctrl+C to copy the selected bookmark URL.'); }
  }
  else if (action === 'export-purchases') {
    try { downloadJson(await api('/api/purchases/export'), 'vrcatalogue-purchases.json'); } catch (error) { toast(error.message); }
  }
  else if (action === 'reload-library' || action === 'disconnect-library') {
    button.disabled = true;
    try { await updateLibrary(action === 'reload-library' ? 'reload' : 'disconnect'); }
    catch (error) { toast(error.message); button.disabled = false; }
  }
  else if (action === 'reveal-local') {
    const entry = detail?.local?.entries[Number(button.dataset.index)]; if (!entry) return;
    button.disabled = true;
    try { await api('/api/local/reveal', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id: detail.id, folder: entry.folder }) }); toast(t('revealed')); }
    catch (error) { toast(error.message); }
    finally { button.disabled = false; }
  }
  else if (action === 'tag') toggleFilter('tag', button.dataset.value);
  else if (action === 'exclude-tag') toggleFilter('excludeTag', button.dataset.value);
  else if (action === 'card-category') toggleFilter('category', button.dataset.value);
  else if (action === 'expand-category') { const slug = button.dataset.value; if (expandedCategories.has(slug)) expandedCategories.delete(slug); else expandedCategories.add(slug); renderSidebar(); }
  else if (action === 'favourite') toggleFavourite(Number(button.dataset.id));
  else if (action === 'detail') openDetail(Number(button.dataset.id));
  else if (action === 'detail-avatar' || action === 'detail-avatar-mention' || action === 'detail-tag') { $('#detail-dialog').close(); if (action === 'detail-avatar-mention') { state.includeMentions = true; syncInputs(); } toggleFilter(action === 'detail-tag' ? 'tag' : 'avatar', button.dataset.value); }
  else if (action === 'gallery-next' || action === 'gallery-prev' || action === 'gallery-index') { detailIndex = action === 'gallery-index' ? Number(button.dataset.index) : (detailIndex + (action === 'gallery-next' ? 1 : -1) + detail.media.length) % detail.media.length; renderDetail(); }
  else if (action === 'close-dialog') button.closest('dialog').close();
  else if (action === 'data') openData();
  else if (action === 'about') openAbout();
  else if (action === 'dismiss-notice') { $('#notice').hidden = true; writeStorage('notice-dismissed', true); }
  else if (action === 'toggle-filters') { document.body.classList.toggle('filters-open'); button.setAttribute('aria-expanded', document.body.classList.contains('filters-open')); }
  else if (action === 'density') { const compact = !$('#grid').classList.contains('compact'); $('#grid').classList.toggle('compact', compact); button.setAttribute('aria-pressed', compact); writeStorage('compact', compact); }
  else if (action === 'retry') fetchItems();
  else if (action === 'export-favourites') downloadJson({ type: 'vrcatalogue-favourites', schemaVersion: 1, exportedAt: new Date().toISOString(), ids: [...favourites], urls: [...favourites].map(id => `https://booth.pm/ja/items/${id}`) }, 'vrcatalogue-favourites.json');
  else if (action === 'export-catalog') {
    try { const exported = await api('/api/export'); downloadJson({ ...exported, favourites: [...favourites] }, 'vrcatalogue-library.json'); }
    catch (error) { toast(error.message); }
  } else if (action === 'refresh-item') {
    button.disabled = true; button.textContent = t('adding');
    try {
      await api('/api/booth', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id: Number(button.dataset.id) }) });
      detail = await api('/api/items/' + detail.id); detailIndex = 0; renderDetail(); allFacets = null; await refreshStatus(); await fetchItems(); toast(t('updated'));
    } catch (error) { toast(error.message); button.disabled = false; button.innerHTML = icon('refresh') + t('refresh'); }
  }
});

document.addEventListener('change', event => {
  const el = event.target;
  if (el.dataset.filter) toggleFilter(el.dataset.filter, el.value);
  else if (el.id === 'sort') change('sort', el.value);
  else if (el.id === 'page-size') change('pageSize', Number(el.value));
  else if (el.id === 'adult') change('adult', el.value);
  else if (el.id === 'availability') { if (state.view === 'local' && el.value === 'missing') state.view = 'items'; change('availability', el.value); }
  else if (el.id === 'min-bytes') change('minBytes', Number(el.value));
  else if (el.id === 'duplicates') change('duplicates', el.checked);
  else if (el.id === 'purchase-filter') { if (state.view === 'purchased' && el.value === 'not-recorded') state.view = 'items'; change('purchase', el.value); }
  else if (el.id === 'free') change('free', el.checked);
  else if (el.id === 'include-mentions') change('includeMentions', el.checked);
  else if (el.id === 'price-min' || el.id === 'price-max') {
    state.min = Math.max(0, Number($('#price-min').value) || 0); state.max = $('#price-max').value === '' ? null : Math.max(0, Number($('#price-max').value) || 0);
    if (state.max !== null && state.max < state.min) state.max = state.min;
    change('min', state.min);
  } else if (el.id === 'price-range') { state.min = Math.min(state.min, Number(el.value)); change('max', Number(el.value) === 15000 ? null : Number(el.value)); }
  else if (el.id === 'language') { lang = el.value; writeStorage('language', lang); applyLanguage(); if (data) render(); }
  else if (el.id === 'currency') { currency = el.value; writeStorage('currency', currency); if (data) renderGrid(); }
  else if (el.id === 'theme') { theme = el.value; document.documentElement.dataset.theme = theme; writeStorage('theme', theme); }
  else if (el.id === 'import-file' && el.files[0]) importFile(el.files[0]);
  else if (el.id === 'purchase-files' && el.files.length) importPurchaseFiles(el.files);
});
let searchTimer;
function scheduleSearch(event) { clearTimeout(searchTimer); if (event.isComposing) return; const value = event.target.value; searchTimer = setTimeout(() => change('q', value, { replace: true }), 120); }
$('#search').addEventListener('input', scheduleSearch);
$('#search').addEventListener('compositionend', scheduleSearch);
$('#search-form').addEventListener('submit', event => { event.preventDefault(); clearTimeout(searchTimer); change('q', $('#search').value, { replace: true }); });
['avatar', 'author', 'tag'].forEach(key => $('#' + key + '-search').addEventListener('input', () => renderOptions(key)));
document.addEventListener('submit', async event => {
  if (event.target.id === 'sync-form') {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
    try {
      const s = await api('/api/sync/config', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled: $('#sync-enabled').checked, queries: $('#sync-queries').value, intervalMinutes: Number($('#sync-interval').value), batchSize: Number($('#sync-batch').value), refreshHours: Number($('#sync-refresh').value) }) });
      updateSyncState(s); $('#sync-feedback').textContent = t('syncSaved'); scheduleSyncPoll(15000);
    } catch (error) { $('#sync-feedback').textContent = error.message; $('#sync-feedback').classList.add('error'); }
    finally { button.disabled = false; }
    return;
  }
  if (event.target.id === 'library-form') {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
    try { await updateLibrary('connect', { path: $('#library-path').value.trim() }); }
    catch (error) { $('#library-feedback').textContent = error.message; $('#library-feedback').classList.add('error'); button.disabled = false; }
    return;
  }
  if (event.target.id === 'online-form') {
    event.preventDefault();
    const button = event.target.querySelector('button'), feedback = $('#online-feedback');
    button.disabled = true; button.textContent = t('onlineBusy'); feedback.textContent = '';
    try {
      const result = await api('/api/booth-search', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ q: $('#online-query').value.trim(), limit: 6 }) });
      feedback.textContent = lang === 'zh' ? `已新增 ${result.added} 条、更新 ${result.updated} 条${result.failed.length ? `；${result.failed.length} 条暂时无法读取` : ''}${result.found ? '' : '；没有找到结果'}。` : `${result.added} added, ${result.updated} refreshed, ${result.failed.length} unavailable.${result.found ? '' : ' No results.'}`;
      feedback.classList.remove('error'); allFacets = null; await refreshStatus(); await fetchItems(); toast(t('imported'));
    } catch (error) { feedback.textContent = error.message; feedback.classList.add('error'); }
    finally { button.disabled = false; button.innerHTML = icon('search') + (lang === 'zh' ? '搜索并收录' : 'Search & collect'); }
    return;
  }
  if (event.target.id !== 'booth-form') return;
  event.preventDefault(); const button = event.target.querySelector('button'), feedback = $('#booth-feedback');
  button.disabled = true; button.textContent = t('adding'); feedback.textContent = '';
  try {
    const result = await api('/api/booth', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: $('#booth-url').value.trim() }) });
    feedback.textContent = `${t('added')} · ${result.title}`; feedback.classList.remove('error');
    allFacets = null; await refreshStatus(); await fetchItems(); toast(t('added'));
  } catch (error) { feedback.textContent = error.message; feedback.classList.add('error'); }
  finally { button.disabled = false; button.textContent = t('add'); }
});
document.addEventListener('error', event => {
  const img = event.target;
  if (img.tagName !== 'IMG' || img.dataset.fallback) return;
  let candidates = []; try { candidates = JSON.parse(img.dataset.imageCandidates || '[]'); } catch {}
  const next = candidates.shift(); img.dataset.imageCandidates = JSON.stringify(candidates);
  if (!next) img.dataset.fallback = 'true';
  img.src = next || '/placeholder.svg';
}, true);
$$('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } }));
document.addEventListener('keydown', event => {
  if (event.key === '/' && !event.ctrlKey && !event.metaKey && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !$$('dialog[open]').length) { event.preventDefault(); $('#search').focus(); }
  if ($('#detail-dialog').open && detail?.media.length > 1 && ['ArrowLeft', 'ArrowRight'].includes(event.key)) { event.preventDefault(); detailIndex = (detailIndex + (event.key === 'ArrowRight' ? 1 : -1) + detail.media.length) % detail.media.length; renderDetail(); }
  if (event.target.classList.contains('import-label') && ['Enter', ' '].includes(event.key)) { event.preventDefault(); event.target.querySelector('input[type="file"]')?.click(); }
});
window.addEventListener('popstate', () => { clearTimeout(searchTimer); state = stateFromUrl(); syncInputs(); fetchItems(); });
document.documentElement.dataset.theme = theme;
$('#notice').hidden = readStorage('notice-dismissed', false);
$('#grid').classList.toggle('compact', readStorage('compact', false));
discoveryUI = initDiscovery({
  api, escape, icon, language: () => lang, readStorage, writeStorage, getView: () => state.view,
  getQuery: () => {
    const query = paramsForState(), q = $('#search').value.trim();
    if (q) query.set('q', q); else query.delete('q');
    return query.toString();
  },
  applyQuery: query => {
    clearTimeout(searchTimer); state = stateFromUrl('?' + savedFilterQuery(query));
    syncUrl(); syncInputs(); document.body.classList.remove('filters-open'); fetchItems();
  },
  selectGroup: (group, value) => {
    clearTimeout(searchTimer);
    const query = new URLSearchParams({ adult: state.adult });
    query.set(({ avatars: 'avatar', authors: 'author', tags: 'tag', query: 'q' })[group], value);
    state = stateFromUrl('?' + query); syncUrl(); syncInputs(); fetchItems();
  },
  openItem: openDetail,
  onHistoryChange: () => { if (state.view === 'recent') fetchItems(); else if (data) renderGrid(); },
  toast,
});
applyLanguage(); syncInputs();
const setupSection = new URLSearchParams(location.search).get('setup');
const scanButton = document.createElement('button'); scanButton.className = 'btn'; scanButton.type = 'button'; scanButton.dataset.scanOpen = ''; scanButton.textContent = lang === 'zh' ? '扫描下载目录' : 'Scan downloads'; $('#results .toolbar-left').append(scanButton);
const classicLink = document.createElement('a'); classicLink.href = '/classic'; classicLink.textContent = lang === 'zh' ? '完整管理' : 'Full manager'; $('.top-nav').append(classicLink);
initLocalScan({ api, escape, language: () => lang, onChanged: async () => { await refreshStatus(); allFacets = null; await fetchItems(); } });
const localToolsUI = initLocalTools({ api, icon, escape, bytes, language: () => lang, onChanged: async () => { await refreshStatus(); allFacets = null; await fetchItems(); if ($('#detail-dialog').open) $('#detail-dialog').close(); } });
const purchaseSyncUI = initPurchaseSync({ api, escape, language: () => lang, onSynced: async () => { await refreshStatus(); allFacets = null; await fetchItems(); renderPurchaseSection(); } });
await refreshStatus();
await fetchItems();
if (setupSection === 'purchases' || setupSection === 'sync') { openData(); $('#' + (setupSection === 'sync' ? 'sync-section' : 'purchase-section')).scrollIntoView({ block: 'start' }); }
if (setupSection === 'local') await localToolsUI.open();
