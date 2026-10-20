# SPDX-License-Identifier: GPL-3.0-only
"""把 ui.html 里的 <script> 抽出来交给 node --check 做语法检查。

★ 为什么需要：ui.html 是单文件、没有构建步骤，语法错一行整个界面白屏，
   而服务端只会返回 200 让页面自己静默失败。node --check 是最便宜的门禁。

用法：python tests/_check_ui_syntax.py
"""
import re
import shutil
import subprocess
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "boothlib" / "ui.html"
NODE = os.environ.get("NODE_BINARY") or shutil.which("node") or "node"


def main():
    src = UI.read_text(encoding="utf-8")
    m = re.search(r"<script>(.*)</script>", src, re.S)
    if not m:
        print("没找到 <script>")
        return 1
    js = m.group(1)
    tmp = ROOT / "_testhome" / "_ui_check.js"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(js, encoding="utf-8")

    # 1) 语法
    r = subprocess.run([NODE, "--check", str(tmp)], capture_output=True,
                       text=True, encoding="utf-8")
    ok_syntax = r.returncode == 0
    print(f"[{'PASS' if ok_syntax else 'FAIL'}] node --check 语法 ({len(js)} chars)")
    if not ok_syntax:
        print((r.stderr or "")[:1500])
        return 1

    # 2) 关键标识符都在（防"改了 HTML 忘了加 JS 绑定"）
    need = ["fsort", "fsortDir", "mtNote", "dq", "dcount", "cmpBy",
            "fmtDay", "initSortUI", "applySort", "syncSortUI", "SORT_OPTS"]
    missing = [k for k in need if k not in js]
    print(f"[{'PASS' if not missing else 'FAIL'}] 关键绑定齐全 "
          f"{'缺 ' + str(missing) if missing else ''}")
    # 3) 所有 $("xxx") 引用的 id 都必须真的存在于 HTML 里
    ids = set(re.findall(r'\$\("([A-Za-z0-9_\-]+)"\)', js))
    dom = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', src))
    ghosts = sorted(i for i in ids if i not in dom)
    print(f"[{'PASS' if not ghosts else 'FAIL'}] $() 引用的 id 都存在 "
          f"{'幽灵 id: ' + str(ghosts) if ghosts else f'({len(ids)} 个)'}")
    return 0 if not missing and not ghosts else 1


if __name__ == "__main__":
    sys.exit(main())
