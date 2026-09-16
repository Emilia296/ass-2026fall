# Electra 智能充电桩运营服务平台

本轮交付后端。需求来源为根目录的 `原始需求.txt`、`接口文档.md`、`数据库.md`；前端参考文档和图片保留，前端按用户要求留待后续实现。

后端使用 Python 3.12、FastAPI、SQLAlchemy 2、PostgreSQL 16、Redis 7。包含文档中的 **113 个业务接口、33 张业务表**，以及一个运营人员登记故障接口、一个设备遥测接口和健康检查接口。所有业务响应使用统一包装和 camelCase 字段。

## 本机 WSL2 运行

当前开发环境是 Windows 的 `CodexUbuntu`（WSL2），项目映射路径 `/mnt/e/ass-2026fall`，Python 环境在 `/home/dev/charge-venv`。

首次准备环境，在 WSL 中运行：

```bash
cd /mnt/e/ass-2026fall
bash scripts/setup-wsl.sh
bash scripts/run-backend.sh
```

Windows PowerShell 可直接启动：

```powershell
wsl -d CodexUbuntu -- bash /mnt/e/ass-2026fall/scripts/run-backend.sh
```

保持该进程运行，按 Ctrl+C 同时停止 API、后台任务和模拟器。数据库和 Redis 由 WSL 服务管理。日志位于 `.runtime/api.log`、`.runtime/worker.log`、`.runtime/simulator.log`。

- API 文档：<http://localhost:8080/docs>
- OpenAPI：<http://localhost:8080/openapi.json>
- 健康检查：<http://localhost:8080/health>
- 用户 API：`/api/v1/app`
- 管理 API：`/api/v1/admin`

开发示例账号：

| 角色 | 账号 | 密码 |
|---|---|---|
| 用户 | `13800138000` | `User123!` |
| 第二个用户 | `13800138001` | `User123!` |
| 管理员 | `admin` | `Admin123!` |
| 运营人员 | `operator` | `Operator123!` |
| 运维人员 | `maintainer` | `Maintainer123!` |

默认车辆 ID 为 1、2；第一个可用充电桩 ID 为 1，二维码内容 `PILE:BJ-001-001`。初始化不会清空已有数据；演示初始化检测到后台账号后不会重复灌入示例数据。

## 功能验收路径

1. 用户密码登录，复制 `data.accessToken`；Swagger 右上角 Authorize 中填写 Token。
2. 查询站点、车辆和扫码设备，使用 `vehicleId=1, pileId=1, targetSoc=80` 创建充电会话。
3. 每两秒设备模拟器经过真实 Redis 入队和消费链路更新电量；查询当前会话可查看电量、费用和功率。
4. 停止充电，查看免费驶离截止时间，再调用驶离接口生成订单。
5. 积分兑换优惠券、订单试算及模拟支付。金额较小时不满足满减门槛是正常行为，短时间充电可能四舍五入为 0 元。
6. 申请售后，管理员审核模拟退款。退款保留支付关联、金额和优惠券返还记录。
7. 另可验收预约到场、取消和超时、空闲提醒、收藏、消息软删除、故障接单处理、权限配置及审计日志。

分时价格必须完整覆盖 `00:00–24:00`，不允许重叠或缺口；接口文档中只展示部分时段的示例需要补全再提交。占桩费固定为前30分钟免费、31–60分钟0.1元/分钟、61分钟起0.2元/分钟，支持规则中的费用封顶。

## 测试

```bash
cd /mnt/e/ass-2026fall
bash scripts/test-backend.sh
```

测试使用独立 PostgreSQL 数据库 `charge_test` 和 Redis DB 15，运行时会清空这两个**测试专用**存储；测试代码检查数据库名和 Redis DB 号，拒绝清空业务库。首次建库由 setup 脚本完成。可以通过 `TEST_DATABASE_URL` 指定名称以 `_test` 结尾的专用库。

验证覆盖功能链路、真实数据库事务、两个请求之间的并发竞争、金额边界、访问控制和队列重试，不包含压力测试或容量认证。详见 [后端验收报告](docs/backend-acceptance.md)。

## 项目结构

```text
backend/app/models.py       33张业务表、外键、唯一约束、索引
backend/app/main.py         HTTP入口、统一错误处理、OpenAPI、审计
backend/app/security.py     登录、Argon2、JWT版本失效、限流、RBAC
backend/app/app_api.py      用户业务接口
backend/app/admin_api.py    运营管理接口
backend/app/charging.py     充电状态机、计量、结算
backend/app/billing.py      分时电费/服务费及占桩费计算
backend/app/benefits.py     优惠券、积分、支付、退款
backend/app/catalog.py      站点聚合、距离查询、订单详情
backend/app/telemetry.py    签名校验、分区队列、重试、死信
backend/app/worker.py       异步消费、预约/欠费/消息/信誉维护
backend/app/simulator.py    设备模拟器
backend/app/validation.py   请求约束和OpenAPI请求结构
backend/migrations/        可直接执行的PostgreSQL建表SQL
backend/api-contract.json  从原接口文档提取的113个接口清单
backend/tests/             自动化验收
```

## 配置和部署边界

可复制 `backend/.env.example` 为 `backend/.env` 修改连接配置。`DEMO_MODE=true` 时，短信接口返回 `demoCode` 供本机验收，支付渠道全部走模拟支付，设备由模拟器上报。没有真实短信供应商、微信/支付宝支付或充电桩协议对接；这些本来不在 V1.1 接口范围内。已追加轻量业务 Agent，提供真实数据查询和多工具运营报告，详见 [Agent说明](docs/agent.md)。

提供 `compose.yaml` 便于后续容器部署：`docker compose up --build`。容器配置为开发演示用途，本轮验证使用 WSL 原生服务，没有运行 Docker 构建。生产模式 `DEMO_MODE=false` 会拒绝示例 JWT/设备密钥和短信模拟发送；需要实际接入提供商后才可作为生产服务使用。

架构实现及并发边界见 [后端架构说明](docs/backend-architecture.md)。**未做压力测试，不声明达到原始需求中的具体 QPS 或千万用户容量指标。**

高并发方案采用多实例网关、请求限流、数据库事务约束、共享缓存与回源互斥、分区异步消费、队列背压及运行观测。验证方式采用后续公测，**不安排独立压力测试**。方案实现与实际容量是两项结果，项目说明采用：“已实现面向目标规模的高并发架构，实际承载能力通过公测持续验证。”

公测部署拓扑与记录方式见 [公测验证说明](docs/public-test.md)。管理员运行指标接口：`GET /api/v1/admin/observability`。
