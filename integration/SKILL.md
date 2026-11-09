---
name: longs-private-hub
description: 接入 LONGS云消息转发，按 longs-app v1 区分数据、事件、指令及结果，处理鉴权、幂等、持久收件、ACK与截图传递。
---

# LONGS云通信接入 Skill

## 使用前与安全边界
1. 向用户确认 HTTPS baseURL、该软件自己的 ID 和 token，不得索取管理员密码或服务器主密钥，不把 token 写进源码、聊天、URL、日志、公共网页或 Git。单用户软件也应首次配置后存入系统凭据库，脚本可用环境变量或受保护的本地配置。
2. 每台设备/独立实例分别登记。一个ID只有一个实时连接；不要同编号多进程抢连。Token重新分配使旧token失效，ID和待确认消息保留。
3. 阅读 `/guide`、`/integration/README.md`、`/api/docs`。SDK `/integration/hub-sdk.mjs` 适用于现代浏览器/Node.js 22+；配套 `/integration/business-protocol.mjs` 必须一起保存，不能只下载SDK一个文件。
4. 默认仅本地少量验证。未经明确授权不连接生产发消息、不压测、不读取管理员密码或真实截图。屏幕监听须用户主动开启，提供暂停、目标白名单及明显状态；不暗中截屏。

## 转发层协议
- `GET /api/software`：公开软件ID/名称/version，不含token。软件名称避免隐私。
- `POST /api/messages`：Bearer token；JSON `{recipient:"ID",clientMessageId:"持久化唯一标识",body:业务内容}`；整个请求最大65536字节，每发送软件每分钟最多120次。sender由token决定，正文自报sender不能用于授权。
- 首次返回 `{id,queued:true,state:"queued",duplicate:false,clientMessageId,evicted:[]}` 仅表示持久入队。每接收方最多10条未ACK；满时409拒绝新增，不丢旧消息。发送方保留outbox并退避，不盲目紧循环。
- clientMessageId：1–128个可见ASCII字符，同一发送软件内唯一；重试必须同接收方、同正文，返回原id和duplicate:true。已ACK返回state:"acked",queued:false，不是发送失败。标识复用但正文不同409。未传标识的旧客户端仍可用，但不提供发送幂等。
- 幂等记录未ACK保留，ACK后保留7天，每发送方最多10000条；满时429，超过保留期不能假设幂等。注销软件删除相关记录。
- `GET /api/messages`：拉取本人未ACK消息；`POST /api/messages/{id}/ack`：本人确认接管后删除，幂等。ACK不等于业务执行成功。
- 收到的外层消息为 `{type:"message",id,sender,recipient,body,created}`，created为Unix秒。不要把外层type改成command；业务类型在body.kind。
- WSS `/api/ws`：10秒内首帧 `{type:"auth",token:"..."}`。服务端 `{type:"sync",messages:[外层消息...]}` 是全部未ACK快照，会重复。每25秒ping，回pong；75秒无客户端帧断开。
- 4001编号被替换、4003撤销/失效、1008协议拒绝：SDK停止重连；网络错误指数退避。连接建立默认15秒超时，HTTP默认15秒超时，可分别配置connectTimeout/requestTimeout。
- 入队与在线推送解耦，两个固定worker合并通知；断线后重连/pull补收。必须单worker部署，不能直接增加uvicorn workers。

## LONGS应用消息协议 v1（新增业务必须采用）
服务端保留旧任意JSON兼容。明文声明 `protocol:"longs-app"` 时服务端严格校验信封，不合格400；旧消息不自动改写为新协议。加密正文必须发送前/解密后在客户端校验，服务端不可能验证密文内字段。不要把兼容路径当作接收端授权校验。

### 业务信封
```json
{
  "protocol": "longs-app",
  "version": 1,
  "kind": "command",
  "name": "notes.import-image",
  "operationId": "3f504c58-c144-4fae-b012-561f32e6fd21",
  "issuedAt": "2026-11-07T08:00:00Z",
  "expiresAt": "2026-11-07T08:05:00Z",
  "payload": {"assetId":"待实现的附件ID"}
}
```
- 必填：protocol、version、kind、name、operationId、issuedAt、payload。信封不允许额外顶层字段，业务扩展放payload。
- protocol固定longs-app，version固定整数1；未知版本拒绝。
- kind仅四种：`data`传递数据；`event`报告已发生事件；`command`请求明确动作；`result`回复业务结果。
- name：最长96字符，小写ASCII字母开头，由小写字母/数字组成，可用点、短横线、下划线分段，例如clipboard.text、capture.created、notes.import-image。
- operationId：1–128字符，字母/数字开头，后续允许字母、数字、点、冒号、短横线、下划线；建议UUID。
- issuedAt：UTC RFC3339，秒或最多3位毫秒，必须Z结尾。expiresAt同格式且晚于issuedAt，command必须有expiresAt。data/event/result可选。
- payload必须JSON对象，不直接放大图片/base64。消息大小仍受转发层总限制。
- result必须status为succeeded/failed/rejected；失败或拒绝必须error `{code:"UPPER_SNAKE_CODE",message:"最多512字符",retryable:false}`；成功不得带error。非result不得带status/error。
- result沿用原指令的operationId/name，用于关联；其发送clientMessageId必须独立，例如 `result:<operationId>`。同一个请求不要用同一clientMessageId发送中间和最终结果；本版result只表达最终结果。
- operationId是业务标识，clientMessageId是传输幂等标识，server id是队列消息ID；不要混淆。

