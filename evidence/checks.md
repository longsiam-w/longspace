# 验证记录与边界

## C-20261107-01｜本次取证（不是业务复测）
- 时间：2026-11-07，UTC+08:00；工具时钟首次返回 23:41:20。
- 环境：Windows PowerShell；Node.js v22.16.0；当前目录不在 Git 仓库内（rev-parse 返回 fatal），没有提交基线。
- 实际操作：递归查找 AGENTS.md（未发现）；读取聊天导出内 JSON，枚举全部 85 条消息、0 个 forks，并对关键事件定向查看原文/工具输出；读取现存架构代码、相关测试与交付文档。没有宣称完整逐字审阅所有聊天工具载荷。
- 方式：本地 Node 脚本提取 script#chatbox-export-data，去 HTML 标签后按消息 ID 定位。解析中间文件仅在会话临时区，不复制进 evidence，不公开。
- 一次辅助命令因 PowerShell 对内联正则引号解析失败，改为独立 mjs 文件后读取成功；不影响业务代码。
- 结果：确认核心实现存在，发现 README 队列淘汰说明过期、权限故障根因未获线上堆栈等证据边界；仅创建本目录文档。
- 未做：没有导入 server.py（其顶层会创建数据目录/密钥）、运行测试、安装依赖、启动服务、连接生产或生成部署包。

## C-20261107-02｜历史自动化验收清单

下表均是**历史结果**，不是本次运行。历史工作目录是迁移前 FTP 目录，无 Git 提交；旧文档标注主要使用临时 HUB_DATA、小样本、无生产访问/压测。Python 精确版本、依赖锁定版本、机器配置和每项耗时没有完整保留，不据此做性能比较。测试组数随当时版本变化，不将旧 6/7 组与新 8 组混为同一次运行。

| 范围 | 历史命令/入口 | 历史证据与结果 | 关键限制 |
|---|---|---|---|
| 跨平台打包 | `python deploy/archive-tool.py pack ...` / `unpack ...`，PowerShell Parser | 聊天 #8 原始输出：安装入口存在、无字节码、语法 PASS | 旧包确切失败原因未还原；不是本次包验收 |
| TLS 与续期 | `deploy/Check-Https.ps1`，内部 Certbot renew dry-run | 用户 #29 原始输出：health 200、timer active/enabled、all simulated renewals succeeded | 只证明当时状态；公网恢复由用户 #37 报告 |
| 后端集成 | `python -m unittest test_hub -v` | `消息转发稳定性审查.md` 先后记录 6/7 组；附件交付记录 8 组通过；源码有 folders_move_zip、reliable_send、token_rotation | 当前未重跑；没有断电/磁盘故障实验 |
| 转发微检查 | `python check_relay.py` | 稳定性审查：4 条微小消息，HTTP/WS/离线/ACK/非法帧及新进程恢复通过 | 新进程重读不等于断电保证；不是生产 WSS 全链路 |
| SDK 生命周期 | `node test_relay_sdk.mjs` | 稳定性审查/协议交付报告通过 | 伪 socket，无网络；不等于真实黑洞网络演练 |
| 文档页 | `python test_api_docs.py` | 聊天 #63 有原始 `API docs PASS: strict CSP, no external requests/errors...Local only.` 输出 | 本地浏览器，不证明 Linux 文件权限或线上部署 |
| GUI | `python test_browser.py`、`python test_gui.py` | `GUI-交付验收.md`：小文本与改名副本，320/390/768/1440 视口，目录移动/URL/弹窗等通过 | 桌面模拟视口不是实机；没有断点续传、无大数据测试 |
| 业务协议 | `python test_business_protocol.py`、`node test_business_protocol.mjs` | `业务消息协议与截图链路.md` 报告 Python 2 组、JS 及兼容/授权/过期测试通过 | 不是已连接平板笔记软件 |
| 临时附件 | `python test_attachments.py`、`node test_attachment_client.mjs` | `临时附件前置工程.md` 报告鉴权/隔离/幂等/确认/清理通过；65 字节超测试上限 64 字节；客户端模拟流 | Node 测试无真实网络；无真实大文件/慢网络/生产验收 |

## 待补但不伪造的证据

1. 新版本实际部署时间、版本标识与轻量验收输出（先按用户授权执行，不自动连接）。
2. Linux 服务用户读取资源的原始检查、应用异常日志，以验证权限根因与修复。
3. 若未来求职要说明个人能力，补本人对幂等、事务/副作用边界、TLS 分层诊断的讲解或亲自操作记录；现有 AI 生成代码不替代它。
4. 真机截图→笔记链路须先明确平台/软件能力再实现，当前不得补写成功截图或虚构用户反馈。
