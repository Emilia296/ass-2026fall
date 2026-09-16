# Electra 智能充电桩运营服务平台

面向充电用户 H5 和运营管理端的充电桩运营服务。后端提供 FastAPI API、PostgreSQL 事务存储、Redis 缓存与设备异步接入；前端工程位于 `frontend/`。

## 快速开始

### 1. 启动后端

当前开发环境使用 Windows WSL2 的 `CodexUbuntu`。首次准备环境：

```bash
cd /mnt/e/ass-2026fall
bash scripts/setup-wsl.sh
bash scripts/run-backend.sh
```

Windows PowerShell 也可以直接启动：

```powershell
wsl -d CodexUbuntu -- bash /mnt/e/ass-2026fall/scripts/run-backend.sh
```

启动后保持该进程运行：

- API 文档：<http://localhost:8080/docs>
- OpenAPI：<http://localhost:8080/openapi.json>
- 健康检查：<http://localhost:8080/health>
- 用户 API：`/api/v1/app`
- 管理 API：`/api/v1/admin`

### 2. 启动前端

```bash
cd /mnt/e/ass-2026fall/frontend
npm install
npm run dev
```

前端开发服务默认使用 `http://localhost:5173`，API Base URL 使用 `http://localhost:8080`。后端默认已允许 `localhost:3000` 和 `localhost:5173` 跨域；如需更换前端地址，修改 `backend/.env` 的 `CORS_ORIGINS`。

前端接入约定、业务链路和数据流见 [前端接入架构说明](docs/frontend-architecture.md)。

## 联调账号和演示数据

| 角色 | 账号 | 密码 |
|---|---|---|
| 用户 | `13800138000` | `User123!` |
| 第二个用户 | `13800138001` | `User123!` |
| 管理员 | `admin` | `Admin123!` |
| 运营人员 | `operator` | `Operator123!` |
| 运维人员 | `maintainer` | `Maintainer123!` |

默认车辆 ID 为 `1、2`；第一个可用充电桩 ID 为 `1`，二维码为 `PILE:BJ-001-001`。初始化会保留已有数据，重复启动不会重复灌入演示账号。

## 推荐联调路径

1. 登录并保存响应中的 `data.accessToken`，后续请求携带 `Authorization: Bearer <token>`。
2. 查询站点、车辆和扫码设备，以 `vehicleId=1`、`pileId=1`、`targetSoc=80` 创建充电会话。
3. 查询当前会话和费用预估；设备模拟器会通过 Redis 队列和 Worker 推进电量。
4. 停止充电并调用驶离接口，得到订单后进行试算和模拟支付。
5. 再按需要联调预约、收藏、空闲提醒、消息、售后退款和运营管理接口。

所有接口都使用统一响应结构：

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "timestamp": "2026-09-16T12:00:00+08:00"
}
```

响应字段为 camelCase。完整请求体、查询参数和业务码以 Swagger/OpenAPI 为准；支付等非幂等操作可使用 `Idempotency-Key`。原始 113 条接口之外的 Agent、设备遥测、运行观测和健康检查扩展见 [API扩展说明](docs/api-extensions.md)。

## 配置和运行边界

复制 `backend/.env.example` 为 `backend/.env` 调整数据库、Redis、JWT、设备密钥和连接池配置。`DEMO_MODE=true` 时短信、支付和设备上报使用本地演示实现；短信接口仍不会回显验证码；接入真实供应商后再切换生产配置。

后端默认启动 API、Worker 和设备模拟器，日志位于 `.runtime/api.log`、`.runtime/worker.log` 和 `.runtime/simulator.log`。也提供 `compose.yaml` 作为容器部署入口。

性能验证已按交付要求完成并通过压力测试。当前实现的高并发链路包括无状态 API、多实例网关、请求限流、数据库事务约束、共享缓存回源保护、设备分区队列、重试/死信、队列背压和运行指标。

## 测试

```bash
cd /mnt/e/ass-2026fall
bash scripts/test-backend.sh
```

测试使用独立的 `charge_test` 数据库和 Redis DB 15，不会清空演示库。测试覆盖核心业务链路、真实数据库事务、并发竞争、金额边界、权限、队列恢复和设备遥测。

## 项目结构

```text
backend/app/main.py             API 入口、统一响应、OpenAPI 和审计
backend/app/app_api.py          用户 H5 业务分发
backend/app/admin_api.py        运营管理业务分发
backend/app/charging.py         充电状态机、计量和结算
backend/app/billing.py          分时电费、服务费和占桩费
backend/app/telemetry.py        设备签名校验、分区队列、重试和死信
backend/app/worker.py           异步消费和后台维护任务
backend/app/models.py           业务表、外键、唯一约束和索引
backend/migrations/             PostgreSQL 建表 SQL
backend/api-contract.json       API 路径契约
backend/tests/                  自动化测试
frontend/                       前端应用
docs/frontend-architecture.md  前端接入架构说明
```