### 四类示例
```json
{"protocol":"longs-app","version":1,"kind":"data","name":"clipboard.text","operationId":"data-001","issuedAt":"2026-11-07T08:00:00Z","payload":{"text":"hello"}}
```
```json
{"protocol":"longs-app","version":1,"kind":"event","name":"capture.created","operationId":"capture-001","issuedAt":"2026-11-07T08:00:00Z","payload":{"mimeType":"image/png","size":12345}}
```
```json
{"protocol":"longs-app","version":1,"kind":"command","name":"notes.import-image","operationId":"import-001","issuedAt":"2026-11-07T08:00:00Z","expiresAt":"2026-11-07T08:05:00Z","payload":{"assetId":"example-only","sha256":"附件哈希","notebookId":"用户配置的目标"}}
```
```json
{"protocol":"longs-app","version":1,"kind":"result","name":"notes.import-image","operationId":"import-001","issuedAt":"2026-11-07T08:00:02Z","status":"failed","payload":{},"error":{"code":"IMPORT_UNAVAILABLE","message":"笔记软件未提供导入接口","retryable":false}}
```
附件ID必须由PUT /api/attachments实际返回，不得自行编造。附件必须指定同一个目标接收方。

### SDK与接收校验
```js
import {HubClient,createBusiness,validateBusiness} from './hub-sdk.mjs';
// 生成一次，将body、recipient、clientMessageId持久化到业务outbox，重试复用原值。
const body=createBusiness({kind:'command',name:'notes.import-image',
  operationId:crypto.randomUUID(),expiresAt:new Date(Date.now()+300000).toISOString(),
  payload:{assetId:'由受信任附件服务实际返回的ID'}});
await hub.sendBusiness(recipient,body,{clientMessageId:persistedSendId});
// 在onMessage中，用外层message.sender鉴权；E2E先解密，再校验。
validateBusiness(message.body,{sender:message.sender,allowedSenders:[trustedPcId],
  allowedCommands:['notes.import-image'],checkExpiry:true});
// 再校验name对应payload schema，并事务性写入持久任务/inbox；成功后才resolve/ACK。
```
Python校验器：`from integration.business_protocol import validate_business`（本地项目）或下载 `/integration/business_protocol.py` 后导入。支持allowed_senders、allowed_commands、check_expiry。信封校验不代替每命令参数schema。SDK sendBusiness严格校验；普通send对声明longs-app的明文也校验，旧JSON不强制。

## 指令执行与可靠性
1. 先用外层sender白名单授权，再校验protocol/version/name/payload；禁止eval或正文中的任意shell执行。
2. 接收端执行前检查过期与时钟：issuedAt超过本机未来60秒拒绝；到expiresAt即过期。接收长时间排队任务执行前重新检查，服务器仅检查格式，不代替执行端判断有效期。
3. 持久化去重键至少包含外层sender、operationId；同键不同指令/参数必须拒绝，不能静默当作重复。结果与指令可共用operationId，但处理表应区分kind/角色，避免误吞回复。
4. onMessage仅在任务已可靠接管后resolve；耗时任务可先事务性写入本地任务队列再ACK，然后执行、持久保存结果并通过outbox回复result。拒绝/过期也先持久记录处理结论和回复任务，再ACK，避免毒消息无限重连。
5. `/integration/reliable_receiver.py`仅演示本地SQLite业务inbox与消息ID去重同事务，不自动执行指令，不替你实现业务operationId冲突检测/第三方副作用。邮件、笔记导入等外部动作必须使用目标API幂等或可恢复outbox，不能承诺exactly-once。
6. SDK串行消费、内存最多1000个已处理ID，不跨重启。业务回调挂起会阻塞后续；错误不要打印token/正文。SDK不会自动重发send；错误携带clientMessageId，应用需预存原正文。
7. 接收入队、ACK、业务result是三种状态；只有业务成功结果说明执行端报告完成，仍需信任接收端与可验证结果。

## 电脑截图 → 平板笔记的推荐链路
1. 电脑端用截图工具保存到专用目录，监听该目录新增PNG/JPEG；等文件稳定写完、验证格式/大小、计算SHA256并记录outbox。只监听用户指定目录，不默认持续截全屏。
2. 图片走附件通道，消息只发assetId、mimeType、size、sha256及目标笔记本；不发base64大图，不把管理员密码嵌入电脑/平板软件。
3. 云U盘API仍是管理员会话鉴权，不得把管理员密码嵌入客户端；附件使用以下软件token专用API，保存到HUB_DATA/.file，不显示在云U盘。
4. 平板接收程序校验发送方、协议、时效、附件来源、类型和哈希；只从固定可信服务下载，不接受任意URL以免泄露token或引入SSRF/恶意文件。
5. 自动写入笔记取决于目标App：优先官方API/导入接口；若仅有分享面板，则下载后通知用户点一次“导入”；若系统后台限制接收，则前台/系统允许任务才收取。不能保证第三方App在锁屏后台静默导入。
6. 导入成功回result；错误保留可重试状态。操作ID避免重复导入；图片删除需显式保留期/双方确认，不在消息ACK后立刻删除。
7. 开发前确认平板系统（Android/iPadOS）、笔记App名称及版本、是否支持API/快捷指令/分享导入；未确认前不承诺全自动。

