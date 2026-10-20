# 参与 BoothNest

欢迎提交可复现的问题、功能建议、文档修改和 Pull Request。交流可以使用中文或英文。

## 本地开发

需要 Python 3.12+，运行应用无需第三方 Python 包；维护检查需要 Node.js 22。

```powershell
git clone https://github.com/VoidCloudCloud/BoothNest.git
cd BoothNest
python run.py
python tools/test.py
```

可设置 `BOOTH_NEST_HOME` 为独立测试数据目录。请使用合成文件与临时目录，不要用真实商品素材、购买记录或个人库存作为提交的测试样本。

## 修改原则

- 扫描与文件内容核对保持只读，不自动移动、执行或删除下载。
- 人工归属规则优先于自动识别，取消或失败不能覆盖上次完整结果。
- 本机服务保持回环监听、会话凭证、同源与路径边界校验。
- 离线模式不能隐式请求商品、搜索或图片接口。
- 新的数据格式应考虑已有库存与人工规则的兼容；未经说明不改变统计口径。

请先运行 `python tools/test.py`，在 PR 中说明修改原因、用户能观察到的变化、验证方式及尚未验证的场景。界面修改尽量附合成数据截图；涉及数据写入、取消或路径处理时，请补充有意义的回归检查。

## 提交范围

仓库使用 `.gitignore` 允许清单，`tools/check_release.py` 维护对应源码清单。新增维护文件时检查两处是否都需要更新。不要提交 `seed/`、`data/`、`cache/`、`dist/`、`release/`、配置、人工修正规则、日志或包含个人路径的截图。

新增 Python 模块使用 GPL-3.0-only SPDX 声明。提交代码即表示你有权以本项目许可证提供这些修改；无需签署额外贡献者协议。

## 发布维护

1. 更新 `boothlib/__init__.py`、`build/version_info.txt`、README 和 CHANGELOG 的版本信息。
2. 在 Windows 运行完整测试和 `python tools/build_release.py`。
3. 用独立数据目录验收新用户启动、目录选择、离线扫描、人工修正、内容核对和关闭退出。
4. 核对 ZIP、SHA-256 与对应源码；检查源码包独立解压后的测试。
5. 为已验证提交创建标签；在 GitHub 发布预发行版时，同时提供 Windows 程序、对应源码、摘要与文件清单。

CI 仅测试和构建，不会自动发布 Release。安全问题请使用 [私密漏洞报告](https://github.com/VoidCloudCloud/BoothNest/security/advisories/new)，不要在公开 Issue 中提交攻击凭证或个人数据。
