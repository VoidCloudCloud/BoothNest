# SPDX-License-Identifier: GPL-3.0-only
"""名称匹配引擎（从实战迭代 8 轮后的最终判据整理而来）。

三层证据，从强到弱：
  1. 文件名里的 7 位 BOOTH ID           → 直接命中，最可靠
  2. 压缩包内部资产路径 ↔ BOOTH 店铺名   → 交叉校验
  3. 名称搜索反查 + 三重判据             → 见 evaluate()

三重判据（精度关键，全部是踩坑换来的）：
  A. 独特整串连写命中：长度 >=8 且由 >=2 段组成的 camelCase 串
     （PaleNightSailor / MessyClassmate / SnowDrops）连写出现在完整标题里。
     「>=2 段」是精度闸门：单个英文单词（Collection / Breeze）撞词概率太高。
  B. 标题覆盖率 >=0.75 且至少一个强词元。
  C. 标题**精确**覆盖 >=0.5 + 店铺名精确佐证 + 最长词元被佐证。
     必须「精确」：Seaside Breeze 靠 fuzzy 撞上 SeaSideX 键盘套件就是反例。

另外两条硬约束：
  - 最长词元必须被标题或店铺佐证（挡 Cuddle Coddle 撞「cuddle」ぬいぐるみ）
  - 角色名（Milltina / forShinano）不作为识别性整串（会把无关商品全拉进来）
"""
from __future__ import annotations

import os
import re
import unicodedata

# ---------------------------------------------------------------- 词典
AVATARS = {
    "shinano", "milltina", "airi", "eku", "manuka", "mizuki", "rurune", "selestia",
    "shinra", "sio", "moe", "kikyo", "lime", "chiffon", "chocolat", "lumina", "maya",
    "kumaly", "milfy", "lasyusha", "mao", "mayo", "plum", "ramune", "ichigo",
    "mamehinata", "lapwing", "andi", "ririka", "mafuyu", "nemesis", "komado",
    "rondo", "grusha", "rusk", "sock", "misaki",
}

# 通用词：留在 token 里没有区分度，只会制造假阳性
STOP = {
    "psd", "material", "materials", "mat", "tex", "texture", "textures", "pack",
    "materialpack", "texturepack", "package", "fullset", "full", "set", "gimmick", "gimmicks",
    "prefab", "others", "other", "common", "readme", "read", "me", "ver", "version",
    "unitypackage", "zip", "rar", "for", "and", "the", "of", "data", "only",
    "import", "first", "please", "files", "file", "use", "howto", "instruction",
    "instructions", "all", "new", "old", "main", "sub", "part", "parts", "item",
    "items", "extra", "bonus", "addon", "add", "on", "vrc", "vrchat", "avatar",
    "avatars", "3d", "model", "unity", "shop", "user", "manual",
    # 通用技术词（LilToonWaveShader 曾撞上另一个 lilToon 着色器）
    "shader", "shaders", "liltoon", "poiyomi", "udonsharp", "ndmf", "matcap",
    "fresnel", "outline", "rimlight", "emissive", "pbr", "urp", "hdrp",
    "tool", "tools", "system", "plugin", "script", "extension",
}

STOP_CJK = {
    "説明画像", "素材", "衣装", "対応", "マテリアル", "テクスチャ", "モデル", "セット",
    "変更", "改変", "共通", "最初", "導入", "絶対", "必ず", "入れて", "ください",
    "用", "版", "商品", "画像", "ファイル", "同梱", "本体", "基本", "内容", "確認",
    "アバター", "まとめ", "その他", "全部", "全て", "おまけ", "特典", "更新",
    "追加", "修正", "最新", "旧", "新", "人适配", "适配", "衣服", "模型",
}

# 带变音符号的拉丁扩展区；★ 必须显式含 A-Z，否则 MessyClassmate 会被切成
# 'essy' + 'lassmate'（大写被当分隔符丢掉）
_LAT = r"0-9A-Za-z\u00c0-\u024f\u1e00-\u1eff"
_CJK = r"\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f\u3005"

_ADAPT = re.compile(
    r"[【\[\(（]?\s*\d+\s*(?:人适配|アバター対応|人対応|avatars?対応)"
    r"\s*[】\]\)）]?", re.I)


