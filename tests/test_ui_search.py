# SPDX-License-Identifier: GPL-3.0-only
"""用 Node 跑 ui.html 里**真实的**搜索代码，对合成 dataset 做全角/半角验收。

为什么不靠 CDP：本机沙箱里 headless 浏览器的 CDP WebSocket 会被重置
（tests/test_ui_export.py 对照组同样失败）。但搜索逻辑是纯函数，
可以从 ui.html 里**原样抽出来**在 Node 里跑 —— 测的是真正上线的那份代码，
不是重写一份抄本。

用法：python tests/test_ui_search.js_run.py
"""
import json
import re
import shutil
import subprocess
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UI = ROOT / "boothlib" / "ui.html"
DATA = ROOT / "tests" / "fixtures" / "catalog.json"
NODE = os.environ.get("NODE_BINARY") or shutil.which("node") or "node"

fails = []


def chk(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        fails.append(name)


def extract_fn(src: str, header: str) -> str:
    """按大括号配对，从 ui.html 里原样抽出整个函数（含函数体）。

    不用正则非贪婪匹配：`.*?` 会在 `.join(" ")` 的右括号处提前截断，
    抽出来的是残句（第一次尝试就是这么失败的）。
    """
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
    raise ValueError(f"没找到 {header} 的结尾")


def main():
    if not Path(NODE).exists():
        print(f"缺少 Node.js：{NODE}")
        return 1
    src = UI.read_text(encoding="utf-8")

    # ---- 从 ui.html 原样抽出真实的搜索实现 ----
    print("=== 从 ui.html 抽取真实搜索代码 ===")
    fw = src[src.index("const FW_MAP"):src.index("function filteredRows")]
    chk("抽到 FW_MAP/foldWidth/normQ", "function foldWidth" in fw
        and "function normQ" in fw, f"{len(fw)} chars")
    fn = extract_fn(src, "function filteredRows(")
    chk("整函数抽出（括号配平）",
        fn.count("{") == fn.count("}") and "normQ" in fn,
        f"{len(fn)} chars, {{={fn.count('{')} }}={fn.count('}')}")

    data = json.loads(DATA.read_text(encoding="utf-8"))
    rows = []
    for p in data.get("products") or []:
        rows.append({
            "t": p.get("title") or "", "s": p.get("shop") or "",
            "c": p.get("cat_main") or "", "sub": p.get("cat_subs") or [],
            "av": p.get("avatars") or [], "f": p.get("local_folders") or [],
            "id": p.get("id"), "b": p.get("local_bytes") or 0, "n": 1,
        })
    print(f"  合成样本商品 {len(rows)} 件")

    # 用真实 filteredRows，只把 DOM/状态桩掉
    harness = f"""
{fw}
const ROWS = {json.dumps(rows, ensure_ascii=False)};
let INPUT = "";
const S = {{ rows: ROWS, onlyDup: false, sort: {{ k: "b", asc: false }} }};
function $(id) {{
  if (id === "q") return {{ value: INPUT }};
  return {{ value: "" }};      // fcat / fshop 都不筛选
}}
{fn}
function run(qRaw) {{ INPUT = String(qRaw); return filteredRows().length; }}
console.log(JSON.stringify({{
  fw21: run("\\uff12\\uff11"), hw21: run("21"),
  fw8: run("\\uff18"), hw8: run("8"),
  shinano: run("Shinano"),
  all: run(""),
  upper: run("SHINANO"), lower: run("shinano"),
}}));
"""
    tmp = ROOT / "_testhome" / "_search_harness.js"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(harness, encoding="utf-8")

    print()
    print("=== Node 跑真实搜索代码 ===")
    r = subprocess.run([NODE, str(tmp)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    if r.returncode != 0:
        chk("node 执行成功", False, (r.stderr or "")[:300])
        return _report()
    res = json.loads(r.stdout.strip().splitlines()[-1])
    print(f"  {res}")

    chk("全角「２１」有命中", res["fw21"] > 0, f"={res['fw21']}")
    chk("全角「２１」= 半角「21」", res["fw21"] == res["hw21"],
        f"{res['fw21']} vs {res['hw21']}")
    chk("全角「８」= 半角「8」", res["fw8"] == res["hw8"],
        f"{res['fw8']} vs {res['hw8']}")
    chk("大小写不敏感", res["upper"] == res["lower"],
        f"{res['upper']} vs {res['lower']}")
    chk("Shinano 有结果", res["shinano"] > 0, f"={res['shinano']}")
    chk("空查询 = 全量", res["all"] == len(rows), f"={res['all']}")

    # 复现修复前的行为做对照：只用 toLowerCase 会漏掉全角
    legacy = f"""
const ROWS = {json.dumps(rows, ensure_ascii=False)};
function runOld(qRaw) {{
  const q = String(qRaw).trim().toLowerCase();
  return ROWS.filter(p => !q || (p.t+" "+p.s+" "+p.c+" "+p.sub.join(" ")+" "+p.av.join(" ")+" "+p.f.join(" "))
    .toLowerCase().includes(q)).length;
}}
console.log(JSON.stringify({{ fw21: runOld("\\uff12\\uff11"), hw21: runOld("21") }}));
"""
    tmp.write_text(legacy, encoding="utf-8")
    r2 = subprocess.run([NODE, str(tmp)], capture_output=True, text=True,
                        encoding="utf-8", timeout=120)
    if r2.returncode == 0:
        old = json.loads(r2.stdout.strip().splitlines()[-1])
        print()
        print(f"  修复前（纯 toLowerCase）: 全角={old['fw21']} 半角={old['hw21']}")
        chk("已确认修复前全角搜不到（证明改动有意义）",
            old["fw21"] != old["hw21"] or old["fw21"] == 0,
            f"旧: 全角={old['fw21']} 半角={old['hw21']}")
    shutil.rmtree(tmp.parent / "_search_harness.js", ignore_errors=True)
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