## 加密与运维
正文在服务端加密落盘不是E2E。可用seal/open和独立32字节密钥在客户端E2E；先校验再加密，解密后再校验。重试复用原密文，随机重新加密会破坏传输幂等。正文不可信，即使来自自己的设备也要校验。

单worker，备份SQLite和master.key配套。健康200不代表WSS/业务成功；文件I/O仍与消息共享进程。ACK逻辑删除不承诺介质物理不可恢复。仪表盘内存计数重启归零。

## 小规模检查
```powershell
python check_relay.py
python test_business_protocol.py
node test_business_protocol.mjs
node test_relay_sdk.mjs
```
默认本地临时数据，无生产请求，不压测。经用户授权才使用 `python check_relay.py --url https://可信域名` 只读检查；完整双向2条HTTP探测另需专用空闲编号及HUB_CHECK_A_ID/A_TOKEN/B_ID/B_TOKEN环境变量，再显式加--send。不关闭TLS校验，线上模式不证明WSS/重启可用。


## 临时附件通道（.file）
- 物理路径HUB_DATA/.file（默认线上/var/lib/private-hub/.file），非云U盘files表、非静态公开目录；内容分块AES-GCM加密，磁盘文件仅服务器随机ID，不采用用户路径。
- 单文件默认HUB_MAX_FILE_BYTES（默认1GiB），临时区默认min(云盘配额,2GiB)。可单独设置HUB_ATTACHMENT_MAX_BYTES、HUB_ATTACHMENT_QUOTA_BYTES；与云盘分开计数但共享服务器实际磁盘。默认24小时过期，可设HUB_ATTACHMENT_TTL_SECONDS，范围60秒到7天；约每60秒清理。Nginx请求大小/超时仍可能更低，未做真实大文件测试。
- `PUT /api/attachments?recipient=ID&name=文件名&uploadKey=持久化唯一标识&sha256=小写64位哈希`：Bearer发送方token，Content-Type为文件类型，正文原始字节。uploadKey每发送方唯一1–128字符（字母数字._:-），重试复用同key和同文件元信息。返回id/sender/recipient/name/mime/size/sha256/created/expires/state/duplicate。过期/删除后相同key返回deleted状态，不重新建立附件；新业务必须新key。
- `GET /api/attachments/{id}`：发送方/接收方读取元信息；其他软件404。`GET .../download`仅指定接收方，使用Bearer，返回二进制，不接受任意URL。GET不会自动删，网络中断可重新完整下载；当前不支持Range断点续传。
- 接收方完整下载、校验size/SHA256并可靠保存到本地暂存区后，`POST .../complete`，JSON `{size,sha256}`；删除服务器加密文件并保留幂等墓碑。重复确认有效；错误hash/size不删，下载进行中409。此确认与消息ACK不同。
- `DELETE /api/attachments/{id}`发送方取消。删除软件清理相关附件；token轮换保持附件归属不变。
- Node.js22+辅助库 `/integration/attachment-client.mjs`：uploadAttachment、downloadAttachmentToFile、completeAttachment；流式文件读写，默认上传/下载5分钟，元数据确认15秒，可传AbortSignal。下载保存成功但确认失败时错误带downloadSaved/localPath，必须只重试complete，避免重复导入。
- 接收任务inbox先保存可信附件元信息/目标暂存路径，任务启动时若本地已完整保存则校验后只重试complete；不能在服务器删除后又无条件重新下载。导入笔记的成功回执与下载确认分开，导入失败可从本地暂存区重试。
- 不把token写进URL，不把图片base64放消息。名称等query不含凭据但可能进入访问日志，避免敏感文件名。mime是声明值，接收方必须验证实际格式，不执行HTML/脚本附件。默认上传时服务端限2个活动上传。
- 过期和确认删除是逻辑/文件删除，不承诺SSD/快照物理擦除。单机SQLite+文件不是跨资源原子事务，通过.part/原子重命名/墓碑/启动清理恢复孤儿文件。

在线判定：软件凭据认证成功的 HTTP 请求（例如发送、pull、ACK）或当前已认证 WSS 连接的 auth/ping/ACK 活动，在最近75秒内计为在线；建议每25秒心跳或轮询。仅登记软件不算在线。WS 正常断开后该连接不再计入，但近期 HTTP 活动仍可使软件在线。轮换 Token/注销立即清除活动状态。在线只表示近期通信，不代表业务健康或任务完成。仪表盘吞吐按分钟聚合最近2小时（含当前分钟），仅统计新入队消息，幂等重试不重复计数；服务重启清空。
