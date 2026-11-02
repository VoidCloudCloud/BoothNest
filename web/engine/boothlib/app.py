# SPDX-License-Identifier: GPL-3.0-only
"""BoothNest 桌面版入口。

窗口方案：**内置 HTTP 服务 + Edge/Chrome 的 --app 模式**。

为什么不用 pywebview：
    它依赖 pythonnet/.NET，PyInstaller 冻结后 Python.Runtime.dll 无法解析入口点
    （RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize），
    给 pythonnet 写 hook 很脆。改用系统自带的 Edge（Chromium），
    只用标准库 + 现成的浏览器运行时，打包后最稳。

用法：
    python run.py          # 源码运行
    BoothNest.exe        # 打包后
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

BROWSER_CANDIDATES = [
    # Edge（Windows 自带，优先）
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
    # Chrome 兜底
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
]


def resource_dir() -> Path:
    """界面文件所在目录。

    打包后（PyInstaller onedir）资源解包到 `_internal/`，ui.html 放在
    `_internal/assets/`。

    ★ 必须用 "assets" 这种**不与包同名**的目录：若把 datas 放进 `boothlib/`，
    PyInstaller 会建一个纯数据目录 `_internal/boothlib/`，它**遮蔽真正的
    boothlib 包**，于是 `from boothlib.app import main` 在任何代码执行前就失败
    —— 表现为 exe 秒退、无输出、无 traceback、连日志都写不出来。
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for cand in (base / "assets", base / "boothlib", base):
            if (cand / "ui.html").exists():
                return cand
        return base
    return Path(__file__).resolve().parent


def find_browser() -> str | None:
    for pat in BROWSER_CANDIDATES:
        p = Path(os.path.expandvars(pat))
        if p.is_file():
            return str(p)
    return None


def crash_log(msg: str) -> Path | None:
    """把错误写到日志文件；连日志都写不了就退到 TEMP。

    注意：打包成 GUI（console=False）后 stdout/stderr 不可见，
    任何异常都必须落盘，否则表现为「双击没反应」。
    """
    for base in ("home", "temp"):
        try:
            if base == "home":
                from .config import Config
                d = Config().log_dir
            else:
                d = Path(os.environ.get("TEMP", ".")) / "BoothNest"
            d.mkdir(parents=True, exist_ok=True)
            fp = d / "crash.log"
            fp.write_text(msg, encoding="utf-8")
            return fp
        except Exception:
            continue
    return None


