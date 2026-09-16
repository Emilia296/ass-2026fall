from datetime import timedelta
from sqlalchemy import delete, update, or_, cast, Date
from .common import *
from .security import passwords
from . import charging, benefits, catalog
from .billing import validate_periods

TABLES = {
    "stations": m.station,
    "piles": m.pile,
    "price-plans": m.plan,
    "orders": m.order,
    "reservations": m.reservation,
    "users": m.user,
    "coupon-templates": m.template,
    "coupon-event-rules": m.event_rule,
    "faults": m.fault,
    "after-sales": m.after_sale,
    "admin-users": m.admin,
    "roles": m.role,
    "operation-logs": m.audit,
    "login-logs": m.login_log,
}
MODULES = {
    "observability": "dashboard",
    "stations": "station",
    "piles": "pile",
    "charging": "pile",
    "price-plans": "price",
    "occupancy-fee-rules": "price",
    "orders": "order",
    "reservations": "reservation",
    "users": "user",
    "coupon-templates": "coupon",
    "coupon-event-rules": "coupon",
    "faults": "fault",
    "after-sales": "after-sales",
    "admin-users": "system",
    "roles": "system",
    "permissions": "system",
    "operation-logs": "audit",
    "login-logs": "audit",
    "system-configs": "system",
    "dashboard": "dashboard",
    "agent": "dashboard",
}


def authorize(u, method, path):
    module = MODULES.get(path.split("/")[0])
    require(module is not None, 40400, "接口不存在")
    require(
        module + (":view" if method == "GET" else ":edit") in u["permissions"],
        40300,
        "当前账号无此操作权限",
    )


def dashboard(db, q):
    a = (
        dt(q["startDate"])
        if q.get("startDate")
        else now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    )
    z = dt(q["endDate"]) + timedelta(days=1) if q.get("endDate") else now() + timedelta(seconds=1)
    require(z > a and (z - a).days <= 366, message="统计范围最长366天")
    oc = [m.order.c.created_at >= a, m.order.c.created_at < z]
    rev = db.scalar(
        select(func.coalesce(func.sum(m.payment.c.pay_amount), 0)).where(
            m.payment.c.paid_at >= a, m.payment.c.paid_at < z, m.payment.c.status == "SUCCESS"
        )
    )
    ref = db.scalar(
        select(func.coalesce(func.sum(m.refund.c.refund_amount), 0)).where(
            m.refund.c.refunded_at >= a, m.refund.c.refunded_at < z, m.refund.c.status == "SUCCESS"
        )
    )
    trend = {
        str(r[0]): r[1]
        for r in db.execute(
            select(cast(m.order.c.created_at, Date), func.count())
            .where(*oc)
            .group_by(cast(m.order.c.created_at, Date))
        )
    }
    revenue = {
        str(r[0]): r[1]
        for r in db.execute(
            select(cast(m.payment.c.paid_at, Date), func.sum(m.payment.c.pay_amount))
            .where(
                m.payment.c.paid_at >= a, m.payment.c.paid_at < z, m.payment.c.status == "SUCCESS"
            )
            .group_by(cast(m.payment.c.paid_at, Date))
        )
    }
    refunds = {
        str(r[0]): r[1]
        for r in db.execute(
            select(cast(m.refund.c.refunded_at, Date), func.sum(m.refund.c.refund_amount))
            .where(
                m.refund.c.refunded_at >= a,
                m.refund.c.refunded_at < z,
                m.refund.c.status == "SUCCESS",
            )
            .group_by(cast(m.refund.c.refunded_at, Date))
        )
    }
    dates = [
        str((a + timedelta(days=i)).date())
        for i in range((z.date() - a.date()).days + 1)
        if (a + timedelta(days=i)).date() <= now().date()
    ]
    return {
        "user_count": count(db, m.user),
        "order_count": count(db, m.order, *oc),
        "total_energy_kwh": db.scalar(
            select(func.coalesce(func.sum(m.order.c.energy_kwh), 0)).where(*oc)
        ),
        "platform_revenue": rev - ref,
        "refund_amount": ref,
        "pile_count": count(db, m.pile),
        "fault_pile_count": count(db, m.pile, m.pile.c.status == "FAULT"),
        "order_trend": [{"date": d, "value": trend.get(d, 0)} for d in dates],
        "revenue_trend": [
            {"date": d, "value": revenue.get(d, 0) - refunds.get(d, 0)} for d in dates
        ],
    }


