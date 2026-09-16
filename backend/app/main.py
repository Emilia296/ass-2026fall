import json, logging, os, hashlib
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import (
    IntegrityError,
    OperationalError,
    DataError,
    TimeoutError as PoolTimeoutError,
)
from redis.exceptions import RedisError
from .db import Session, now
from .common import *
from .security import authenticate, auth_action, cache, rate_limit
from . import app_api, admin_api
from .validation import validate, schema_for

app = FastAPI(
    title="Electra 智能充电运营平台",
    version="1.1.0",
    description="H5 / 运营管理 API；短信、支付、设备为明确标识的模拟接入。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(
        ","
    ),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


def response(data=None, code=0, message="success", status=200):
    return JSONResponse(
        {"code": code, "message": message, "data": serial(data), "timestamp": now().isoformat()},
        status_code=status,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return response(
        code=40400 if exc.status_code == 404 else 40000,
        message="接口不存在" if exc.status_code == 404 else "请求方法或格式错误",
        status=exc.status_code,
    )


def sanitize(v):
    if isinstance(v, dict):
        return {
            k: sanitize(x)
            for k, x in v.items()
            if not any(
                secret in k.lower() for secret in ("password", "token", "smscode", "signature")
            )
        }
    if isinstance(v, list):
        return [sanitize(x) for x in v]
    return v


def app_public(v):
    if isinstance(v, dict):
        return {
            k: app_public(x)
            for k, x in v.items()
            if k
            not in (
                "credit_penalty_applied",
                "password_hash",
                "failed_login_count",
                "manual_locked",
                "lock_reason",
                "token_version",
                "lock_until",
                "meter_sequence",
                "price_snapshot",
                "occupancy_snapshot",
                "fee_segments",
            )
        }
    if isinstance(v, list):
        return [app_public(x) for x in v]
    return v


def process(request, body):
    scope = request.path_params.get("scope") or request.url.path.split("/")[3]
    path = "/".join(request.url.path.split("/")[4:])
    method = request.method
    q = dict(request.query_params)
    db = Session()
    u = None
    before = None
    try:
        for name, value in request.path_params.items():
            if name != "configKey":
                require(str(value).isdigit() and int(value) > 0, message=f"{name}必须为正整数")
        validate(request.url.path, method, body)
        if path.startswith("auth/"):
            data = auth_action(db, scope, path, body, request)
        else:
            u = authenticate(db, request, scope)
            if scope == "admin":
                admin_api.authorize(u, method, path)
                parts = path.split("/")
                table = admin_api.TABLES.get(parts[0])
                if method != "GET" and table is not None and len(parts) > 1 and parts[1].isdigit():
                    before = one(db, table, table.c.id == int(parts[1]), required=False)
                data = admin_api.dispatch(db, u, method, path, body, q)
                if method != "GET":
                    add(
                        db,
                        m.audit,
                        admin_id=u["id"],
                        role_name=",".join(u["roles"]),
                        module=parts[0],
                        operation_type=method,
                        target_type=parts[0],
                        target_id=int(parts[1])
                        if len(parts) > 1 and parts[1].isdigit()
                        else data.get("id")
                        if isinstance(data, dict)
                        else None,
                        before_data=serial(sanitize(before)),
                        after_data=serial(sanitize(data)),
                        reason=body.get("reason")
                        or body.get("handleResult")
                        or body.get("handleNote"),
                        result="SUCCESS",
                    )
            else:
                # Cache only public station lists, never personalized objects; short TTL bounds status staleness.
                cache_key = None
                if method == "GET" and path == "stations":
                    cache_key = (
                        "catalog:"
                        + hashlib.sha256(json.dumps(q, sort_keys=True).encode()).hexdigest()
                    )
                    cached = cache.get(cache_key)
                    if cached is not None:
                        return response(json.loads(cached))
                data = app_api.dispatch(db, u, method, path, body, q)
                if cache_key:
                    cache.setex(cache_key, 2, json.dumps(serial(data)))
        if isinstance(data, dict) and method != "GET":
            aliases = {
                "stations": "station_id",
                "piles": "pile_id",
                "vehicles": "vehicle_id",
                "reservations": "reservation_id",
                "messages": "message_id",
                "faults": "fault_id",
                "after-sales": "after_sales_id",
                "users": "user_id",
                "roles": "role_id",
                "coupon-templates": "template_id",
                "price-plans": "plan_id",
            }
            alias = aliases.get(path.split("/")[0])
            if alias and "id" in data:
                data.setdefault(alias, data["id"])
            if path.startswith("messages/") and method == "DELETE":
                data["deleted"] = True
            if scope == "admin" and path.endswith("/unlock"):
                data["failed_login_count"] = 0
        db.commit()
        return response(app_public(data) if scope == "app" else data)
    except BizError as exc:
        if exc.persist:
            db.commit()
        else:
            db.rollback()
        if scope == "admin" and u and method != "GET":
            try:
                add(
                    db,
                    m.audit,
                    admin_id=u["id"],
                    role_name=",".join(u.get("roles", [])),
                    module=path.split("/")[0],
                    operation_type=method,
                    target_type=path,
                    before_data=serial(sanitize(before)),
                    after_data={"error": exc.message},
                    reason=body.get("reason"),
                    result="FAILED",
                )
                db.commit()
            except Exception:
                db.rollback()
        status = (
            401
            if exc.code in (40001, 40002, 40003)
            else 403
            if exc.code == 40300
            else 404
            if exc.code == 40400
            else 429
            if exc.code == 42900
            else 503
            if exc.code == 50300
            else 409
            if exc.code in (40900, 40901, 41002, 41003, 42001, 43003, 44002)
            else 400
        )
        return response(code=exc.code, message=exc.message, status=status)
    except IntegrityError:
        db.rollback()
        return response(
            code=40900, message="数据冲突，请检查唯一值、关联资源和数据范围", status=409
        )
    except (KeyError, ValueError, TypeError, ArithmeticError, DataError) as exc:
        db.rollback()
        logging.info("Invalid request: %s", exc)
        return response(code=40000, message="请求参数缺失或格式错误", status=400)
    except (OperationalError, PoolTimeoutError, RedisError):
        db.rollback()
        logging.exception("Dependency unavailable")
        return response(code=50300, message="服务暂时繁忙，请稍后重试", status=503)
    except Exception:
        db.rollback()
        logging.exception("Unhandled API exception")
        return response(code=50000, message="服务内部错误", status=500)
    finally:
        db.close()


async def endpoint(request: Request):
    raw = await request.body()
    if len(raw) > 1048576:
        return response(code=40000, message="请求体过大", status=413)
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        return response(code=40000, message="JSON格式错误", status=400)
    if not isinstance(body, dict):
        return response(code=40000, message="请求体必须为对象", status=400)
    return await run_in_threadpool(process, request, body)


contract = json.loads((Path(__file__).parent.parent / "api-contract.json").read_text())
for item in contract:
    import re

    parameters = [
        {
            "name": p,
            "in": "path",
            "required": True,
            "schema": {"type": "string" if p == "configKey" else "integer"},
        }
        for p in re.findall(r"\{([^}]+)\}", item["path"])
    ]
    extra = {"parameters": parameters}
    if item["method"] in ("POST", "PUT"):
        extra["requestBody"] = {
            "content": {"application/json": {"schema": schema_for(item["path"], item["method"])}}
        }
    if "/auth/login" not in item["path"] and "/auth/sms-code" not in item["path"]:
        extra["security"] = [{"BearerAuth": []}]
    app.add_api_route(
        item["path"],
        endpoint,
        methods=[item["method"]],
        tags=["运营管理" if "/admin/" in item["path"] else "用户H5"],
        name=item["title"],
        operation_id=item["method"].lower()
        + "_"
        + item["path"].replace("/", "_").replace("{", "").replace("}", ""),
        openapi_extra=extra,
    )
# Original requirement includes operator-entered faults; this is a documented additive endpoint.
app.add_api_route(
    "/api/v1/admin/faults", endpoint, methods=["POST"], tags=["运营管理"], name="运营人员登记故障"
)


@app.post("/api/v1/device/telemetry", tags=["设备接入"])
async def device_telemetry(request: Request):
    from .telemetry import ingest

    try:
        raw = await request.body()
        require(len(raw) <= 1048576)
        data = json.loads(raw)
        result = await run_in_threadpool(ingest, data.get("events"))
        return response(result)
    except BizError as exc:
        return response(
            code=exc.code,
            message=exc.message,
            status=403 if exc.code == 40300 else 503 if exc.code == 50300 else 400,
        )
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return response(code=40000, message="设备数据格式错误", status=400)
    except RedisError:
        return response(code=50300, message="设备队列暂不可用，请重试", status=503)


@app.get("/health", tags=["运维"])
def health():
    try:
        with Session() as db:
            db.execute(select(1))
        cache.ping()
        return response({"database": "ok", "redis": "ok"})
    except Exception:
        return response(code=50300, message="依赖服务不可用", status=503)


original_openapi = app.openapi


def openapi():
    schema = original_openapi()
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    return schema


app.openapi = openapi
