# longspace

A personal website featuring a cross-platform software information flow system and a cloud USB drive system.

# LONGS Private Hub

私人云U盘 + 多端软件通信中转 + 可替换门户。**本地实现，不代表已部署到 8.163.121.238。**

## 本地运行
Python 3.11+：
```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python manage.py init
$env:HUB_ORIGIN='http://127.0.0.1:8765'
.venv\Scripts\python -m uvicorn server:app --host 127.0.0.1 --port 8765 --workers 1 --ws-max-size 65536 --no-access-log
```
初始化密码通过交互式 CLI 输入，无最低字符数限制，但不能为空。建议使用较长、独立的密码；短密码会降低抗猜测能力。HTTP 仅用于 loopback 本地调试。生产必须设置准确 HTTPS HUB_ORIGIN；不能用公网 HTTP 登录。

- `/` 门户（邮箱 wen.longs@qq.com）
- `/drive` 文件目录树、上传、下载、删除、文件夹操作
- `/dashboard` 软件登记、单次显示凭据、注销、吞吐图、队列元数据、转发事件
- `/integration/SKILL.md`、`/integration/hub-sdk.mjs` 接入材料
- `/api/docs`、`/api/openapi.json` 基础接口文档

配置：HUB_DATA 数据目录，HUB_ORIGIN 对外 HTTPS Origin（无末尾斜杠），HUB_MAX_FILE_BYTES 默认 1 GiB，HUB_QUOTA_BYTES 默认 20 GiB。仅运行 **1 个 worker / 1 个实例**，在线连接、会话、计数均在进程内存；不支持直接水平扩容。重启需重新登录，但待确认消息保留。

## 安全与保留边界
- 这不是传统 FTP 服务，没有明文 FTP 端口；采用 HTTP API + HTTPS/WSS。
- 文件随机对象名、AES-256-GCM 每块随机 nonce、AAD 绑定文件和块序号，认证尾部检测截断。文件名、目录名、大小不加密；文件内容在服务器可解密（非零知识网盘）。
- data/master.key 是服务器存储主密钥。限制整个数据目录权限 0700、密钥 0600。备份时密钥应与数据分开加密保存；丢失密钥无法恢复。获得服务器 root 的攻击者仍能解密存储。没有自动密钥轮换；轮换需离线迁移。
- 文件默认 1 GiB 上限、全库 20 GiB 配额；不做覆盖写入；仅空文件夹可删除。没有回收站、在线预览或断点续传。
- 消息为每接收方最多 10 条待 ACK 的 FIFO 队列；满时返回 HTTP 409，不淘汰旧消息。支持 clientMessageId 幂等发送，ACK 后收据保留 7 天，每发送方最多 10000 条；每软件每分钟最多发送 120 次。接入业务仍须持久化 outbox/inbox 与去重，不承诺全局 exactly-once。
- 消息正文加密落盘，软件 token 仅存 SHA-256 摘要；SDK 提供可选 AES-GCM 端到端加密。建议敏感消息强制使用 E2E 并通过独立渠道分发每对软件密钥。服务器仍见发收编号、时间与大小。
- ACK/删除是逻辑删除，不是 SSD、快照、云备份上的物理安全擦除。SQLite secure_delete=ON，每分钟 WAL TRUNCATE；数据库空闲页、WAL、备份可能短期包含密文。不要给消息库做长期历史备份，需恢复文件时可离线备份并排除队列表。
- 最近 100 条事件仅保存在内存，无消息正文；转发记录同时保存软件名与 ID。吞吐图独立按分钟汇总最近 2 小时（含当前分钟），不受事件列表截断影响；累计计数与图表均在服务重启后清零。在线表示最近 75 秒有有效软件 HTTP 请求或当前认证 WebSocket 的 auth/ping/ACK 活动，建议每 25 秒心跳或轮询，不代表业务健康。默认禁用 uvicorn access log，代理默认日志不含请求正文；不要开启调试正文日志。
- 管理员 Cookie HttpOnly + SameSite=Strict，HTTPS 时 Secure；12小时会话；跨 Origin 写操作拒绝、WS 校验 Origin；登录每 IP 五分钟最多10次。无 XSS 形式的动态 HTML 拼接。公共软件映射是产品要求，注册名不应包含隐私。
- 管理员可上传可信门户 HTML 到 HUB_DATA/portal/index.html 替换 `/`；仍保持 CSP、不支持任意外链或内联脚本。需要自定义 JS/CSS 或复杂门户时，应在反向代理仅覆盖 `/` 和专用静态前缀，保留 `/drive`、`/dashboard`、`/api`、`/assets`、`/integration`。任意同源网页代码可能滥用管理员会话，必须审查，不应托管不可信页面。

