# 来源定位与最小证据摘录

记录日期：2026-11-07，UTC+08:00（日精度）。本文件为事后提取，未运行历史命令。

## 聊天定位

源文件：从 evidence/ 出发 `../../聊天记录.html`；HTML 内 `script#chatbox-export-data` 的 `messages` 数组共 85 条、forks 为 0。序号为 0-based，下列 ID 可在原文件中搜索。只索引相关消息，不复制全量聊天。

| 序号 | 消息 ID | 来源角色 |
|---|---|---|
| 1 | `1296476e-eeee-46d6-9b5e-d0607a16e356` | 用户 |
| 7 | `947675e7-bc5a-465c-b6ca-424f799439be` | 用户 |
| 8 | `003c0189-5c7d-4e1a-8000-39bb58c98b63` | 助手及其工具记录 |
| 25 | `3ea70152-978a-4309-a2c4-3d1cc5b73520` | 用户 |
| 27 | `6dd1c954-32d3-4b45-94ec-22e045241a65` | 用户 |
| 28 | `3645badd-d029-476c-86db-20f9efb0d254` | 助手及其工具记录 |
| 29 | `0172650d-3766-4840-a8eb-d7c39d6292ad` | 用户 |
| 31 | `540acc60-819d-4cea-a9ea-e6dc38b32fe0` | 用户 |
| 36 | `095d1cbc-4189-4ea7-a296-6ff8421a5d6a` | 助手及其工具记录 |
| 37 | `f89eeb5d-608c-4090-b6f8-f406397ba0f5` | 用户 |
| 52 | `bd639593-6a6e-4465-9f91-834eddd21687` | 用户 |
| 58 | `b675ebf4-8439-4e5d-b5b7-350f5bb50fb6` | 用户 |
| 59 | `3affe9e6-ff11-4fc1-a9c7-855b40d41dc0` | 助手及其工具记录 |
| 62 | `34b8a38d-5c12-4016-ba77-5c8f19b44aea` | 用户 |
| 63 | `197c3c3f-a0c4-432a-846c-1d06ff98cf52` | 助手及其工具记录 |
| 68 | `ac6d8dfb-7237-4ae3-bd77-530d920f0c18` | 用户 |
| 69 | `c55b1165-8245-4912-a547-f84c1e4d0cf5` | 助手及其工具记录 |
| 70 | `a4193f0e-df81-4b62-9259-f5a8810befaa` | 用户 |
| 71 | `ad545e25-2f36-4535-85c0-37dacc3b3a61` | 助手及其工具记录 |
| 72 | `a4c554cd-5073-4e4d-9637-883188719113` | 用户 |
| 73 | `8ba54266-f61b-4071-9d78-d3ba7bf452bc` | 助手及其工具记录 |
| 74 | `b22bf40b-b295-4b90-9123-42a9eb330d9b` | 用户 |
| 75 | `2e3805d1-d71e-4cc1-bdd8-bd4fa19ecf5c` | 助手及其工具记录 |
| 76 | `06905b96-4d32-43d2-a312-01ba2c378ff8` | 用户 |
| 78 | `41f11d12-613f-4fd4-97b2-a458bc02277b` | 用户 |
| 79 | `8f16242d-3b28-49fc-93cd-8b83d60557c1` | 助手及其工具记录 |
| 80 | `f13c4c13-8847-4392-8bc8-4c5e60c6cd5b` | 用户 |
| 81 | `314ef2ca-221f-41b5-90fa-f390b0bd2b8a` | 助手及其工具记录 |

## 历史输出摘录（非本次执行）

- 消息 #8：`Round-trip PASS: installer found; no bytecode included`
- 消息 #8：`PowerShell syntax PASS`
- 消息 #29：`Congratulations, all simulated renewals succeeded:`
- 消息 #63：`API docs PASS: strict CSP, no external requests/errors, schema rendering, filter, expand, mobile. Local only.`

这些摘录只保留非敏感成功标识；完整条件见 checks.md 与原消息。没有复制 token、服务器地址、邮箱或密钥。权限异常原始堆栈未取得，故不制造 PermissionError 摘录。

## 当前源文件指纹

下列 SHA-256 由本次本地读取实际生成，用于识别整理时的文件内容；不是提交 ID、数字签名或不可篡改时间证明，也不表示所有文件已测试。除聊天文件外，路径相对 webdev/。

| 文件 | SHA-256 |
|---|---|
| `../聊天记录.html` | `6ed8fe4accddf97a85b8379145239a0a360b05951d3425b3581895ca3e814de0` |
| `server.py` | `a42cd1e512ceb047b276e74f3f4553b923f783f20acd40cb706bcff2a36cd206` |
| `relay_attachments.py` | `924966dccee6b21898c2148015a4c535acb67c254a021bffa004f980cd072003` |
| `deploy/archive-tool.py` | `971becb4cd3eab30cafb9679b1db3552cf0da49192933504f6286d2a1b499296` |
| `deploy/update-ui.py` | `d8fc9589e3b0373c17ac197bc842c78f1fb5489d7df4634beb44fc378cb6b6cb` |
| `deploy/hub.service` | `055bff19fa2104aca0fd2c1604b80b206b29b2fb48606832a3b45e708c7844e4` |
| `integration/hub-sdk.mjs` | `059aca59aa43d2dac42ab181a39dd25acddff2f5887690a4a96d8609162648c0` |
| `integration/reliable_receiver.py` | `bbbdb1f99ac3dd41b193f4e099ac13a95c34bb013cf982982a6b9d92a2f7e554` |
| `integration/business_protocol.py` | `ca0f4e54609e3932bff13d0df38d3eca32dcee4013f509830dd2b4a5080b7f42` |
| `integration/business-protocol.mjs` | `a47bdeb38c9242764d1e9c7e64378d0d551c04d636a3d9adbd3c2b94271c95b8` |
| `integration/attachment-client.mjs` | `2f7700f9ad78f062eec0a404984780583bc817102b20c7af2ad846842826c484` |
| `test_hub.py` | `719b80d4e6915868788c15471507b65d46dcd8d2d2fc7b38bee0090f9e15e800` |
| `test_attachments.py` | `e02e7867201bc803e384b2fea3a612efa76980e90199be5f289a5bd9fb8a3853` |
| `test_attachment_client.mjs` | `2ec9b26ad6c3d27bc73cb194cd26fa9aed7f380abdd1a450a58ab1ba3a36f0cd` |
| `test_api_docs.py` | `094e5dcec6c4f84f6fdb47d60958fd8f4b51ac54f6887b564a838c95b8c67ad0` |

## 文档冲突处理

- 根 README 的“满十条淘汰”是旧契约：以当前 server.py 和稳定性审查最后“四项修复验收”节解释当前实现，保留旧文不覆写。
- 业务协议交付文档当时写“暂无附件 API”，后续临时附件工程已新增 API；并非本次发现附件模块缺失。
- 交接摘要将权限问题称为已定位根因；但原修复说明明确缺线上堆栈，本证据采用更保守的“确定的部署缺陷，线上根因尚未最终验证”。
- 本地测试通过、服务器 health 200、公网可访问、业务端到端成功是不同事实，分别记录。
