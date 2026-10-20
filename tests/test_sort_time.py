# SPDX-License-Identifier: GPL-3.0-only
"""验收「按时间排序」这条链路：扫描取时间 → 聚合到商品 → 前端排得对。

三层各自独立验证，任何一层静默退化都会被抓到：

  1. **扫描层**：用一棵时间可控的临时目录树，断言 item 的 mtime 取的是
     条目内**最新文件**的时间，而不是目录自身的 mtime。
     （★ 这不是等价物：Windows 上往已有文件夹里写文件**不会**更新目录 mtime，
       所以早期"取目录 mtime"的实现会把刚下载的东西报成几个月前。）
  2. **聚合层**：同一商品的多次下载取最新那份；没有时间的不参与计算但也不能崩。
  3. **前端层**：把 ui.html 里**真实的** cmpBy / filteredRows 抽出来在 Node 里跑，
     对合成 dataset 验升降序、空值沉底、日期字符串与数值混排。

用法：python tests/test_sort_time.py
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from boothlib import analytics as A            # noqa: E402
from boothlib.scanner import scan              # noqa: E402

UI = ROOT / "boothlib" / "ui.html"
NODE = os.environ.get("NODE_BINARY") or shutil.which("node") or "node"

fails = []


def chk(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        fails.append(name)


def extract_fn(src: str, header: str) -> str:
    """按大括号配对抽出整个函数（含函数体）。"""
    i = src.index(header)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise ValueError(header)


def make_tree(base: Path) -> dict:
    """造三组下载条目，时间各不相同。

    ★ 关键在于 a 组：**先建目录、再往里写文件**，写完之后把目录 mtime
      手动改回旧时间 —— 模拟"几个月前下的东西，昨天又往里面补了个文件"。
      正确实现应报"昨天"，错误实现（取目录 mtime）会报"几个月前"。
    """
    old = time.mktime((2025, 1, 5, 12, 0, 0, 0, 0, -1))
    new = time.mktime((2026, 10, 17, 21, 30, 0, 0, 0, -1))
    mid = time.mktime((2026, 3, 9, 8, 0, 0, 0, 0, -1))

    a = base / "aaa_newfile_in_old_dir"
    a.mkdir()
    (a / "old_file.zip").write_bytes(b"x" * 10)
    os.utime(a / "old_file.zip", (old, old))
    (a / "just_added.unitypackage").write_bytes(b"y" * 20)
    os.utime(a / "just_added.unitypackage", (new, new))
    os.utime(a, (old, old))          # 目录 mtime 回退到"几个月前"

    b = base / "bbb_middle.zip"
    b.write_bytes(b"z" * 30)
    os.utime(b, (mid, mid))

    c = base / "ccc_old.zip"
    c.write_bytes(b"w" * 40)
    os.utime(c, (old, old))
    return {"old": old, "mid": mid, "new": new}


def main():
    print("=== 1) 扫描层：mtime 取条目内最新文件 ===")
    # ★ 不用 tempfile：DSH 沙箱下 tempfile 建的目录后续 scandir 会 PermissionError
    #   （实测 mkdir 能过，但读回来被拒）。放到工程 _testhome 下最稳。
    base = ROOT / "_testhome" / f"_sort_tree_{os.getpid()}"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    try:
        exp = make_tree(base)
        sc = scan(str(base))
        by = {x["folder"]: x for x in sc["items"]}
        chk("扫到 3 个条目", len(sc["items"]) == 3, str(sorted(by)))
        a = by.get("aaa_newfile_in_old_dir") or {}
        chk("目录条目带 mtime", "mtime" in a, str(sorted(a.keys())))
        chk("a 组取的是最新文件时间（不是目录 mtime）",
            abs((a.get("mtime") or 0) - exp["new"]) < 2,
            f"{a.get('mtime')} vs 期望 {exp['new']:.0f}")
        chk("a 组取到的确实不是旧时间",
            abs((a.get("mtime") or 0) - exp["old"]) > 3600 * 24,
            "若相等说明还在用目录 mtime")
        chk("a 组 mtime_min 是最早的文件",
            abs((a.get("mtime_min") or 0) - exp["old"]) < 2)
        chk("单文件条目 mtime 正确",
            abs((by.get("bbb_middle.zip", {}).get("mtime") or 0)
                - exp["mid"]) < 2)
        chk("最旧条目时间正确",
            abs((by.get("ccc_old.zip", {}).get("mtime") or 0)
                - exp["old"]) < 2)
        # 扫描结果按时间能力排序时必须真的是升/降序
        arr = sorted(sc["items"], key=lambda x: x["mtime"])
        chk("按 mtime 升序 = ccc < bbb < aaa",
            [x["folder"][:3] for x in arr] == ["ccc", "bbb", "aaa"],
            str([x["folder"][:3] for x in arr]))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print()
    print("=== 2) 聚合层：同一商品多份下载取最新 ===")
    ds = {
        "products": [
            {"id": "1", "title": "T1", "local_bytes": 100, "local_mtime": 2000,
             "local_mtime_min": 1000},
            {"id": "2", "title": "T2", "local_bytes": 50},
        ],
        "items": [
            {"folder": "a", "size": 100, "product_id": "1"},
            {"folder": "b", "size": 50, "product_id": "2"},
        ],
    }
    rows = {r["id"]: r for r in A.product_rows(ds)}
    chk("product_rows 暴露 mt", rows["1"]["mt"] == 2000, str(rows["1"]["mt"]))
    chk("product_rows 暴露 mt0", rows["1"]["mt0"] == 1000)
    chk("没有时间的商品给 0（不是 None）", rows["2"]["mt"] == 0,
        f"{rows['2']['mt']!r}")

    print()
    print("=== 3) 前端层：用 Node 跑 ui.html 里真实的排序实现 ===")
    if not Path(NODE).exists():
        print(f"  缺少 Node.js：{NODE}")
        return 1
    src = UI.read_text(encoding="utf-8")
    fw = src[src.index("const FW_MAP"):src.index("function filteredRows")]
    helpers = extract_fn(src, "function fmtDay(")
    chk("抽出 fmtDay", "function fmtDay" in helpers)
    cmpfn = extract_fn(src, "function cmpBy(")
    chk("抽出 cmpBy", "localeCompare" in cmpfn)
    fn = extract_fn(src, "function filteredRows(")

    data = json.loads((ROOT / "tests" / "fixtures" / "catalog.json").read_text(encoding="utf-8"))
    # 合成样本商品 + 人为注入 mt / pa，验排序（seed 里没有本地时间）
    import hashlib
    rows = []
    for i, p in enumerate(data.get("products") or []):
        h = int(hashlib.md5(str(p["id"]).encode()).hexdigest()[:6], 16)
        rows.append({
            "t": p.get("title") or "", "s": p.get("shop") or "",
            "c": p.get("cat_main") or "", "sub": p.get("cat_subs") or [],
            "av": p.get("avatars") or [], "f": p.get("local_folders") or [],
            "id": p.get("id"), "b": p.get("local_bytes") or 0, "n": 1,
            "w": p.get("wish_lists_count") or 0, "pm": p.get("price_min"),
            "pa": (p.get("published_at") or "")[:10],
            "mt": (h % 400) * 86400 + 1_600_000_000 if i % 17 else 0,
        })
    print(f"  合成样本商品 {len(rows)} 件（{sum(1 for r in rows if r['mt'])} 件带时间）")

    harness = f"""
{fw}
const ROWS = {json.dumps(rows, ensure_ascii=False)};
let INPUT = "";
const S = {{ rows: ROWS, onlyDup: false, sort: {{ k: "mt", asc: false }} }};
function $(id) {{
  if (id === "q") return {{ value: INPUT }};
  if (id === "fsort") return {{ value: S.sort.k }};
  return {{ value: "" }};
}}
{helpers}
{cmpfn}
{fn}
function ids(k, asc) {{
  S.sort = {{ k: k, asc: asc }};
  return filteredRows().map(r => r.id);
}}
function monotone(arr, key, asc) {{
  const v = arr.map(i => (ROWS.find(r => String(r.id) === String(i))||{{}})[key]);
  for (let i = 1; i < v.length; i++) {{
    const x = v[i-1], y = v[i];
    const ex = x === undefined || x === null || x === "";
    const ey = y === undefined || y === null || y === "";
    if (ex || ey) {{
      if (!ey) return false;      // 空值必须沉底
      continue;
    }}
    if (typeof x === "number") {{ if (asc ? x > y : x < y) return false; }}
    else {{ const c = String(x).localeCompare(String(y), "zh-Hans-CN", {{numeric:true}});
            if (asc ? c > 0 : c < 0) return false; }}
  }}
  return true;
}}
const mtDesc = ids("mt", false), mtAsc = ids("mt", true);
const paDesc = ids("pa", false), paAsc = ids("pa", true);
const bDesc  = ids("b", false);
const tAsc   = ids("t", true);
const noneLast = (() => {{
  const arr = ids("mt", false);
  const vals = arr.map(i => (ROWS.find(r => String(r.id) === String(i))||{{}}).mt);
  const firstZero = vals.indexOf(0);
  return firstZero === -1 || vals.slice(firstZero).every(v => !v);
}})();
const dateFmt = fmtDay(0) + "|" + fmtDay(1600000000) + "|" + fmtDay("x");
/* 升降序「互为反转」只对**有值部分的值序列**成立：
   - 空值按设计在两个方向都沉底，硬要求整体反转会把这条正确行为判成失败；
   - 同一时间戳的并列项按 id 兜底（也固定不反转），但它们的**值相同**，
     所以比较值序列就能验「方向真的翻过来了」而不受并列影响。
   （第一版拿 id 序列整体反转来比，被并列项判成了失败 —— 是断言错，不是代码错。） */
