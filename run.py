# SPDX-License-Identifier: GPL-3.0-only
"""桌面版启动入口（PyInstaller 的入口脚本）。

为什么需要这个文件：
    PyInstaller 会把入口脚本作为 `__main__` 顶层模块执行，此时它**不属于任何包**，
    于是 app.py 里的 `from .api import Api` 这类相对导入会直接报
    "attempted relative import with no known parent package"。
    所以入口放在包外，用绝对导入调用 boothlib.app.main()。

另外：打包成 GUI（console=False）后 stdout/stderr 不可见，
任何早期异常都表现为「双击没反应」。这里在最开头就写一行 trace，
方便定位「到底有没有进到 Python」。
"""
import os
import sys
import traceback
from pathlib import Path


def _trace(msg: str) -> None:
    """把启动痕迹写到 exe 同级目录（那里必定可写），失败就退到 TEMP。

    注意：早期版本写到 %TEMP%/BoothNest，但**连正常工作的情况也写不出来**，
    导致我误判成「Python 没跑起来」。所以现在优先写 exe 旁边的
    `_startup.log`，并且先测一次写权限。
    """
    if not os.environ.get("BOOTH_NEST_DEBUG"):
        return
    import datetime
    line = (f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    cands = []
    try:
        cands.append(Path(sys.executable).parent / "_startup.log")
    except Exception:
        pass
    try:
        cands.append(Path(os.environ.get("TEMP", ".")) / "booth_startup.log")
    except Exception:
        pass
    for fp in cands:
        try:
            with open(fp, "a", encoding="utf-8") as f:
                f.write(line)
            return
        except Exception:
            continue


_trace(f"run.py 启动 frozen={getattr(sys, 'frozen', False)} "
       f"exe={sys.executable} argv={sys.argv[:2]}")
_trace(f"sys.path[:3]={sys.path[:3]}")
_trace(f"_MEIPASS={getattr(sys, '_MEIPASS', None)}")

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from boothlib.app import main            # noqa: E402
    _trace("import boothlib.app OK")
except Exception:
    _trace("import FAILED:\n" + traceback.format_exc())
    raise

if __name__ == "__main__":
    try:
        rc = main()
        _trace(f"main() returned {rc}")
    except SystemExit as e:
        _trace(f"SystemExit {e.code}")
        raise
    except Exception:
        _trace("main() raised:\n" + traceback.format_exc())
        raise
    sys.exit(rc)