def validate_entity(t, data):
    statuses = {
        m.station.name: ["OPEN", "PAUSED", "CLOSED"],
        m.pile.name: ["IDLE", "FAULT", "OFFLINE", "MAINTAIN"],
        m.plan.name: ["ENABLED", "DISABLED"],
        m.template.name: ["DRAFT", "ISSUING", "STOPPED"],
        m.event_rule.name: ["ENABLED", "DISABLED"],
        m.admin.name: ["ENABLED", "DISABLED"],
        m.role.name: ["ENABLED", "DISABLED"],
    }
    if "status" in data and t.name in statuses:
        require(
            data["status"] in statuses[t.name], message="状态值不合法或该状态需通过业务流程修改"
        )
    if t is m.station:
        from .billing import minute

        require(-180 <= data["longitude"] <= 180 and -90 <= data["latitude"] <= 90)
        minute(data["business_start"])
        minute(data["business_end"])
    if t is m.template:
        require(
            data["coupon_type"] in ("FULL_CUT", "DISCOUNT")
            and data["valid_type"] in ("FIXED", "AFTER_RECEIVE")
        )
        require(
            data["min_amount"] >= 0
            and data["points_cost"] >= 0
            and data["per_user_limit"] > 0
            and data["total_quantity"] >= 0
        )
        if data["coupon_type"] == "FULL_CUT":
            require(data.get("discount_amount") is not None and data["discount_amount"] > 0)
        else:
            require(data.get("discount_rate") is not None and 0 < data["discount_rate"] < 1)
        if data["valid_type"] == "FIXED":
            require(
                data.get("valid_from")
                and data.get("valid_to")
                and data["valid_to"] > data["valid_from"]
            )
        else:
            require(data["valid_days"] > 0)
        require(data.get("max_discount") is None or data["max_discount"] > 0)
    if t is m.event_rule:
        require(
            data["event_type"] in ("DAILY_LOGIN", "CONSUMPTION")
            and 0 <= data["probability"] <= 1
            and data["daily_limit"] > 0
            and data["min_consume_amount"] >= 0
        )
    if t is m.plan:
        require(data.get("effective_to") is None or data["effective_to"] > data["effective_from"])