def _message_box(title: str, text: str) -> None:
    """没有浏览器可用时，至少让用户看到原因。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        print(f"{title}: {text}", file=sys.stderr)


def _writable_dir(p: Path, tries: int = 3) -> bool:
    """确认目录真的可写（能建文件并删除）。

    带重试：目录被上一次被强杀的浏览器短暂占用时会瞬时返回 WinError 5，
    隔一会儿就好了 —— 一次失败就放弃会误判成「永久不可写」。
    """
    for i in range(tries):
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".writable"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except Exception as e:
            if i == tries - 1:
                _trace(f"_writable_dir({p}) failed x{tries}: "
                       f"{type(e).__name__}: {e}")
            else:
                time.sleep(0.8)
    return False


def _profile_dir(home: Path) -> Path | None:
    """找一个**确实可写**的浏览器 profile 目录；都不可用则返回 None。

    ★ 目录名刻意避开 "browser-profile"/"User Data" 这类浏览器配置目录特征：
      火绒等 HIPS 会把「创建浏览器配置目录」当成凭据窃取行为拦截
      （实测返回 WinError 5，且 mkdir 成功、只有**新建文件**被拒）。

    ★ 返回前必须保证目录已创建：Edge 遇到不存在的 --user-data-dir 会
      直接以 exit code 21 退出，现象是「程序活着但一个窗口都没有」。

    ★ 这个 profile 必须是**独立**的，不能退回 Edge 默认配置：
      用户 Edge 若登录了 Microsoft 账号，用默认配置启动会弹出
      「正在同步你的浏览数据」白底大对话框，把界面整个盖住
      （用户报的"打开什么都没显示"就是它）。

    依次尝试：数据目录下 → %TEMP%。全都不可写才返回 None。
    """
    # 允许用环境变量指定 profile（自动化测试用：多个实例共用同一个
    # --user-data-dir 时，后启动的那个**建不出 renderer**，
    # 会把测试自身的干扰误判成产品问题）。
    override = os.environ.get("BOOTH_NEST_PROFILE")
    if override:
        # ★ 必须 resolve()：如果传进来的是相对路径，Edge 会以「exe 的工作目录」
        #   为基准去解析 --user-data-dir，而工作目录未必是项目目录 ——
        #   结果 Edge 拿到一个不存在的路径，直接退出（exit 21），
        #   日志里只看到 "window appeared=False"，非常难查。
        p = Path(override).resolve()
        if _writable_dir(p):
            return p
        raise RuntimeError(
            f"BOOTH_NEST_PROFILE 指定的目录不可写：{p}\n"
            "请换一个可写目录，或清掉该环境变量。")

    try:
        home.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    cands = [home / n for n in (".wvdata", "wvdata", "wvprofile", "profile")]
    tmp = Path(os.environ.get("TEMP", "."))
    cands.append(tmp / "BoothNest" / "wvdata")
    cands.append(tmp / f"bs-{os.getpid()}")
    cands.append(tmp / "BoothNest-Profile")
    for p in cands:
        if _writable_dir(p):
            return p
    return None


def _trace(msg: str) -> None:
    """启动诊断日志：仅在设置了 BOOTH_NEST_DEBUG 时才写。

    打包成 GUI 后没有 stdout，出问题时需要落盘才查得动；但正常使用不该在
    exe 旁边留日志文件，所以默认关闭，排查时设环境变量即可：
        set BOOTH_NEST_DEBUG=1
    """
    if not os.environ.get("BOOTH_NEST_DEBUG"):
        return
    try:
        import datetime
        fp = Path(sys.executable).parent / "_startup.log"
        with open(fp, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}"
                    f" {msg}\n")
    except Exception:
        pass


def current_integrity() -> str | None:
    """读**本进程**的完整性级别（Low / Medium / High …），失败返回 None。

    为什么要读它：DSH 给工作区目录打了低完整性标签
        Mandatory Label\\Low Mandatory Level:(OI)(CI)(NW)
    因为带 (OI)(CI) 继承，在工作区里生成的 exe 也带该标签。
    低完整性进程被视为不可信，Chromium 于是**不创建 renderer 子进程**，
    页面永远不渲染 = 白屏（详见 README 第五节）。

    这比「猜 exe 的路径里有没有 default-workspace / boothlibrary」可靠得多：
    路径判断在用户把项目改名或换个位置时就会误报或漏报，
    而完整性级别是**导致白屏的那个真实条件本身**。

    ⚠ ctypes 必须显式声明 argtypes/restype：
      不声明时 HANDLE 会被按 32 位 int 处理，在 64 位下
      OpenProcessToken 直接失败（踩过：一直返回 "OpenProcessToken 失败"）。
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        adv = ctypes.WinDLL("advapi32", use_last_error=True)

        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.HANDLE)]
        adv.OpenProcessToken.restype = wintypes.BOOL
        adv.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD)]
        adv.GetTokenInformation.restype = wintypes.BOOL
        adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

        TOKEN_QUERY = 0x0008
        TokenIntegrityLevel = 25

        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p),
                        ("Attributes", wintypes.DWORD)]

        class TOKEN_MANDATORY_LABEL(ctypes.Structure):
            _fields_ = [("Label", SID_AND_ATTRIBUTES)]

        tok = wintypes.HANDLE()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_QUERY,
                                   ctypes.byref(tok)):
            return None
        try:
            need = wintypes.DWORD(0)
            adv.GetTokenInformation(tok, TokenIntegrityLevel, None, 0,
                                    ctypes.byref(need))
            buf = ctypes.create_string_buffer(need.value)
            if not adv.GetTokenInformation(tok, TokenIntegrityLevel, buf,
                                           need.value, ctypes.byref(need)):
                return None
            lbl = ctypes.cast(buf,
                              ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
            cnt = adv.GetSidSubAuthorityCount(lbl.Label.Sid).contents.value
            rid = adv.GetSidSubAuthority(lbl.Label.Sid, cnt - 1).contents.value
        finally:
            k32.CloseHandle(tok)

        return {0x0000: "Untrusted", 0x1000: "Low", 0x2000: "Medium",
                0x2100: "MediumPlus", 0x3000: "High",
                0x4000: "System"}.get(rid, f"0x{rid:04X}")
    except Exception:
        return None


def _check_location(step) -> None:
    """若程序处于「会让 Chromium 白屏」的状态，明确提示用户。

    判据优先用**本进程的完整性级别**（低完整性 = 必然白屏，见
    current_integrity 的注释）；读不到才退回路径猜测。

    ★ 只提示、不拦截：白屏时用户什么都看不到，
      能用一行文字告诉他原因和办法，就已经胜过对着空白窗口猜。
    """
    if not getattr(sys, "frozen", False):
        return

    il = current_integrity()
    exe = Path(sys.executable).resolve()
    risky_path = il is None and ("\\default-workspace\\" in str(exe).lower()
                                or "\\boothlibrary\\" in str(exe).lower())
    if il != "Low" and not risky_path:
        return

    step(f"WARNING: 可能导致白屏（integrity={il} path_risky={risky_path}）")
    _message_box(
        "BoothNest — 建议换个位置运行",
        "当前程序运行在受限状态，实测该状态会导致浏览器无法渲染界面"
        "（窗口出来了但整片空白）。\n\n"
        "原因：本程序所在目录带有「低完整性」标记，Chromium 因此不会"
        "创建渲染进程。\n\n"
        "解决办法：运行同目录下的「安装.cmd」，\n"
        "它会装到你的用户目录并建桌面快捷方式。\n\n"
        "（项目源码可以留在原处，只有 exe 需要移出工作区。）\n\n"
        f"当前完整性级别：{il}\n"
        f"当前位置：\n{exe.parent}")


def main() -> int:
    from .api import Api
    from .config import Config
    from .instance import InstanceLock
    from .server import make_server

    def step(msg: str) -> None:
        """分步痕迹。打包后无 stdout，卡在哪一步只能靠这个。"""
        _trace(f"[main] {msg}")

    instance = None
    try:
        step("enter main")
        _check_location(step)
        cfg = Config().load()
        cfg.ensure_dirs()
        instance = InstanceLock(cfg.home)
        if not instance.acquire():
            _message_box("BoothNest", "程序已经在运行，请切换到已有窗口。")
            return 0
        api = Api(cfg, exit_handler=lambda: os._exit(0))
        step("Api() ok")
        api.cfg.ensure_dirs()
        step("ensure_dirs ok")
        ui_dir = resource_dir()
        step(f"resource_dir={ui_dir}")
        if not (ui_dir / "ui.html").exists():
            raise FileNotFoundError(f"找不到界面文件 ui.html（查找目录：{ui_dir}）")

        srv, url = make_server(api, ui_dir)
        step(f"server ok {url}")
        browser = find_browser()
        step(f"browser={browser}")
        profile = _profile_dir(api.cfg.home)
        step(f"profile={profile}")

        if browser:
            common = [
                browser,
                f"--app={url}",
                "--no-first-run",
                "--no-default-browser-check",
                # 抑制首次运行/同步/默认浏览器等所有引导弹窗。
                # ★ 这条是必须的：曾经降级用「默认 profile」启动，而用户 Edge
                #   登录了 Microsoft 账号，于是弹出一个白底大对话框
                #   「我们现在正在你的所有设备上同步你的浏览数据」，
                #   把它后面的应用界面整个盖住 —— 用户看到的就是"打开什么都没显示"。
                "--disable-features=Translate,TranslateUI,"
                "msEdgeIdentityFeature,EdgeSync,msImplicitSignin",
                "--disable-sync",
                # ★ 不要加 --disable-background-networking。
                #   它会阻断 Chromium 的内部网络服务初始化，导致**不创建
                #   renderer 进程** —— 现象：窗口出来、标题停在 URL、整片纯白，
                #   而且服务端访问日志里 0 条请求（浏览器压根没去取页面）。
                #   实测进程树里只有 browser + gpu-process + utility，
                #   缺 renderer 就是它。
                "--window-size=1480,940",
                "--disable-extensions",
            ]
            # 排查用：BOOTH_NEST_CDP_PORT 会让浏览器开 CDP 端口，
            # 这样验证工具能连进去确认真实渲染结果（截图会被别的窗口遮挡，
            # PrintWindow 对 Chromium 又永远是白图，都不足为凭）。
            cdp = os.environ.get("BOOTH_NEST_CDP_PORT")
            if cdp:
                common += [f"--remote-debugging-port={cdp}",
                           "--remote-allow-origins=*"]

            # ★ 不要给浏览器加 CREATE_NO_WINDOW：
            #   msedge 是 GUI 程序，带上该标志（继承自无控制台的打包父进程）时
            #   它会在建窗口前就退出 —— 现象是 Popen 成功、pid 也有，但系统里
            #   **一个 msedge 进程都没有**。
            #
            # ★ profile 策略：**只用我们自己的隔离 profile，绝不用默认配置**。
            #   用默认 profile 会把用户的登录态/扩展/书签一起带进来，弹同步提示
            #   盖住界面（踩过）。所以这里只准备"带隔离 profile"这一种启动方式，
            #   连它都失败就直接报错，而不是悄悄退化成默认 profile。
            attempts = []
            if profile:
                attempts.append([
                   *common[:2], f"--user-data-dir={profile}", *common[2:]])

            proc = None
            for i, args in enumerate(attempts):
                step(f"launch attempt {i} (isolated-profile)")
                try:
                    _spawn_browser(args, step)
                except Exception as e:                   # noqa: BLE001
                    step(f"  spawn failed: {type(e).__name__}: {e}")
                    continue
                # ★ 不能用被启动进程的退出码判断成败。
                #   Edge 的启动进程只是个 launcher，把请求转交给真正的浏览器
                #   进程后就会退出（用 cmd start 时退出得更快，rc=0）。
                #   早期代码把它当"启动失败"，于是根本没起浏览器 ——
                #   现象就是窗口一闪/白屏，日志里却是 "browser exited early"。
                #   判据改成：**等应用窗口出现**。
                ok = False
                for attempt in range(40):
                    time.sleep(0.75)
                    if api.last_heartbeat > 0:
                        ok = True
                        break
                step(f"  window appeared={ok}")
                if ok:
                    proc = True
                    break

            if proc is None:
                # 附带诊断：--user-data-dir 指向不存在的目录时 Edge 会立刻
                # 退出（exit 21），日志里只会看到 window appeared=False。
                prof_exists = bool(profile) and Path(profile).is_dir()
                step(f"  DIAG profile_exists={prof_exists} profile={profile}")
                no_edge = not _any_edge_process()
                step(f"  DIAG any_edge_process={not no_edge}")
                hint = ""
                if not prof_exists:
                    hint = ("\n提示：配置目录不存在，Edge 会直接退出。"
                            "若用 BOOTH_NEST_PROFILE 指定，请传绝对路径。")
                elif no_edge:
                    hint = ("\n提示：系统里没有 msedge 进程，说明浏览器根本没起来。"
                            "检查 Edge 是否可启动、或被安全软件拦截。")
                raise RuntimeError(
                    "浏览器无法用隔离配置启动。\n"
                    f"配置目录：{profile}（存在={prof_exists}）\n"
                    "请确认该目录可写，或关闭其它正在使用它的程序后重试。"
                    + hint)
            step("client confirmed; starting heartbeat watcher")

            # The launcher can exit before its browser window. The current
            # authenticated UI owns the lifecycle through heartbeats instead.
            threading.Thread(target=_watch_client, args=(api, step),
                             daemon=True).start()

            step("entering serve loop")
            _serve_forever(srv)
        else:
            _message_box(
                "BoothNest",
                "找不到 Microsoft Edge 或 Google Chrome。\n\n"
                f"服务已在本地启动，请手动在浏览器打开：\n{url}\n\n"
                "（按 Ctrl+C 退出）")
            import webbrowser
            webbrowser.open(url)
            _serve_forever(srv)
        return 0
    except Exception:
        tb = traceback.format_exc()
        fp = crash_log(tb)
        _message_box("BoothNest 启动失败",
                     f"{tb.splitlines()[-1]}\n\n日志：{fp}")
        return 1
    finally:
        if instance:
            instance.release()


def _spawn_browser(args: list[str], step):
    """启动浏览器（fire-and-forget）。

    ★ 核心问题：不能由打包后的 exe **直接** Popen 浏览器。
      实测（tests/diag_isolate_flags.py + diag_edge_renderer.py）：
        同一个 Edge、**完全相同的命令行**，从普通进程启动 → renderer 8~9 个；
        从 PyInstaller 冻结的 exe 启动     → renderer **0** 个。
      参数逐个试过（--disable-features / --disable-sync / --disable-extensions）、
      父进程用 DETACHED_PROCESS、清洗 _MEIPASS/PYTHON* 环境变量、console=True
      —— 全都不解决。差异只在「父进程是冻结的 exe」这一点上。

      renderer=0 的后果：窗口出来了、标题停在 URL、**整片纯白**，
      服务端访问日志 0 条请求（浏览器根本没去取页面）。

      ★ 解法：让 cmd.exe 当中间父进程。
        `cmd /c start "" <浏览器> <参数…>`
        浏览器由 cmd 创建，而不是由冻结进程创建，实测能正常出 renderer。

      ★ 不要给浏览器加 CREATE_NO_WINDOW：msedge 是 GUI 程序，带上该标志
        时它会在建窗口前就退出（Popen 成功、pid 也有，但一个 msedge 都没有）。

    注意调用方**不能**用返回进程的退出码判断成败：cmd / start 会立刻退出。
    要以「窗口是否出现」为准。
    """
    comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    cmd = [comspec, "/c", "start", "", args[0]] + args[1:]
    devnull = open(os.devnull, "wb")
    # cmd 自己带控制台，可以给它 CREATE_NO_WINDOW 避免闪黑框
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                         stdout=devnull, stderr=devnull,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    step(f"  spawned via cmd pid={p.pid}")
    return p


def _any_edge_process() -> bool:
    """系统里是否存在 msedge 进程（用于报错时给点线索）。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/NH"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "msedge.exe" in (out.stdout or "")
    except Exception:
        return False


def _watch_client(api, step) -> None:
    """Fallback cleanup if a browser crashes without sending a close hint.

    Background Chromium timers may run only once a minute; allow two minutes
    without heartbeats, then use the same reload-safe close grace period.
    """
    while True:
        time.sleep(5)
        if api.last_heartbeat and time.monotonic() - api.last_heartbeat > 120:
            step("client heartbeat expired; scheduling close")
            api.window_closed()


def _serve_forever(srv) -> None:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
