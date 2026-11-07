# BoothNest 原生 Qt 客户端

此客户端使用 PySide6 / Qt Widgets。商品图库由 QListView、QAbstractListModel 和绘制委托实现；库存管理使用 QTableView。界面不加载网页或 WebEngine。

此客户端目前为主分支预览。[Qt desktop checks](https://github.com/VoidCloudCloud/BoothNest/actions/workflows/qt.yml) 的成功 Windows 构建提供 `BoothNest-Qt-Windows` artifact，包含程序 ZIP、对应源码 ZIP 和 SHA256SUMS。下载 artifact 后完整解压其中的 `BoothNestQt-windows-x64.zip`；程序包不附商品目录、开放数据库、图片缓存或私人数据，新数据目录从空库开始。现有 Release 地址仍对应原发布内容。

## 使用

双击 `BoothNestQt.exe`。默认使用 `%LOCALAPPDATA%\BoothNest`；可用 `--home "绝对数据目录"` 连接已有库存。程序与网页客户端共享原有 Node 服务和 Python 扫描引擎。每个数据目录同一时间只允许一个客户端运行，避免多个后台同时写入。

支持图库/表格、搜索、分类/模型/作者/标签/功能与本地文件筛选、排序、分页、详情与多图预览、收藏、最近浏览、保存筛选；支持原生扫描与取消、定时扫描、库存修正、分组统计、SHA-256 重复文件核对、CSV 导出、商品/已购 JSON 导入导出、公开同步与浏览器扩展配对。BOOTH 链接在系统浏览器打开。

标签树中，勾选表示包含，半选表示排除。更多筛选包含价格、库存范围、已购范围和体积条件。Ctrl+F 聚焦搜索，Ctrl+K 打开快捷查找，F5 刷新，Ctrl+L 打开库存管理，Ctrl+O 打开扫描窗口。快捷查找使用本地索引，提供商品、模型、作者与标签建议；↑↓ 选择，Enter 打开，Esc 关闭。选择模型、作者或标签时保留内容分级并重置其他筛选。

顶部可切换简体中文 / English、JPY / CNY / USD、深色 / 浅色，立即更新图库、表格与已打开的窗口，并通过原有偏好接口保存。英文商品标题和说明优先使用目录已有的英文译文，缺少译文时保留原文；商品标签、作者、规格、路径及扫描日志保留原始数据。

价格采用与网页一致的固定参考汇率：1 JPY ≈ 0.048 CNY / 0.0067 USD，覆盖卡片、商品表格、详情与规格。实际价格以 BOOTH 日元结算为准；价格筛选仍使用 JPY。免费与价格未知分别显示。

“分享筛选…”可复制可移植的筛选文本，也可粘贴筛选文本或现有网页筛选链接。此操作只在本机解析，不访问链接。导出仅包含公开的类别、模型、作者、标签、功能、文字、内容分级、日元价格、排序和每页数量；本地库存、已购、收藏、最近浏览、结果 ID、路径、配对码及令牌不会导出。私人视图和本地排序会退回公开浏览。复制前可检查完整文本；不会生成依赖本机回环地址的分享链接。

源下载文件仍由原引擎只读扫描。自动同步、库存修正与导入仅在用户点击相应操作或此前已配置的计划到期时执行。

关闭主窗口会等待收藏与浏览记录保存，随后请求后台取消任务、提交已完成进度并退出。通过 `--url http://127.0.0.1:端口` 连接独立服务时，关闭 Qt 窗口保留该服务。

## 源码运行

使用 Python 3.12+ 与 Node.js 22.13+，在独立虚拟环境安装 `requirements-qt.txt`：

```powershell
cd web
python -m pip install -r requirements-qt.txt
python desktop/qt_main.py --home "D:\BoothNestData"
```

构建：安装 `requirements-build.txt`，执行 `python desktop/build_qt.py --node "C:\path\node.exe" --output "D:\QtBuild"`。构建产物与现有安装独立，个人数据不进入程序包。

`--smoke-test "输出目录" --home "一次性库存副本"` 会对指定副本执行真实 UI/API 自验，包含收藏、最近浏览、保存筛选和一次性目录扫描写入。测试目录必须包含 `.qt-test-home` 标记；只能用于可丢弃的测试副本。

在 `web/desktop` 执行 `python -m unittest test_qt_client test_launcher -v` 可运行不依赖个人数据的原生与生命周期回归。GitHub Actions 会运行这些检查、构建 Windows 程序，并验证打包入口。

本客户端源码遵循 GPL-3.0-only；PySide6 / Qt 的相应授权和声明随程序附带。
