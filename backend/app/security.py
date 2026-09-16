import os, secrets, hashlib, jwt, re
from datetime import timedelta
from pwdlib import PasswordHash
from redis import Redis
from sqlalchemy import select
from .common import *

cache = Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True, socket_timeout=3
)
passwords = PasswordHash.recommended()
SECRET = os.getenv("JWT_SECRET", "local-demo-only-change-this-secret-before-deploying")
DEMO = os.getenv("DEMO_MODE", "true").lower() == "true"
if not DEMO and SECRET.startswith("local-demo"):
    raise RuntimeError("Set a secure JWT_SECRET")


def rate_limit(key, limit, seconds):
    n = cache.eval(
        "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
        1,
        "rate:" + key,
        seconds,
    )
    require(n <= limit, 42900, "请求过于频繁，请稍后再试")


def permissions(db, aid):
    roles = [
        dict(r)
        for r in db.execute(
            select(m.role)
            .join(m.admin_role, m.admin_role.c.role_id == m.role.c.id)
            .where(m.admin_role.c.admin_user_id == aid, m.role.c.status == "ENABLED")
        ).mappings()
    ]
    ids = [r["id"] for r in roles]
    codes = list(
        db.scalars(
            select(m.permission.c.permission_code)
            .join(m.role_permission, m.role_permission.c.permission_id == m.permission.c.id)
            .where(m.role_permission.c.role_id.in_(ids))
            .distinct()
        )
    )
    return [r["role_code"] for r in roles], codes


def authenticate(db, request, scope):
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    try:
        claims = jwt.decode(
            token, SECRET, algorithms=["HS256"], options={"require": ["exp", "sub", "scope", "ver"]}
        )
        require(claims["scope"] == scope, 40300, "无权限")
        u = get(db, m.admin if scope == "admin" else m.user, claims["sub"])
        require(u["token_version"] == claims["ver"], 40001, "登录已失效")
        require(u["status"] == ("ENABLED" if scope == "admin" else "NORMAL"), 40001, "账号不可用")
    except (jwt.PyJWTError, KeyError, ValueError):
        raise BizError(40001, "未登录或登录已失效")
    if scope == "admin":
        u["roles"], u["permissions"] = permissions(db, u["id"])
    return u


def auth_action(db, scope, path, b, request):
    is_admin = scope == "admin"
    t = m.admin if is_admin else m.user
    if path == "auth/sms-code":
        require(not is_admin)
        phone = b.get("phone", "")
        require(re.fullmatch(r"1\d{10}", phone), message="请输入正确手机号")
        rate_limit("sms:" + phone, 1, 60)
        rate_limit("sms-ip:" + request.client.host, 20, 3600)
        require(DEMO, 50300, "短信服务未配置")
        code = str(secrets.randbelow(900000) + 100000)
        cache.setex("sms:" + phone, 300, hashlib.sha256(code.encode()).hexdigest())
        return {"sent": True, "expires_in": 300, "demo_code": code}
    if path == "auth/login":
        account = b.get("username" if is_admin else "phone", "")
        method = "PASSWORD" if is_admin else b.get("loginMethod")
        require(
            method in ("PASSWORD", "SMS_CODE") and isinstance(account, str) and len(account) <= 64
        )
        rate_limit("login:" + request.client.host, 60, 60)
        if is_admin:
            rate_limit("admin-login:" + account, 10, 60)
        u = one(
            db, t, (t.c.username if is_admin else t.c.phone) == account, lock=True, required=False
        )
        log = {
            "account_type": "ADMIN" if is_admin else "USER",
            "account_id": u["id"] if u else None,
            "phone_or_username": account,
            "login_method": method,
            "ip_address": request.client.host,
            "device_info": request.headers.get("user-agent", "")[:1000],
        }

        def fail(code, msg):
            add(db, m.login_log, **log, result="FAILED", fail_reason=msg)
            raise BizError(code, msg, persist=True)

        if u and not is_admin:
            if u["manual_locked"]:
                fail(40003, "账号已人工锁定，请联系管理员")
            if u["lock_until"] and u["lock_until"] > now():
                fail(40002, "账号临时锁定，请稍后重试")
        if u and u["status"] not in ("NORMAL", "ENABLED"):
            fail(40300, "账号已停用")
        if method == "PASSWORD":
            valid = False
            if u and u.get("password_hash"):
                try:
                    valid = passwords.verify(str(b.get("password", "")), u["password_hash"])
                except Exception:
                    valid = False
            if not valid:
                if u and not is_admin:
                    n = u["failed_login_count"] + 1
                    change(
                        db,
                        t,
                        u["id"],
                        failed_login_count=n,
                        lock_until=now() + timedelta(seconds=min(300, 30 * n)),
                        manual_locked=n >= 6,
                        status="LOCKED" if n >= 6 else "NORMAL",
                        lock_reason="连续密码错误" if n >= 6 else None,
                        token_version=u["token_version"] + (1 if n >= 6 else 0),
                    )
                    fail(
                        40003 if n >= 6 else 40002,
                        "密码错误，账号已人工锁定"
                        if n >= 6
                        else f"密码错误，临时锁定{min(300, 30 * n)}秒",
                    )
                fail(40001, "账号或密码错误")
        else:
            actual = hashlib.sha256(str(b.get("smsCode", "")).encode()).hexdigest()
            valid = cache.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then redis.call('DEL',KEYS[1]); return 1 end; return 0",
                1,
                "sms:" + account,
                actual,
            )
            if not valid:
                fail(40004, "验证码错误或已失效")
            if not u:
                require(re.fullmatch(r"1\d{10}", account))
                u = add(db, t, phone=account, nickname="车主" + account[-4:])
                log["account_id"] = u["id"]
        u = change(
            db,
            t,
            u["id"],
            **(
                {"last_login_at": now()}
                if is_admin
                else {"failed_login_count": 0, "lock_until": None}
            ),
        )
        add(db, m.login_log, **log, result="SUCCESS")
        token = jwt.encode(
            {
                "sub": str(u["id"]),
                "scope": scope,
                "ver": u["token_version"],
                "exp": now() + timedelta(hours=2),
            },
            SECRET,
            algorithm="HS256",
        )
        info = public_user(u)
        if is_admin:
            info["roles"], info["permissions"] = permissions(db, u["id"])
        return {"access_token": token, "expires_in": 7200, "admin" if is_admin else "user": info}
    u = authenticate(db, request, scope)
    u = get(db, t, u["id"], lock=True)
    if path == "auth/logout":
        change(db, t, u["id"], token_version=u["token_version"] + 1)
        return None
    if path == "auth/password":
        require(
            not is_admin
            and isinstance(b.get("newPassword"), str)
            and 8 <= len(b["newPassword"]) <= 128,
            message="新密码需8~128位",
        )
        require(
            u["password_hash"] and passwords.verify(b.get("oldPassword", ""), u["password_hash"]),
            40001,
            "原密码错误",
        )
        change(
            db,
            t,
            u["id"],
            password_hash=passwords.hash(b["newPassword"]),
            token_version=u["token_version"] + 1,
        )
        return None
    raise BizError(40400, "接口不存在")