## 测试
```
python -m unittest test_hub -v
```
独立临时数据库，无需触碰真实数据。覆盖：登录权限、CSRF、加密上传回读、中文名、空文件、重复名、路径穿越、非空目录删除、队列上限及顺序、双向队列、ACK 权限、发送者防伪、WS 离线补收与在线转发、撤销凭据、大消息限制。

## 服务器部署：先检查后切换
当前缺 SSH 用户名/端口/认证方式、现有站点配置及可信 HTTPS 信息。不能猜测 root 登录或覆盖未知虚拟主机。

1. 打开本地 PowerShell，在项目目录运行 `powershell -ExecutionPolicy Bypass -File .\deploy\Connect-Server.ps1`，交互输入 SSH 用户名和密码（密钥登录可加 `-IdentityFile '你的密钥路径'`、端口可加 `-Port 22`）。首次指纹要与云控制台核对。脚本只读检查 OS、监听和 Nginx 配置，不自动改站。
2. 根据检查结果，备份当前生效虚拟主机和旧站目录至带时间戳的目录；旧测试页应从服务路径撤下，但保留私有备份以便回滚。不要直接删除其他网站配置。
3. Ubuntu/Debian + systemd 的示例安装（其他环境按探测调整）：
```
sudo apt-get update
sudo apt-get install -y python3-venv nginx
sudo useradd --system --home /var/lib/private-hub --shell /usr/sbin/nologin private-hub
sudo install -d -m 755 /opt/private-hub/app
sudo install -d -m 700 -o private-hub -g private-hub /var/lib/private-hub
sudo python3 -m venv /opt/private-hub/venv
```
通过 scp 将 server.py、relay_attachments.py、manage.py、requirements.txt、web/、integration/ 和 deploy/ 上传到 `/opt/private-hub/app`（先传普通用户目录再 sudo 安装），不要上传 data、测试临时库或私钥。
```
sudo /opt/private-hub/venv/bin/pip install -r /opt/private-hub/app/requirements.txt
sudo -u private-hub env HUB_DATA=/var/lib/private-hub /opt/private-hub/venv/bin/python /opt/private-hub/app/manage.py init
```
上面的 init 直接在远端交互终端输入密码。使用 `sudoedit /etc/private-hub.env` 写入：
```
HUB_DATA=/var/lib/private-hub
HUB_ORIGIN=https://你的实际域名
HUB_MAX_FILE_BYTES=1073741824
HUB_QUOTA_BYTES=21474836480
```
```
sudo chmod 600 /etc/private-hub.env
sudo cp /opt/private-hub/app/deploy/hub.service /etc/systemd/system/private-hub.service
sudo systemctl daemon-reload
sudo systemctl enable --now private-hub
curl http://127.0.0.1:8765/api/health
```
4. 复用或签发可信 TLS 证书。推荐绑定域名到此 IP；若仅用 IP，必须取得受信任的 IP-SAN 证书，不可把自签名等同受信任 HTTPS。没有证书时可先通过 SSH 隧道本地验收，不要将后台裸露在 HTTP 公网。
5. 参考 deploy/nginx.conf.example 只调整目标虚拟主机；先 `sudo nginx -t`，再 `sudo systemctl reload nginx`。不停止整台服务器，不改无关主机。防火墙只放行需要的 22/80/443，8765 仅绑定本地。
6. 验收：旧测试首页不再出现；门户链接、HTTPS 锁、登录/退出、文件上传下载、WS 断线补收、十条溢出、注销客户端、服务重启积压仍在。跨设备实际验证才算部署完成。
7. 回滚：恢复备份的目标 Nginx 虚拟主机并 nginx -t/reload；必要时 stop private-hub。保留 /var/lib/private-hub 不丢文件。不会提供无条件覆盖现有网站的一键脚本。

## 更新现有部署

在项目目录运行 `powershell -ExecutionPolicy Bypass -File .\deploy\Update-Ui.ps1`，输入 UPDATE，SSH 密码仅在终端输入。先暂停上传和通信任务，并配套备份数据库与主密钥。更新器备份应用文件、更新代码和资源、校验页面正文；应用代码变化时重启服务，旧登录失效。失败会尝试恢复应用文件，不修改密码、Nginx、TLS 或环境配置。部署脚本包含原站点默认配置，复用前须核对目标主机。

## 许可证

本项目采用 [MIT License](LICENSE)。第三方依赖仍遵循各自许可证。