# ---------------------------------------------------------------- 文本工具
_FILE_EXTENSIONS = {
    ".zip", ".rar", ".7z", ".unitypackage", ".fbx", ".blend", ".obj",
    ".png", ".jpg", ".jpeg", ".webp", ".psd", ".clip", ".txt", ".pdf",
    ".stl", ".mp4", ".wav", ".mp3", ".exe", ".msi",
}


def _name_stem(name: str) -> str:
    """Strip real file extensions, preserving dotted product/series names."""
    value = unicodedata.normalize("NFKC", name or "")
    stem, extension = os.path.splitext(value)
    return stem if extension.lower() in _FILE_EXTENSIONS else value


def norm_text(s: str) -> str:
    """归一化：小写，去掉标点/空白/下划线，保留所有 Unicode 字母数字。

    Unicode 感知是必须的：ASCII-only 会吞掉 Mòryu 的 ò、Rosée 的 é。
    """
    value = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[\W_]", "", value.lower(), flags=re.UNICODE)


def _camel_parts(w: str) -> list[str]:
    w = unicodedata.normalize("NFKC", w)
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", w)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    s = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", s)
    return [p.lower() for p in s.split() if p]


def words(s: str) -> set[str]:
    """按书写系统切词，并对 camelCase 追加组成段。

    '衣装MessyClassmate' 若整体成一个词，'messy' 就永远匹配不上；
    所以拉丁串与 CJK 串分别抽取，且 camelCase 词额外产出 'messy'、'classmate'。
    """
    s = unicodedata.normalize("NFKC", s or "")
    raw = re.findall(rf"[{_LAT}]+|[{_CJK}]+", s, flags=re.IGNORECASE)
    out = {w.lower() for w in raw}
    for w in raw:                      # 在**原始大小写**上拆，先 lower 会抹掉边界
        if re.fullmatch(rf"[{_LAT}]+", w) and len(w) >= 6:
            for p in _camel_parts(w):
                if len(p) >= 3:
                    out.add(p)
    return out


def tokens(name: str) -> list[str]:
    """把文件名切成有区分度的词元。"""
    s = _name_stem(name)
    s = re.sub(r"(?<!\d)\d{7}(?!\d)", " ", s)
    s = _ADAPT.sub(" ", s)
    s = re.sub(r"[\[\]\(\)（）【】「」『』]", " ", s)
    s = re.sub(r"[_\-\.\+,;:!'\"]+", " ", s)
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", s)
    s = re.sub(r"(?i)\b(ver|version|v)\s*[\d\.]+", " ", s)
    out = []
    for t in s.split():
        tl = t.lower().strip()
        if not tl or re.fullmatch(r"[\d\.]+", tl):
            continue
        if tl in STOP or tl in AVATARS or tl in STOP_CJK:
            continue
        has_cjk = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", tl))
        if len(tl) >= (3 if has_cjk else 3) and tl not in out:
            out.append(tl)
    return out


def signature(name: str) -> str:
    return "|".join(sorted(tokens(name)))


_AVATAR_NORMS: set[str] | None = None


def _avatar_norms() -> set[str]:
    global _AVATAR_NORMS
    if _AVATAR_NORMS is None:
        s = {norm_text(a) for a in AVATARS if len(norm_text(a)) >= 5}
        for a in ("しなの", "ミルティナ", "マヌカ", "ショコラ", "シフォン", "ルルネ",
                  "ミルフィ", "ライム", "セレスティア", "瑞希", "ルミナ", "エク",
                  "プラム", "まよ", "クマリ", "ラムネ", "イチゴ", "桔梗",
                  "ラシューシャ"):
            s.add(norm_text(a))
        _AVATAR_NORMS = s
    return _AVATAR_NORMS


