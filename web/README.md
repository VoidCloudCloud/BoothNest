# BoothNest 基础网站

版本 `2.0.0-beta.6`，源码采用 GPL-3.0-only。提供浏览器图形界面，包含本机网站和带登录的在线入口。

## 下载与 GUI

- [下载网站源码 ZIP](https://github.com/VoidCloudCloud/BoothNest/releases/download/web-v2.0.0-beta.6/BoothNest-Web-2.0.0-beta.6-source.zip)；[发布说明、SHA-256 与逐文件清单](https://github.com/VoidCloudCloud/BoothNest/releases/tag/web-v2.0.0-beta.6)。
- 网站源码包需要 Node.js；扫描和经典管理另需 Python。Windows 的 `Start.cmd` 只是启动脚本，需要先安装运行环境，启动后手动打开下方地址。
- 本版本未提供新版免运行环境 EXE。需要解压后双击即用的 Windows 包，可选择[原桌面版 Beta 3](https://github.com/VoidCloudCloud/BoothNest/releases/tag/v1.1.0-beta.3)，其界面和功能对应桌面旧版。
- fnOS / Docker 用户按下方部署步骤操作。已部署好的网站，访问者只需要浏览器。

包含浏览、搜索与筛选、收藏、商品详情、目录导入导出、现有库存读取和管理，以及带登录验证的在线入口。**发行包不附商品目录、VRCatalogue 数据库、图片缓存、库存、购买记录或账户配置。新数据目录首次启动为空，也不会自动下载一套数据。**

## 本机运行

需要 Node.js 22.13+；扫描与经典管理引擎需要 Python 3.12+，无第三方 npm 或 Python 运行时依赖。

```sh
# 从仓库根目录运行；发行 ZIP 解压后已在网站目录，可跳过 cd web。
cd web
node server.mjs
```

Windows 也可双击 `Start.cmd`。打开 `http://127.0.0.1:4317`，保留启动窗口，按 `Ctrl+C` 停止。默认仅监听本机，运行数据保存在网站目录的 `data/`。可用 `BOOTH_NEST_WEB_HOME` 指定独立的绝对数据目录，`BOOTH_NEST_ENGINE_HOME` 指定原有引擎数据目录，`BOOTH_NEST_PYTHON` 指定 Python 解释器。

## Docker 在线部署

在网站目录执行：

```sh
cp .env.example .env
# 编辑 .env，设置自己的密码和允许访问的域名/Host。
docker compose up -d --build
```

模板默认只把端口发布到本机 `127.0.0.1:8010`。公网使用时配置 HTTPS 反向代理，并把实际域名加入 `BOOTH_NEST_ALLOWED_HOSTS`；局域网直连可设置 `BOOTH_NEST_BIND=0.0.0.0` 并加入实际的 `主机:8010`。账号密码使用 HTTP Basic 登录。

不使用 Docker 时，设置 `BOOTH_NEST_USER`、`BOOTH_NEST_PASS`、`BOOTH_NEST_ALLOWED_HOSTS` 后运行 `node online.mjs`，默认端口为 8010。在线入口隐藏或拒绝服务器上的目录选择器、文件管理器动作、桌面扩展配对及网页退出服务；商品链接在访问者的浏览器打开。

Docker 数据独立挂载到 `/data/BoothShelf`，网页数据位于其 `web/` 子目录。需要扫描自己的下载目录时，可在 Compose 中添加到 `/downloads` 的只读挂载。`/healthz` 用于健康检查；页面、API、导出和缓存图片均需登录。

## 更新已有网站

先备份并停止旧服务，只替换程序文件，继续使用原来的数据卷、登录配置、下载目录挂载和自定义路径。**不要用发行包目录替换原数据目录，也不要覆盖既有 `.env`。** 发行包不包含种子目录或初始化商品数据，已有 `catalog.json` 会直接读取，启动不会用新快照覆盖它。

自动同步、扫描与购买记录导入属于用户主动配置的数据功能；升级程序本身不执行全库重扫或联网收录。已启用的原有定时任务仍按原配置运行。可选开放数据索引的说明见 [OPEN_DATA.md](docs/OPEN_DATA.md)。

支持现有网站数据及 BoothNest / BoothShelf 库存快照，包括旧 `bytes` 字段。网站数据目录和引擎库存目录用途不同；升级、旧桌面库接入、Windows 路径转容器路径的处理及兼容性验证范围，见 [旧数据兼容与升级](docs/UPGRADING.md)。

## 测试与打包

```sh
npm run check
npm test
python scripts/build-website.py
```

`release/` 中生成 `BoothNest-Web-版本-source.zip`、SHA-256 和逐文件 manifest。打包使用代码清单，不复制运行目录、数据库、图片缓存、原站参考文件或日志。测试使用临时合成数据，包含空库启动、已有目录保留、登录和请求来源验证。

本项目参考 VRCatalogue 的浏览体验独立实现，非其官方续作。商品与 listing 属于各自权利人；本次不分发商品素材或其开放数据库。参见 [第三方说明](THIRD_PARTY_NOTICES.md) 与 [隐私说明](PRIVACY.md)。
