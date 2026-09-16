# API 扩展与演示边界

原始接口文档中的 113 条路径仍是核心业务契约。运行中的 OpenAPI 还包含以下追加接口，它们是后端实现所需的扩展，不会改变原始 113 条接口的路径和业务码：

| 接口 | 用途 | 访问范围 |
| --- | --- | --- |
| `POST /api/v1/app/agent/chat` | 用户侧只读业务 Agent | 登录用户，只能查询本人数据和公开站点 |
| `POST /api/v1/admin/agent/chat` | 运营侧只读业务 Agent | 登录运营账号，按 RBAC 检查工具权限 |
| `GET /api/v1/admin/observability` | 运行队列、延迟、错误和限流观测 | 管理端 dashboard 查看权限 |
| `POST /api/v1/device/telemetry` | 签名设备遥测接入 | 设备签名，不使用用户 Token |
| `GET /health` | 数据库和 Redis 健康检查 | 运维探针，无业务数据 |

Agent 的请求和回答详见 [Agent说明](agent.md)；设备接入为本地演示协议，生产环境需要替换设备密钥和接入层。OpenAPI 会明确列出这些扩展接口，便于联调时区分核心契约和实现扩展。

## 演示账号与验证码

推荐使用 README 中列出的密码登录演示账号。短信接口的响应只包含 `sent` 和 `expiresIn`，不会返回验证码；`DEMO_MODE=true` 只表示本地短信/支付/设备实现已启用，不意味着认证秘密会回显给客户端。

原始参考文档中后台账号示例密码 `123456` 不符合后端的 8 位最小长度校验；联调请使用 README 中的 `Admin123!`、`Operator123!` 或 `Maintainer123!`。
