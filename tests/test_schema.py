# SPDX-License-Identifier: GPL-3.0-only
"""回归测试：schema 迁移 + 文件系统容错。

这两个模块都是**踩实过的缺陷**的修复，用例直接对应故障现象：

  1. dataset schema 漂移（bytes vs size）会让统计**静默归零**。
     实测：旧 schema 经 A.summarize() 得到 totBytes=0.00 GB，
     而同一份数据实际是 500.77 GB。必须保证迁移后不再归零。
  2. Path.is_dir() 在网络盘断开/无权限时**抛 PermissionError** 而非返回 False。
     实测 X:\\、Z:\\、\\\\nas.example\\... 全部抛异常，导致 set_root 崩、扫盘崩。

用法：python tests/test_schema.py
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from boothlib import analytics as A      # noqa: E402
from boothlib import fsutil as F         # noqa: E402
from boothlib import migrate as MIG      # noqa: E402

fails = []


def chk(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- 样本
OLD = {
    "root": "X:\\下载",
    "products": [{"id": "1", "title": "T", "local_bytes": 300}],
    "items": [
        {"folder": "a", "name": "a", "bytes": 300, "n_files": 2,
         "ids": ["1234567"], "product_id": "1", "confidence": "高"},
        {"folder": "b", "name": "b", "bytes": 200, "n_files": 1,
         "ids": [], "product_id": None, "confidence": None},
    ],
}

NEW = {
    "schema": 2,
    "root": "X:\\下载",
    "products": [{"id": "1", "title": "T", "local_bytes": 300}],
    "items": [
        {"folder": "a", "name": "a", "size": 300, "n_files": 2,
         "ids_strong": ["1234567"], "product_id": "1", "confidence": "高"},
        {"folder": "b", "name": "b", "size": 200, "n_files": 1,
         "ids_strong": [], "product_id": None, "confidence": None},
    ],
    "totItems": 2, "totProds": 1, "totBytes": 500, "totFiles": 3,
    "identified": 1,
}


def main():
    print("=== detect_version ===")
    chk("旧 schema → 1", MIG.detect_version(OLD) == 1)
    chk("新 schema → 2", MIG.detect_version(NEW) == 2)
    chk("空 dict → 0", MIG.detect_version({}) == 0)
    chk("非 dict → 0", MIG.detect_version(None) == 0)
    chk("items 空但有 totItems → 2",
        MIG.detect_version({"items": [], "totItems": 0}) == 2)

    print()
    print("=== migrate：旧 → 新 ===")
    before = copy.deepcopy(OLD)
    ds, rep = MIG.migrate(OLD)
    chk("报告 from=1 to=2", rep["from"] == 1 and rep["to"] == 2)
    chk("报告 changed=True", rep["changed"] is True)
    chk("标记 schema=2", ds.get("schema") == 2)
    chk("item 有 size", ds["items"][0]["size"] == 300)
    chk("item 保留 bytes 镜像", ds["items"][0]["bytes"] == 300)
    chk("ids → ids_strong", ds["items"][0]["ids_strong"] == ["1234567"])
    chk("补 ids_weak", ds["items"][0]["ids_weak"] == [])
    chk("顶层汇总重算 totBytes", ds["totBytes"] == 500, f"={ds['totBytes']}")
    chk("顶层汇总重算 totItems", ds["totItems"] == 2)
    chk("顶层汇总重算 totFiles", ds["totFiles"] == 3)
    chk("顶层汇总重算 identified", ds["identified"] == 1)

    print()
    print("=== 迁移不改动入参（默认非就地）===")
    chk("入参未被污染（无 size）", "size" not in before["items"][0])
    chk("入参未被污染（无 schema）", "schema" not in before)
    chk("入参 ids 仍在", before["items"][0]["ids"] == ["1234567"])

    print()
    print("=== 幂等：迁移两次结果一致 ===")
    ds2, rep2 = MIG.migrate(ds)
    chk("第二次 changed=False", rep2["changed"] is False, str(rep2["actions"]))
    chk("totBytes 不变", ds2["totBytes"] == ds["totBytes"])

    print()
    print("=== 新 schema 不被改动 ===")
    ds3, rep3 = MIG.migrate(NEW)
    chk("changed=False", rep3["changed"] is False)
    chk("size 保持", ds3["items"][0]["size"] == 300)

    print()
    print("=== 核心回归：不再静默归零 ===")
    s_old = A.summarize(MIG.migrate(OLD)[0])
    chk("旧数据迁移后 totBytes>0", s_old["totBytes"] == 500,
        f"={s_old['totBytes']}")
    # 复现原始故障：未迁移时确实归零（证明这个测试是有意义的）
    s_raw = A.summarize(OLD)
    chk("未迁移时也读到 bytes（纵深防御）", s_raw["totBytes"] == 0,
        f"={s_raw['totBytes']} ← 这正是要防的静默归零")

    print()
    print("=== _size_of 双 schema 兼容 ===")
    chk("size 优先", A._size_of({"size": 7, "bytes": 9}) == 7)
    chk("回退 bytes", A._size_of({"bytes": 9}) == 9)
    chk("都没有 → 0", A._size_of({}) == 0)
    chk("None → 0", A._size_of({"size": None}) == 0)
    chk("脏值 → 0", A._size_of({"size": "abc"}) == 0)
    chk("非 dict → 0", A._size_of(None) == 0)

    print()
    print("=== 重复下载的可回收量也算得出来 ===")
    dup = {
        "products": [{"id": "1", "title": "T"}],
        "items": [
            {"folder": "a", "size": 300, "product_id": "1"},
            {"folder": "a2", "size": 100, "product_id": "1"},
        ],
    }
    sd = A.summarize(dup)
    chk("识别出 1 组重复", len(sd["dups"]) == 1)
    chk("可回收 = 较小的那份", sd["wasteTotal"] == 100, f"={sd['wasteTotal']}")
    dup_old = {"products": [{"id": "1", "title": "T"}],
               "items": [{"folder": "a", "bytes": 300, "product_id": "1"},
                         {"folder": "a2", "bytes": 100, "product_id": "1"}]}
    chk("旧 schema 重复也能算", A.summarize(dup_old)["wasteTotal"] == 100)

    print()
    print("=== fsutil：探测函数永不抛异常（真正的契约）===")
    # ★ 断言只写「不抛异常」，不写「必定返回 False」。
    #   早期版本断言 X:\ 不可访问 —— 那依赖运行环境（第一次是在 DSH 沙箱里
    #   被拒，后来放开权限后 X:\ 就能正常列目录了，测试于是开始误报）。
    #   可访问与不可访问**都是合法结果**，唯一必须成立的是「不崩」。
    probes = [("X:\\", "网络盘 X:"), ("Z:\\", "网络盘 Z:"),
              (str(ROOT / "__missing_share__"), "不存在的网络共享"),
              (str(ROOT / "__definitely_not_here__" / "x"), "不存在的本地路径"),
              ("", "空字符串"), ("::::", "非法路径串")]
    for p, label in probes:
        try:
            r = F.is_dir_safe(p)
            ok = isinstance(r, bool)
        except Exception as e:                          # noqa: BLE001
            ok, r = False, f"RAISED {type(e).__name__}"
        chk(f"is_dir_safe 不抛: {label}", ok, f"→ {r}")

    # 确认不存在的本地路径确实返回 False（这条与环境无关）
    chk("不存在的本地目录 → False",
        F.is_dir_safe(str(ROOT / "__definitely_not_here__" / "x")) is False)
    chk("不存在的网络共享 → False",
        F.is_dir_safe(str(ROOT / "__missing_share__")) is False)
    try:
        chk("exists_safe 不抛（不存在 → False）",
            F.exists_safe(str(ROOT / "__definitely_not_here__" / "x")) is False)
        chk("listdir_safe 不抛（不存在 → [])",
            F.listdir_safe(str(ROOT / "__definitely_not_here__" / "x")) == [])
        chk("stat_safe 不抛（不存在 → None）",
            F.stat_safe(str(ROOT / "__definitely_not_here__" / "x")) is None)
    except Exception as e:                              # noqa: BLE001
        chk(f"其余 safe 函数不抛（{type(e).__name__}）", False)

    print()
    print("=== fsutil：正常路径仍然工作 ===")
    chk("工程根目录可访问", F.is_dir_safe(ROOT))
    chk("ROOT/README.md 是文件", F.is_file_safe(ROOT / "README.md"))
    chk("ROOT 下能列出条目", len(F.listdir_safe(ROOT)) > 0)

    print()
    print("=== 错误文案可读（会提示网络盘）===")
    # 动态挑一个**当前没被占用**的盘符，避免把测试绑定到本机映射表
    used = {d[0].upper() for d in
            (str(Path.cwd())[:2], "C:", "D:", "E:", "F:", "G:", "H:",
             "X:", "Y:", "Z:")}
    free = next(f"{c}:\\" for c in "QRSTUVW" if c + ":" not in used)
    msg = F.describe_access_error(free + "下载")
    chk("提到无法访问", "无法访问" in msg, f"[{free}] {msg}")
    chk("提到网络/映射", ("网络" in msg or "映射" in msg), msg)
    msg2 = F.describe_access_error(str(ROOT / "__definitely_not_here__" / "x"))
    chk("不存在的本地路径说「不存在」", "不存在" in msg2, msg2)

    print()
    print("=== scanner 对不可访问根给出可读错误 ===")
    from boothlib.scanner import scan
    try:
        scan(free + "下载")
        chk("scan 不可访问根应报错", False, "却成功了")
    except FileNotFoundError as e:
        chk("scan 抛 FileNotFoundError（非 PermissionError）", True, str(e)[:70])
    except Exception as e:                              # noqa: BLE001
        chk("scan 抛 FileNotFoundError（非 PermissionError）", False,
            f"实际 {type(e).__name__}: {e}")

    print()
    print(f"{len(fails)} failed" if fails else "ALL PASS")
    if fails:
        print("FAILED:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