def dispatch(db, u, method, path, b, q):
    authorize(u, method, path)
    parts = path.split("/")
    root = parts[0]
    id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    if path == "observability":
        from .observability import snapshot

        return snapshot()
    if path == "dashboard/summary":
        return dashboard(db, q)
    if root == "charging":
        require(b.get("reason"), message="终止充电需填写原因")
        s = get(db, m.session, int(parts[2]), lock=True)
        return charging.session_view(db, charging.stop(db, s, "ADMIN_STOP"))
    if root == "permissions":
        allp = rows(db, m.permission)
        return [
            {**p, "children": [c for c in allp if c["parent_id"] == p["id"]]}
            for p in allp
            if p["parent_id"] is None
        ]
    if root == "system-configs":
        if method == "GET":
            return rows(
                db,
                m.config,
                *([m.config.c.config_key.in_(q["keys"].split(","))] if q.get("keys") else []),
            )
        c = one(db, m.config, m.config.c.config_key == parts[1], lock=True)
        val = str(b["configValue"])
        require(len(val) <= 255)
        limits = {
            "PAYMENT_OVERDUE_HOURS": (1, 720),
            "MIN_CREDIT_FOR_RESERVATION": (0, 120),
            "MAX_CREDIT_SCORE": (100, 1000),
            "CREDIT_DAILY_RECOVERY": (0, 10),
            "RESERVATION_TIMEOUT_MINUTES": (1, 120),
        }
        if parts[1] in limits:
            lo, hi = limits[parts[1]]
            require(lo <= int(val) <= hi)
        return change(
            db,
            m.config,
            c["id"],
            config_value=val,
            description=b.get("description", c["description"]),
        )
    if root == "occupancy-fee-rules":
        if method == "GET":
            rules = (
                rows(
                    db,
                    m.occupancy,
                    or_(
                        m.occupancy.c.station_id == int(q["stationId"]),
                        m.occupancy.c.station_id.is_(None),
                    ),
                )
                if q.get("stationId")
                else rows(db, m.occupancy, m.occupancy.c.station_id.is_(None))
            )
            require(rules, 40400, "占桩规则不存在")
            r = sorted(rules, key=lambda x: x["station_id"] is not None, reverse=True)[0]
            return {**r, "tiers": rows(db, m.tier, m.tier.c.rule_id == r["id"])}
        r = get(db, m.occupancy, id, lock=True)
        require(b.get("freeMinutes", 30) == 30, message="免费时间固定为30分钟")
        if "tiers" in b:
            ts = b["tiers"]
            require(
                len(ts) == 2
                and ts[0]["startMinute"] == 31
                and ts[0]["endMinute"] == 60
                and Decimal(str(ts[0]["pricePerMinute"])) == Decimal(".1")
                and ts[1]["startMinute"] == 61
                and ts[1].get("endMinute") is None
                and Decimal(str(ts[1]["pricePerMinute"])) == Decimal(".2"),
                message="占桩阶梯固定为31~60分钟0.1元、61分钟起0.2元",
            )
        cap = b.get("maxAmount", r["max_amount"])
        require(cap is None or Decimal(str(cap)) >= 0)
        return change(db, m.occupancy, id, max_amount=cap)
    t = TABLES.get(root)
    require(t is not None, 40400, "接口不存在")
    if method == "GET":
        if root == "stations":
            return catalog.stations(db, q)
        if root == "roles":
            result = rows(db, t)
            for r in result:
                r["permission_ids"] = [
                    x["permission_id"]
                    for x in rows(db, m.role_permission, m.role_permission.c.role_id == r["id"])
                ]
            return result
        if id:
            r = get(db, t, id)
            if t is m.user:
                return {
                    **public_user(r, True),
                    "vehicles": rows(db, m.vehicle, m.vehicle.c.user_id == id),
                }
            if t is m.order:
                return {
                    **catalog.order_detail(db, r),
                    "user": public_user(get(db, m.user, r["user_id"]), True),
                }
            if t is m.after_sale:
                return {
                    **r,
                    "refund": one(db, m.refund, m.refund.c.after_sales_id == id, required=False),
                }
            return catalog.enrich(db, t, [r])[0]
        result = catalog.enrich(db, t, page(db, t, q))
        if t in (m.user, m.admin):
            result["list"] = [public_user(x, True) for x in result["list"]]
            if t is m.admin:
                for r in result["list"]:
                    r["role_ids"] = [
                        x["role_id"]
                        for x in rows(db, m.admin_role, m.admin_role.c.admin_user_id == r["id"])
                    ]
        if t is m.plan:
            for r in result["list"]:
                r["periods"] = rows(db, m.period, m.period.c.plan_id == r["id"])
        return result
    old = get(db, t, id, lock=True) if id else None
    if t is m.user:
        require(b.get("reason"), message="请填写操作原因")
        if parts[-1] == "unlock":
            require(old["manual_locked"], 40900, "此账号没有人工锁定")
            return public_user(
                change(
                    db,
                    t,
                    id,
                    status="NORMAL",
                    manual_locked=False,
                    failed_login_count=0,
                    lock_until=None,
                    lock_reason=None,
                    token_version=old["token_version"] + 1,
                ),
                True,
            )
        if parts[-1] == "status":
            require(
                b["status"] in ("NORMAL", "DISABLED") and not old["manual_locked"],
                40900,
                "人工锁定需使用解锁接口",
            )
            return public_user(
                change(db, t, id, status=b["status"], token_version=old["token_version"] + 1), True
            )
        iscredit = parts[2] == "credit"
        delta = int(b["changeScore" if iscredit else "changePoints"])
        require(abs(delta) <= 100000, message="调整数值过大")
        value = balance(
            db, id, delta, "ADMIN_ADJUST", "ADMIN", u["id"], b["reason"], credit=iscredit
        )
        return {
            "user_id": id,
            "change_type": "ADMIN_ADJUST",
            "biz_type": "ADMIN",
            "change_score" if iscredit else "change_points": delta,
            "credit_score" if iscredit else "points_balance": value,
        }
    if t is m.template and parts[-1] == "grant":
        ids = b["userIds"]
        require(isinstance(ids, list) and 0 < len(ids) <= 100)
        # Template is already locked; single-row grant avoids unbounded transactions.
        successes = 0
        for uid in sorted(set(map(int, ids))):
            try:
                with db.begin_nested():
                    get(db, m.user, uid)
                    benefits.grant(db, uid, id, "ADMIN_GRANT")
                    successes += 1
            except BizError:
                pass
        return {
            "template_id": id,
            "success_count": successes,
            "failed_count": len(set(ids)) - successes,
        }
    if t is m.fault:
        if id is None:
            p = get(db, m.pile, b["pileId"])
            return add(
                db,
                t,
                fault_no=number("FT"),
                pile_id=p["id"],
                station_id=p["station_id"],
                source_type="OPERATOR",
                fault_type=b["faultType"],
                fault_description=b["faultDescription"],
                fault_time=now(),
            )
        if parts[-1] == "process":
            require(old["status"] == "PENDING", 40900, "故障已被处理")
            return change(
                db,
                t,
                id,
                status="PROCESSING",
                handler_id=u["id"],
                handle_note=b.get("handleNote", ""),
            )
        require(old["status"] == "PROCESSING", 40900, "请先接单处理故障")
        require(b.get("handleNote"))
        status = b.get("pileStatus", "IDLE")
        require(status in ("IDLE", "MAINTAIN", "OFFLINE", "FAULT"))
        p = get(db, m.pile, old["pile_id"], lock=True)
        require(
            not count(
                db, m.session, m.session.c.pile_id == p["id"], m.session.c.leave_time.is_(None)
            ),
            40900,
            "请先结束充电并驶离",
        )
        require(
            not count(
                db,
                m.reservation,
                m.reservation.c.pile_id == p["id"],
                m.reservation.c.status.in_(["WAITING", "ARRIVED", "CHARGING"]),
            ),
            40900,
            "设备仍有预约",
        )
        p = change(db, m.pile, p["id"], status=status)
        if status == "IDLE":
            charging.idle_notify(db, p)
        r = change(
            db,
            t,
            id,
            status="RESOLVED",
            handle_note=b["handleNote"],
            handler_id=u["id"],
            resolved_at=now(),
        )
        if old["reporter_user_id"]:
            notify(
                db,
                old["reporter_user_id"],
                "FAULT_RESULT",
                "故障处理完成",
                b["handleNote"],
                "FAULT",
                id,
            )
        return r
    if t is m.after_sale:
        return benefits.handle_refund(db, u["id"], old, b)
    if t is m.role and parts[-1] == "permissions":
        ids = list(set(map(int, b["permissionIds"])))
        require(len(ids) <= 200 and count(db, m.permission, m.permission.c.id.in_(ids)) == len(ids))
        require(old["role_code"] != "ADMIN", 40300, "内置管理员角色权限不可移除")
        db.execute(delete(m.role_permission).where(m.role_permission.c.role_id == id))
        for pid in ids:
            add(db, m.role_permission, role_id=id, permission_id=pid)
        return {"role_id": id, "permission_ids": ids}
    if t is m.plan and parts[-1] == "periods":
        periods = validate_periods(
            [
                payload(
                    m.period,
                    p,
                    {"start_time", "end_time", "electricity_price", "service_price", "sort_no"},
                )
                for p in b["periods"]
            ]
        )
        db.execute(delete(m.period).where(m.period.c.plan_id == id))
        for p in periods:
            add(db, m.period, plan_id=id, **p)
        return {"plan_id": id, "period_count": len(periods)}
    editable = {
        m.station.name: set(m.station.c.keys()) - {"id", "created_at", "updated_at"},
        m.pile.name: {"station_id", "pile_no", "pile_type", "power_kw", "qr_code", "status"},
        m.plan.name: {
            "plan_name",
            "station_id",
            "pile_id",
            "version",
            "effective_from",
            "effective_to",
            "status",
        },
        m.template.name: set(m.template.c.keys()) - {"id", "created_at"},
        m.event_rule.name: set(m.event_rule.c.keys()) - {"id", "created_at"},
        m.admin.name: {"username", "real_name", "phone", "status"},
        m.role.name: {"role_code", "role_name", "status"},
    }
    require(t.name in editable, 40300, "此资源不可直接修改")
    data = payload(t, b, {"status"} if parts[-1] == "status" else editable[t.name])
    if t is m.admin:
        if id == u["id"]:
            require(
                data.get("status", "ENABLED") == "ENABLED" and "roleIds" not in b,
                40300,
                "不可停用自己或修改自己的角色",
            )
        if not id or b.get("password"):
            require(8 <= len(b.get("password", "")) <= 128, message="密码需要8~128位")
            data["password_hash"] = passwords.hash(b["password"])
        if id:
            data["token_version"] = old["token_version"] + 1
    if t is m.role and old and old["role_code"] == "ADMIN":
        require(
            data.get("role_code", "ADMIN") == "ADMIN"
            and data.get("status", "ENABLED") == "ENABLED",
            40300,
            "内置管理员角色不可停用",
        )
    # Apply column defaults before cross-field validation.
    merged = {
        c.name: c.default.arg for c in t.c if c.default is not None and not callable(c.default.arg)
    }
    merged.update(old or {})
    merged.update(data)
    validate_entity(t, merged)
    if t is m.pile:
        get(db, m.station, merged["station_id"])
        require(
            not id
            or not count(
                db, m.session, m.session.c.pile_id == id, m.session.c.leave_time.is_(None)
            ),
            40900,
            "使用中的充电桩不可直接修改",
        )
        require(
            not id
            or not count(
                db,
                m.reservation,
                m.reservation.c.pile_id == id,
                m.reservation.c.status.in_(["WAITING", "ARRIVED", "CHARGING"]),
            ),
            40900,
            "已预约的充电桩不可直接修改",
        )
    if t is m.plan:
        get(db, m.station, merged["station_id"])
        if merged.get("pile_id"):
            require(get(db, m.pile, merged["pile_id"])["station_id"] == merged["station_id"])
    r = change(db, t, id, **data) if id else add(db, t, **data)
    if t is m.pile and r["status"] == "IDLE" and (not old or old["status"] != "IDLE"):
        charging.idle_notify(db, r)
    if t is m.plan and (not old or "periods" in b):
        periods = validate_periods(
            [
                payload(
                    m.period,
                    p,
                    {"start_time", "end_time", "electricity_price", "service_price", "sort_no"},
                )
                for p in b.get("periods", [])
            ]
        )
        db.execute(delete(m.period).where(m.period.c.plan_id == r["id"]))
        for p in periods:
            add(db, m.period, plan_id=r["id"], **p)
        r["period_count"] = len(periods)
    if t is m.admin and "roleIds" in b:
        ids = list(set(map(int, b["roleIds"])))
        require(ids and len(ids) <= 30 and count(db, m.role, m.role.c.id.in_(ids)) == len(ids))
        db.execute(delete(m.admin_role).where(m.admin_role.c.admin_user_id == r["id"]))
        for rid in ids:
            add(db, m.admin_role, admin_user_id=r["id"], role_id=rid)
    return public_user(r, True) if t is m.admin else r
