# SPDX-License-Identifier: GPL-3.0-only
"""回归测试：验证匹配引擎行为与已验证的 8 轮迭代结论一致。

用例全部由**真实文件名**驱动 —— token 与整串都走 tokens()/raw_chunks() 生成，
而不是手写 token 列表。这样测的是线上真正跑的那条路径
（手写 token 会绕过 STOP 表过滤，测出假结果）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from boothlib import matching as M  # noqa: E402

CASES = []


def case(name, filename, title, shop, sub, want):
    CASES.append((name, filename, title, shop, sub, want))


# ---------------- 应当接受 ----------------
case("独特整串 PaleNightSailor", "【9人适配】PaleNightSailor",
     "【9アバター対応】PaleNightSailor【VRChat向け衣装】", "Code:2l9", "code2l9", True)
case("独特整串 MessyClassmate", "MessyClassmate.zip",
     "【VRC】ギミック搭載衣装 👔「MessyClassmate」 👔【5アバター対応】",
     "BUGAISYA", "bugaisya", True)
case("独特整串 SnowDrops", "SnowDrops_Shinano_Ver1.0.1.zip",
     "【14アバター対応】SnowDrops 【VRChat向け衣装モデル】", "EYECLO", "ey-eclo", True)
case("变音符号 Mòryu", "【14人适配】Mòryu",
     "『FREE ITEM』Mòryu『16アバター対応』", "hansori", "hansori", True)
case("独特整串 FuwawaPrim", "NFD_FuwawaPrim_MaterialPack_V1.00.zip",
     "オリジナル3Dモデル「FuwawaPrim-ふわわぷりむ-」#なっふな堂",
     "なっふな堂", "nyahuuu", True)
case("标题全覆盖 Classy", "Classy", "【11アバター対応】Classy",
     "cherry neru", "cherryneru", True)
case("标题全覆盖 DRIFTLINE", "【5人适配】DRIFTLINE - GRUNGE Y2K TECH",
     "【5アバター対応】DRIFTLINE - GRUNGE Y2K / TECH", "a2x4", "a2x4", True)
case("标题覆盖 Melling みずぽよ", "【10人适配】Melling みずぽよ",
     "🖤Melling \" みずぽよ\" 【11アバター対応 🖤 Liltoon / VRChat】🖤",
     "Melling", "melling", True)
case("店铺佐证 Devil Cadet", "_Ene_Collection__Devil_Cadet_Materials_v1.0.zip",
     "Devil Cadet", "Ene Collection", "ene-collection", True)
case("店铺佐证 Stella Marshal",
     "apps/极空间/_Ene_Collection__Stella_Marshal_Material.zip",
     "Stella Marshal", "Ene Collection", "ene-collection", True)
case("店铺佐证 Mono Blanco", "_Ene_Collection__Mono_Blanco_Material_v1.0.zip",
     "Mono Blanco", "Ene Collection", "ene-collection", True)
case("店铺佐证 Stray Angel", "_Momo_Secret__Stray_Angel_Material_pack.zip",
     "[🔥オープン週末セール55%🔥]<Stray Angel> 14 colors💕 15アバター対応！",
     "Momo Secret", "momo-secret", True)
case("店铺佐证 NyamLoveRaider", "NyamLoveRaider_material_v.1.00.zip",
     "【13avatars】NyamLoveRaider -VRC想定-", "Nya!byte", "nyabyte", True)

# ---------------- 应当拒绝（全部是实战假阳性）----------------
case("反例 Ravenor≠Night Raven", "Ravenor.jpg",
     "🐦‍⬛【VRC 衣装】Night Raven - Noir", "VELLIE", "vellie", False)
case("反例 Cuddle Coddle", "Materials_Cuddle_Coddle_v1.0.zip",
     "「cuddle」10cm無属性ぬいぐるみ・PFRU　フル", "cuddle-dlf", "cuddledlf", False)
case("反例 Seaside Breeze", "Seaside Breeze",
     "SeaSideX【Keyball無線化キット】", "Seaside Works", "seasideworks", False)
case("反例 Bloom Matsuri", "Bloom_Matsuri.zip",
     "matsurihi.me Technical Report 2023.12.31",
     "matsurihi.me", "matsurihime", False)
case("反例 LilToon 通用词", "LilToonWaveShader.zip",
     "【Shader】lilToon_FresnelAlphaEx", "AdamEve桜", "adameve", False)
case("反例 Silent Her≠stratosphere", "05_Silent_Her_For_Shinano.zip",
     "Silent stratosphere", "埼玉最終兵器＆Aether", "aether", False)
case("反例 Stella≠Stellar Shine",
     "_Ene_Collection__Stella_Marshal_Shinano_v1.0(1).zip",
     "✨ Stellar Shine ✨ - liltoon スキン・マテリアル・プリセット",
     "Qrochairo Store", "qrochairo", False)
case("反例 Devil≠devil bob", "_Ene_Collection__Devil_Cadet_Materials_v1.0.zip",
     " devil bob 【10Avatars】", "Salon de Musubi", "salondemusubi", False)
case("正例 ZBrushCore 工具包", "ZBrushCore.rar",
     "ZbrushCoreセミナーデータサンプル", "家鴨屋ぽんのおみせ", "kamo", True)


def main():
    fails = []
    for name, fn, title, shop, sub, want in CASES:
        base = fn.split("/")[-1]
        qt = M.tokens(base)
        ch = M.raw_chunks(base)
        r = M.evaluate(qt, title, shop, sub, ch)
        ok = r["accept"] == want
        if not ok:
            fails.append(name)
        print(f"[{'PASS' if ok else 'FAIL'}] {name:32s} "
              f"accept={str(r['accept']):5s} (want {str(want):5s}) "
              f"cov={r['title_cov']:.2f} dec={str(r['decisive']):5s} "
              f"shop={str(r['shop_hit']):5s} tok={qt}")
    print()
    print(f"{len(CASES) - len(fails)}/{len(CASES)} passed")
    if fails:
        print("FAILED:", fails)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
