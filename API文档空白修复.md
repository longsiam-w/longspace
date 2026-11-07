# /api/docs 空白修复

线上只读核实：HTTPS /api/docs 返回 200、HTML 1018 字节，严格 CSP 包含 script-src 'self' / style-src 'self'。默认 FastAPI Swagger UI 使用 CDN 脚本/样式和内联初始化，不兼容本站策略。

修复：关闭默认 Swagger UI，在相同 /api/docs 路径提供本站 HTML + 外部同源 JS，读取 /api/openapi.json 渲染接口、参数、响应和 schemas。支持搜索、展开、失败重试和手机布局；不依赖 CDN，不放宽 CSP，不自动调用业务接口。不提供 Swagger Try it out。手工解析 JSON 的接口仍需结合 /guide 与 integration/SKILL.md 获取完整请求体说明。

新增 web/api-docs.html、web/api-docs.js、test_api_docs.py；更新 server.py 路由/静态白名单、web/style.css、deploy/update-ui.py 资源列表及新旧白名单兼容检测。

本地验收：test_api_docs.py 通过（严格 CSP、无外部请求、无控制台错误、渲染、筛选、展开、390px 无横向溢出），test_hub.py 6 组通过。已查看手机截图。无线上写入或部署，无压力测试。

部署：在项目目录执行 powershell -ExecutionPolicy Bypass -File .\deploy\Update-Ui.ps1，输入 UPDATE，在终端输入 SSH 密码。会更新 server.py 并重启，需重新登录。部署后访问 /api/docs 并强制刷新；未部署前线上仍是旧版空白页。