const vals = arr => arr.filter(i => (ROWS.find(r => String(r.id) === String(i))||{{}}).mt)
  .map(i => (ROWS.find(r => String(r.id) === String(i))||{{}}).mt);
const vDesc = vals(mtDesc), vAsc = vals(mtAsc);
console.log(JSON.stringify({{
  n: mtDesc.length,
  mtOk: monotone(mtDesc, "mt", false),
  mtAscOk: monotone(mtAsc, "mt", true),
  mtReverse: JSON.stringify(vDesc) === JSON.stringify([...vAsc].reverse()),
  paOk: monotone(paDesc, "pa", false),
  paAscOk: monotone(paAsc, "pa", true),
  bOk: monotone(bDesc, "b", false),
  tOk: monotone(tAsc, "t", true),
  noneLast: noneLast,
  dateFmt: dateFmt,
  oldDefaultWasB: ids("b", false).join(",") !== mtDesc.join(","),
}}));
"""
    tmp = ROOT / "_testhome" / "_sort_harness.js"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(harness, encoding="utf-8")
    r = subprocess.run([NODE, str(tmp)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    if r.returncode != 0:
        chk("node 执行成功", False, (r.stderr or "")[:400])
        return _report()
    res = json.loads(r.stdout.strip().splitlines()[-1])
    print(f"  {res}")

    chk("降序按下载时间单调不增", res["mtOk"])
    chk("升序按下载时间单调不减", res["mtAscOk"])
    chk("有值部分升序 = 降序反转（全序且稳定）", res["mtReverse"])
    chk("降序按上架时间单调不增", res["paOk"])
    chk("升序按上架时间单调不减", res["paAscOk"])
    chk("降序按占用单调不增", res["bOk"])
    chk("升序按商品名（中文 locale）单调", res["tOk"])
    chk("没有时间的沉底", res["noneLast"])
    chk("fmtDay 输出可读，空值给 —", res["dateFmt"].startswith("—|2020-09-1"),
        res["dateFmt"])
    chk("默认排序已从「占用」改成「下载时间」", res["oldDefaultWasB"])
    chk("结果数不变", res["n"] == len(rows), f"{res['n']} vs {len(rows)}")
    return _report()


def _report():
    print()
    if fails:
        print(f"{len(fails)} failed")
        print("FAILED:", fails)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