def raw_chunks(name: str) -> list[str]:
    """提取原始文件名里的完整拉丁串（含 camelCase 整体），用作搜索查询词。

    剔除：STOP 词、含角色名的串（Milltina / forShinano）、数字过多的串。
    """
    an = _avatar_norms()
    s = _name_stem(name)
    s = re.sub(r"(?<!\d)\d{7}(?!\d)", " ", s)
    s = _ADAPT.sub(" ", s)
    out = []
    # [^\W_] 而不是 \w：\w 含下划线，会把 'NFD_FuwawaPrim_MaterialPack' 整体
    # 吃成一个串，导致本该定案的 'FuwawaPrim' 丢失。
    for c in re.findall(r"[^\W\d_][^\W_]{3,}", s, flags=re.UNICODE):
        if c.lower() in STOP or not tokens(c):
            continue
        if sum(ch.isdigit() for ch in c) > len(c) / 2:
            continue
        nc = norm_text(c)
        if not nc or nc in an:
            continue
        if any(a in nc for a in an if len(a) >= 5):
            continue
        out.append(c)
    return list(dict.fromkeys(out))


def search_queries(qtokens: list[str], chunks: list[str]) -> list[str]:
    """Try compound names before broad words; deduplicate case variants."""
    meaningful = [t for t in qtokens if len(norm_text(t)) >= 3
                  and t not in {"collection", "package"}]
    ordered = sorted(meaningful, key=len, reverse=True)
    queries = []
    if 2 <= len(ordered) <= 3:
        queries.append(" ".join(ordered))
    if len(ordered) >= 2:
        queries.append(" ".join(ordered[:2]))
    queries.extend(c for c in sorted(chunks, key=len, reverse=True)
                   if len(norm_text(c)) >= 5 and tokens(c)
                   and norm_text(c) != "collection")
    queries.extend(t for t in ordered if len(norm_text(t)) >= 4)
    unique = {}
    for query in queries:
        key = " ".join(unicodedata.normalize("NFKC", query).casefold().split())
        unique.setdefault(key, query)
    return list(unique.values())[:6]


def best_match(matches: list[dict]) -> dict | None:
    """Short exact names need a unique winner, or independent shop evidence."""
    if not matches:
        return None
    ranked = sorted(matches, key=lambda match: match["score"], reverse=True)
    best = ranked[0]
    if best.get("exact_name") and any(
            other["id"] != best["id"] and other["score"] >= best["score"]
            for other in ranked[1:]):
        return None
    return best


# ---------------------------------------------------------------- 判据
def is_strong(t: str) -> bool:
    tn = norm_text(t)
    if not tn:
        return False
    has_cjk = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", tn))
    return len(tn) >= (3 if has_cjk else 5)


def hit_in(t: str, text_norm: str, text_words: set[str]) -> tuple[bool, bool]:
    """token 是否命中标题。返回 (hit, fuzzy)。

    fuzzy 只允许「token 是更长单词的前缀扩展」单向：
      loveable⊂unloveable、charme⊂charmed、obsidia⊂obsidian
    禁止反向（token 比命中的词更长），否则 Ravenor 会因内含 raven 撞 Night Raven。
    """
    tn = norm_text(t)
    if not tn:
        return False, False
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", tn):
        return (len(tn) >= 3 and tn in text_norm), False
    if tn in text_words:
        return True, False
    if len(tn) >= 6:
        for w in text_words:
            if tn in w and 0 <= len(w) - len(tn) <= 3:
                return True, True
    return False, False


def chunk_hit(chunk: str, title: str) -> bool:
    cn, cc = norm_text(title), norm_text(chunk)
    if len(cc) < 6:
        return False
    if cc in cn:
        return True
    ws = words(title)
    parts = [p for p in _camel_parts(chunk) if len(p) >= 3]
    return len(parts) >= 2 and all(p in ws for p in parts)


def chunk_decisive(chunk: str, title: str) -> bool:
    """独特整串连写命中 → 可单独定案。"""
    cc = norm_text(chunk)
    if len(cc) < 8:
        return False
    if len(_camel_parts(chunk)) < 2:
        return False
    return cc in norm_text(title)


