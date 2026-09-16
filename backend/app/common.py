import re, uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select, insert, update, func, String, Boolean, BigInteger, Numeric, DateTime
from . import models as m
from .db import now


class BizError(Exception):
    def __init__(self, code=40000, message="请求参数错误", persist=False):
        self.code, self.message, self.persist = code, message, persist


def require(ok, code=40000, message="请求参数错误"):
    if not ok:
        raise BizError(code, message)


def snake(s):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def camel(s):
    a = s.split("_")
    return a[0] + "".join(x.title() for x in a[1:])


def serial(value):
    if isinstance(value, dict):
        return {camel(k): serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def number(prefix):
    return prefix + now().strftime("%Y%m%d") + uuid.uuid4().hex[:18].upper()


def rows(db, t, *conditions):
    return [dict(r) for r in db.execute(select(t).where(*conditions)).mappings()]


def one(db, t, *conditions, lock=False, required=True):
    stmt = select(t).where(*conditions)
    if lock:
        stmt = stmt.with_for_update()
    r = db.execute(stmt).mappings().first()
    if r is None:
        if required:
            raise BizError(40400, "资源不存在")
        return None
    return dict(r)


def get(db, t, id, uid=None, lock=False):
    cond = [t.c.id == int(id)]
    if uid is not None:
        cond.append(t.c.user_id == uid)
    return one(db, t, *cond, lock=lock)


def add(db, t, **data):
    return dict(db.execute(insert(t).values(**data).returning(t)).mappings().one())


def change(db, t, id, **data):
    if "updated_at" in t.c:
        data["updated_at"] = now()
    return dict(
        db.execute(update(t).where(t.c.id == id).values(**data).returning(t)).mappings().one()
    )


def count(db, t, *cond):
    return db.scalar(select(func.count()).select_from(t).where(*cond))


def dt(v):
    if isinstance(v, datetime):
        return v
    result = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return result.replace(tzinfo=now().tzinfo) if result.tzinfo is None else result


def money(v):
    return Decimal(str(v)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def payload(t, b, allowed=None, create=False):
    result = {}
    for key, v in b.items():
        k = snake(key)
        if (
            k not in t.c
            or k in ("id", "created_at", "updated_at")
            or allowed is not None
            and k not in allowed
        ):
            continue
        c = t.c[k]
        if v is None:
            require(c.nullable, message=f"{key}不能为空")
            result[k] = None
            continue
        try:
            if isinstance(c.type, Boolean):
                require(type(v) is bool, message=f"{key}必须为布尔值")
            elif isinstance(c.type, BigInteger):
                require(
                    not isinstance(v, bool) and Decimal(str(v)) == int(v),
                    message=f"{key}必须为整数",
                )
                v = int(v)
            elif isinstance(c.type, Numeric):
                v = Decimal(str(v))
                require(v.is_finite(), message=f"{key}必须为有限数字")
            elif isinstance(c.type, DateTime):
                v = dt(v)
            elif isinstance(c.type, String):
                require(
                    isinstance(v, str) and len(v) <= (c.type.length or 10000),
                    message=f"{key}格式错误或长度超限",
                )
        except (ValueError, TypeError, ArithmeticError):
            raise BizError(message=f"{key}格式错误")
        result[k] = v
    if create:
        for c in t.c:
            if c.name not in ("id", "created_at") and not c.nullable and c.default is None:
                require(c.name in result, message=f"缺少{camel(c.name)}")
    return result


def public_user(u, admin=False):
    hidden = {"password_hash", "token_version", "failed_login_count"}
    if not admin:
        hidden |= {"manual_locked", "lock_until", "lock_reason"}
    return {k: v for k, v in u.items() if k not in hidden}


def notify(db, uid, kind, title, content="", biz="SYSTEM", id=None):
    return add(
        db,
        m.message,
        user_id=uid,
        message_type=kind,
        title=title,
        content=content or title,
        biz_type=biz,
        biz_id=id,
    )


def setting(db, key, default):
    r = one(db, m.config, m.config.c.config_key == key, required=False)
    return r["config_value"] if r else default


def balance(db, uid, delta, kind, biz, id, remark="", credit=False):
    u = get(db, m.user, uid, lock=True)
    field = "credit_score" if credit else "points_balance"
    old = u[field]
    new = (
        max(0, min(int(setting(db, "MAX_CREDIT_SCORE", 120)), old + delta))
        if credit
        else old + delta
    )
    require(new >= 0, 43002, "积分不足")
    change(db, m.user, uid, **{field: new})
    data = (
        {"change_score": new - old, "score_before": old, "score_after": new}
        if credit
        else {"change_points": delta, "balance_before": old, "balance_after": new}
    )
    add(
        db,
        m.credit if credit else m.points,
        user_id=uid,
        change_type=kind,
        biz_type=biz,
        biz_id=id,
        remark=remark,
        **data,
    )
    notify(
        db,
        uid,
        "CREDIT_CHANGED" if credit else "POINTS_CHANGED",
        ("信誉" if credit else "积分") + f"变化 {new - old:+d}",
        remark or kind,
        biz,
        id,
    )
    return new


def page(db, t, q, *cond):
    p = int(q.get("page", 1))
    size = int(q.get("pageSize", 10))
    require(p >= 1 and 1 <= size <= 100, message="分页范围为1~100")
    for k, v in q.items():
        c = snake(k)
        if c in t.c and c not in ("id", "created_at") and k not in ("startTime", "endTime"):
            val = payload(
                t, {k: v if not isinstance(t.c[c].type, Boolean) else str(v).lower() == "true"}
            )[c]
            cond = (*cond, t.c[c] == val)
    for k in ("startDate", "startTime", "endDate", "endTime"):
        if q.get(k):
            value = dt(q[k])
            col = t.c.start_time if "start_time" in t.c else t.c.created_at
            if k == "endDate":
                from datetime import timedelta

                value += timedelta(days=1)
            cond = (*cond, col >= value if k.startswith("start") else col < value)
    if q.get("keyword"):
        from sqlalchemy import or_

        cols = [
            c
            for c in t.c
            if c.name
            in (
                "station_name",
                "pile_no",
                "phone",
                "nickname",
                "username",
                "order_no",
                "coupon_name",
            )
        ]
        matches = [c.ilike("%" + q["keyword"] + "%") for c in cols]
        if t is m.order:
            matches.append(
                m.order.c.user_id.in_(
                    select(m.user.c.id).where(m.user.c.phone.ilike("%" + q["keyword"] + "%"))
                )
            )
        if matches:
            cond = (*cond, or_(*matches))
    if q.get("minCreditScore") and "credit_score" in t.c:
        cond = (*cond, t.c.credit_score >= int(q["minCreditScore"]))
    total = count(db, t, *cond)
    data = [
        dict(r)
        for r in db.execute(
            select(t)
            .where(*cond)
            .order_by(t.c.created_at.desc(), t.c.id.desc())
            .limit(size)
            .offset((p - 1) * size)
        ).mappings()
    ]
    return {"list": data, "page": p, "page_size": size, "total": total}
