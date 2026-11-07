# 第三方与许可

BoothNest 基础网站及所含 Python 扫描引擎采用 GPL-3.0-only，完整许可证见 LICENSE。引擎来自本仓库的 BoothNest 实现。本次发行完整源码，不内置 Python、Node.js 或浏览器二进制；运行环境由安装者提供，其许可独立适用。

本产品参考 VRCatalogue 的浏览体验独立实现，不是官方续作，未附原站抓取的 HTML、CSS、JavaScript、Logo 或截图。BOOTH、pixiv、VRChat 和 VRCatalogue 的名称及相关商品内容属于相应权利人，不代表对本项目的背书。

本次只更新网站程序，**不分发 VRCatalogue Open Data、商品目录或图片缓存**。可选元数据读取代码仍保留；安装者自行提供相应数据时，VRCatalogue Open Data 的来源为 https://huggingface.co/datasets/vrcatalogue/vrcatalogue-open-data ，许可为 CC BY 4.0：https://creativecommons.org/licenses/by/4.0/ 。这份数据许可不授权原站界面美术表达、商标或创作者商品图文与下载文件。详见 docs/OPEN_DATA.md。

## 可选原生 Qt 客户端

`desktop/qt_main.py` 使用 PySide6 / Qt Widgets，客户端源码为 GPL-3.0-only。组件版本、开源授权选项和上游源码见 [QT_THIRD_PARTY.md](docs/QT_THIRD_PARTY.md)，Qt 授权原文保存在 `licenses/`。Windows Qt 程序包另附 Python、Node.js、PyInstaller 许可；这些运行时随 Qt artifact 分发，不改变网站源码包的运行要求。