def evaluate(qtokens: list[str], title: str, shop_name: str = "",
             shop_sub: str = "", chunks: list[str] | None = None) -> dict:
    """返回判定结果 dict。"""
    chunks = chunks or []
    if not qtokens and not chunks:
        return {"accept": False, "title_cov": 0.0, "shop_hit": False,
                "strong": False, "fuzzy": False, "decisive": False, "score": 0.0}

    tnorm, tws = norm_text(title), words(title)
    hits = exact = 0
    fuzzy = strong = False
    title_hit_tokens: set[str] = set()
    for t in qtokens:
        h, fz = hit_in(t, tnorm, tws)
        if h:
            hits += 1
            title_hit_tokens.add(t)
            if fz:
                fuzzy = True
            else:
                exact += 1
                if is_strong(t):
                    strong = True
    title_cov = hits / len(qtokens) if qtokens else 0.0
    title_exact = exact / len(qtokens) if qtokens else 0.0

    sws, snorm = words(shop_name), norm_text(shop_name)
    subn = norm_text((shop_sub or "").replace("-", ""))
    shop_hit = False
    # ★ 独立佐证：命中的词必须来自**没在标题里命中过**的词元。
    #   Cuddle Coddle 的 'cuddle' 同时命中标题与店铺（店铺叫 cuddle-dlf），
    #   那是同一个词的巧合，不是两条独立证据 → 必须挡住。
    independent_shop = False
    for t in list(qtokens) + list(chunks):
        tn = norm_text(t)
        if len(tn) < 4:
            continue
        hit_shop = False
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", tn):
            hit_shop = tn in snorm
        else:
            hit_shop = tn in sws or tn == subn
        if hit_shop:
            shop_hit = True
            if t not in title_hit_tokens and not any(
                    norm_text(t) == norm_text(x) for x in title_hit_tokens):
                independent_shop = True

    # 最长词元（可能并列）必须**全部**被标题或店铺佐证。
    # Cuddle Coddle 的最长词 'coddle' 既不在标题也不在店铺 → 拒绝。
    if qtokens:
        maxlen = max(len(norm_text(x)) for x in qtokens)
        tops = [x for x in qtokens if len(norm_text(x)) == maxlen]
    else:
        tops = []
    longest_ok = True
    for longest in tops:
        lh, _ = hit_in(longest, tnorm, tws)
        ln = norm_text(longest)
        ok = bool(lh) or bool(
            ln and (ln in sws or ln == subn or
                    (len(ln) >= 3 and re.search(r"[\u3040-\u30ff\u3400-\u9fff]", ln)
                     and ln in snorm)))
        if not ok:
            longest_ok = False
            break

    dec = any(chunk_decisive(c, title) for c in chunks)
    ch_ok = any(chunk_hit(c, title) for c in chunks)
    # Two short words (Yoi_Koi, Wing Veil) are useful together. Accept only
    # the complete title core, never a partial name or a fuzzy coincidence.
    exact_name = bool(len(set(qtokens)) >= 2 and title_exact == 1.0
                      and not fuzzy and set(tokens(title)) == set(qtokens))

    accept = bool(
        dec
        or exact_name
        or (title_cov >= 0.75 and strong and longest_ok)
        or (title_exact >= 0.5 and strong and independent_shop and longest_ok)
    )
    score = (title_cov * 2 + (0.6 if shop_hit else 0) + (0.3 if strong else 0)
             + (1.2 if dec else (0.4 if ch_ok else 0))
             + (0.4 if exact_name else 0) - (0.15 if fuzzy else 0))
    return {"accept": accept, "title_cov": round(title_cov, 4),
            "title_exact": round(title_exact, 4), "shop_hit": shop_hit,
            "independent_shop": independent_shop, "strong": strong,
            "fuzzy": fuzzy, "decisive": dec, "exact_name": exact_name,
            "score": round(score, 4)}


def shop_cross_roots(asset_roots: list[str], shop_name: str,
                     shop_sub: str) -> bool:
    """包内资产根目录 ↔ BOOTH 店铺名 交叉校验。"""
    if not asset_roots:
        return False
    cands = [norm_text(shop_name),
             norm_text((shop_sub or "").replace("-", ""))]
    cands = [c for c in cands if len(c) >= 3]
    for r in asset_roots:
        rn = norm_text(r)
        if len(rn) < 3:
            continue
        for c in cands:
            if rn == c or (len(rn) >= 4 and rn in c) or (len(c) >= 4 and c in rn):
                return True
    return False
