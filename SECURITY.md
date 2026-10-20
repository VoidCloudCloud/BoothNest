# 安全反馈与支持范围

当前维护目标是最新公开测试版，支持 Windows 本地单用户使用。内置 HTTP 服务只监听 127.0.0.1，不能当成多用户网站部署。持有操作系统账号权限的其他程序仍可能访问同一用户的数据和进程，这不属于账号隔离机制。

报告安全问题时，请使用 [GitHub 私密漏洞报告](https://github.com/VoidCloudCloud/BoothNest/security/advisories/new)，避免公开个人路径、库存、会话凭证或可用于攻击其他用户的细节。请包含版本、复现条件、影响和最小化样本。普通运行问题请使用 [问题模板](https://github.com/VoidCloudCloud/BoothNest/issues/new/choose)。

发布验证应包含无凭证 / 跨站请求被拒、路径越界被拒、文件只在资源管理器定位、CSV 公式转义、压缩包处理上限与原文件哈希不变。自动检查可通过 `python tools/test.py` 运行。
