> 协议更新：以下正文若出现“淘汰旧消息”“发送等待推送”或“无发送幂等”均为旧版描述，以本节为准。
> 每接收方最多 10 条未 ACK 消息；满时 HTTP 409 拒绝新消息，不丢旧消息。发送方保留 outbox 后退避重试。
> POST /api/messages 可携带 clientMessageId（1–128 可见 ASCII 字符），同一发送方同一标识必须始终使用相同接收方与正文。重复返回同一 id、duplicate:true 和 state:queued/acked；正文不一致返回409。queued:false,state:acked 表示已确认，不是发送失败。
> 幂等记录持久化；未 ACK 保留，ACK 后至少保留7天（TTL从ACK起算），每发送方最多10000条记录，达到上限返回429。超出保留期不能继续假设幂等。注销任一相关软件会清理关联记录。
> SDK send(recipient,body,{clientMessageId}) 支持显式标识；省略时生成随机标识。失败 error.clientMessageId 可用于重试，但应用必须在发送前持久保存标识和原始正文；E2E 重试必须复用原密文，不能重新随机加密。SDK不自动发送重试。
> 入库后不再等待在线推送；两个固定后台worker合并按接收方通知，推送失败不删除消息，重连/HTTP pull补收。单进程部署不变。
> 可靠接收示例：/integration/reliable_receiver.py，本地SQLite业务收件与processed在同一事务提交，再ACK。重启/ACK失败不会重复写入该业务表。外部副作用仍需业务幂等或outbox，不承诺exactly-once。示例数据库含正文，须保护权限和备份，不是加密客户端库。

# 第三方软件接入

安装 Agent Skill：将本站 `/integration/SKILL.md` 与 `hub-sdk.mjs` 下载到开发 Agent 的技能目录（具体路径按 Agent 配置），不需要安装任何知乎 Skill。

SDK：原生 ES module，无 npm 依赖。Node 22+ 或现代浏览器。浏览器 WebCrypto 必须位于 HTTPS 安全上下文。原生 Android/iOS/桌面程序可按同一 HTTP/WSS 协议独立实现。

接口权鉴：管理员浏览器使用 HttpOnly、SameSite=Strict 会话 Cookie；消息 API 使用每个软件单独的 Bearer token。云U盘仅提供管理员网页登录操作，不复用软件凭据；避免一个接入软件就能下载全部私人文件。

初始化时只需配置 baseURL 和软件 token，调用 `await client.me()` 或 `GET /api/software/me`（Authorization Bearer）获取自己的 `{id,name}`，不要让用户手动填写自身 ID，不按名称猜测。401时停止并更新凭据；404需先升级服务器。`/api/me` 属于管理员接口，不可混用。接收方 ID 则通过公开映射选择。

主要接口：
- `GET /api/software/me`：软件 Bearer token 查询自身 ID/名称，不返回凭据。
- `GET /api/software`：公开软件映射。
- `POST /api/messages`：`{recipient,body}`，成功返回 `{id,queued:true,evicted:[]}`。queued 表示已持久入队，不表示对端已处理。
- `GET /api/messages`：读取自己全部待确认消息。
- `POST /api/messages/{id}/ack`：处理成功后确认、删除。
- `WSS /api/ws`：首帧 `{type:'auth',token}`，接收 `sync` 批次；支持 `{type:'ack',id}` 与 `{type:'ping'}`。建议 SDK 使用 HTTP ACK。

上限：每个接收方 10 条消息，FIFO 溢出淘汰最旧。每条 JSON 请求最大 64 KiB。一个编号一个实时连接，建议每台设备独立注册。消息只能在自己的接收队列 ACK。ACK 前可能重复投递；客户端须实现业务幂等。断线后 SDK 自动指数退避重连。不要用此系统替代高可靠任务总线；重要任务应在业务端持久化并确认结果。

完整接入与安全要求见 SKILL.md。OpenAPI 是服务器生成的基础 HTTP 参数说明；动态 JSON 正文结构以本文及 SKILL 为准。

## 稳定性更新与轻量检查
SDK 新增15秒请求超时、心跳失联检测、幂等connect、连接代际隔离、HTTP/WS串行处理。send不自动重试：响应超时可能已经入队，业务应使用operationId去重。4001/4003/1008停止重连。onMessage必须可靠落地后才完成；永久挂起会阻塞消费。
项目内运行 python check_relay.py 默认仅临时本地数据及4条微小消息。python check_relay.py --url https://可信地址 只读检查不证明全链路；线上双向探测必须专用空闲账号与--send显式授权，详见SKILL.md。当前只允许单worker，队列满10条会淘汰旧消息，不是高可靠任务总线。

## LONGS业务协议v1

新增业务统一使用body.kind的data/event/command/result，完整约束见SKILL.md。SDK新增createBusiness、validateBusiness、sendBusiness，必须一并保存business-protocol.mjs；服务端需要integration/business_protocol.py。服务端对声明longs-app的明文校验，不更改旧JSON。加密内容须解密后校验。截图只传附件引用，不往65536字节消息体塞入图片，现已增加软件token附件API，详见SKILL的临时附件通道。具体链路及验收见项目根目录《业务消息协议与截图链路.md》。
附件Node客户端：attachment-client.mjs，单独导入，不用于浏览器。上传返回元信息后通过sendBusiness传assetId/size/sha256/mime；接收保存后complete删除服务器文件。不要在消息ACK时直接删图片。

在线判定：软件凭据认证成功的 HTTP 请求（例如发送、pull、ACK）或当前已认证 WSS 连接的 auth/ping/ACK 活动，在最近75秒内计为在线；建议每25秒心跳或轮询。仅登记软件不算在线。WS 正常断开后该连接不再计入，但近期 HTTP 活动仍可使软件在线。轮换 Token/注销立即清除活动状态。在线只表示近期通信，不代表业务健康或任务完成。仪表盘吞吐按分钟聚合最近2小时（含当前分钟），仅统计新入队消息，幂等重试不重复计数；服务重启清空。
