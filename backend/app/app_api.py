from sqlalchemy import delete, update, or_
from datetime import timedelta
from .common import *
from . import charging, benefits, catalog


def dispatch(db, u, method, path, b, q):
    if path == "agent/chat" and method == "POST":
        from .agent import chat

        return chat(db, u, "app", b)
    uid = u["id"]
    parts = path.split("/")
    root = parts[0]
    id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    if path == "users/me":
        if method == "GET":
            return public_user(get(db, m.user, uid))
        return public_user(change(db, m.user, uid, **payload(m.user, b, {"nickname", "avatar"})))
    if root == "vehicles":
        if method == "GET":
            if path == "vehicles/default":
                return one(
                    db,
                    m.vehicle,
                    m.vehicle.c.user_id == uid,
                    m.vehicle.c.is_default.is_(True),
                    m.vehicle.c.status == "NORMAL",
                    required=False,
                )
            return rows(db, m.vehicle, m.vehicle.c.user_id == uid, m.vehicle.c.status == "NORMAL")
        get(db, m.user, uid, lock=True)
        v = get(db, m.vehicle, id, uid, lock=True) if id else None
        if v:
            require(v["status"] == "NORMAL", 40900, "车辆已解绑")
        require(
            not v
            or not count(
                db, m.session, m.session.c.vehicle_id == id, m.session.c.leave_time.is_(None)
            ),
            40900,
            "充电期间不可修改车辆",
        )
        if method == "DELETE":
            change(db, m.vehicle, id, status="UNBOUND", is_default=False)
            return None
        if path.endswith("/default"):
            db.execute(update(m.vehicle).where(m.vehicle.c.user_id == uid).values(is_default=False))
            change(db, m.vehicle, id, is_default=True)
            return {"vehicle_id": id, "is_default": True}
        allowed = {
            "plate_number",
            "vehicle_name",
            "brand",
            "model",
            "battery_capacity",
            "current_soc",
            "is_default",
        }
        data = payload(m.vehicle, b, allowed)
        if not id:
            require(
                all(k in data for k in ("plate_number", "battery_capacity")),
                message="请填写车牌和电池容量",
            )
        if "current_soc" in data:
            require(0 <= data["current_soc"] <= 100)
            data.update(soc_source="MANUAL", soc_updated_at=now())
        if "battery_capacity" in data:
            require(0 < data["battery_capacity"] <= 300, message="电池容量需为0~300kWh")
        if data.get("is_default"):
            db.execute(update(m.vehicle).where(m.vehicle.c.user_id == uid).values(is_default=False))
        return change(db, m.vehicle, id, **data) if id else add(db, m.vehicle, user_id=uid, **data)
    if root == "stations":
        if id is None:
            return catalog.stations(db, q, uid)
        st = get(db, m.station, id)
        if len(parts) == 2:
            return catalog.station_detail(db, id, uid)
        if parts[2] == "piles":
            cond = [m.pile.c.station_id == id]
            for k in ("pileType", "status"):
                if q.get(k):
                    cond.append(m.pile.c[snake(k)] == q[k])
            return rows(db, m.pile, *cond)
        if parts[2] == "favorite":
            if method == "POST":
                require(
                    not count(
                        db, m.favorite, m.favorite.c.user_id == uid, m.favorite.c.station_id == id
                    ),
                    40901,
                    "已收藏此站点",
                )
                add(db, m.favorite, user_id=uid, station_id=id)
            else:
                db.execute(
                    delete(m.favorite).where(
                        m.favorite.c.user_id == uid, m.favorite.c.station_id == id
                    )
                )
            return {"station_id": id, "favorite": method == "POST"}
        if parts[2] == "availability-watch":
            if method != "GET":
                get(db, m.user, uid, lock=True)
            w = one(
                db,
                m.watch,
                m.watch.c.user_id == uid,
                m.watch.c.station_id == id,
                lock=method != "GET",
                required=False,
            )
            if method == "GET":
                return w
            if len(parts) == 3:
                typ = b.get("pileType", "ALL")
                require(typ in ("FAST", "SLOW", "ALL"))
                return (
                    change(db, m.watch, w["id"], pile_type=typ, status="ACTIVE", cancelled_at=None)
                    if w
                    else add(db, m.watch, user_id=uid, station_id=id, pile_type=typ)
                )
            require(w, 46001, "空闲提醒不存在")
            allowed = ["NOTIFIED"] if parts[3] == "continue" else ["ACTIVE", "NOTIFIED"]
            require(w["status"] in allowed, 46002, "空闲提醒状态不允许当前操作")
            return change(
                db,
                m.watch,
                w["id"],
                status="ACTIVE" if parts[3] == "continue" else "CANCELLED",
                cancelled_at=now() if parts[3] == "cancel" else None,
            )
    if path == "favorites/stations":
        return catalog.stations(db, q, uid, True)
    if path == "piles/scan":
        p = one(db, m.pile, m.pile.c.qr_code == q.get("qrCode"))
        st = get(db, m.station, p["station_id"])
        return {
            **p,
            "pile_id": p["id"],
            "station_name": st["station_name"],
            "can_start_charging": p["status"] == "IDLE" and st["status"] == "OPEN",
        }
    if root == "reservations":
        if method == "GET":
            if id:
                r = get(db, m.reservation, id, uid)
                r.pop("credit_penalty_applied", None)
                return catalog.enrich(db, m.reservation, [r])[0]
            result = page(db, m.reservation, q, m.reservation.c.user_id == uid)
            for r in result["list"]:
                r.pop("credit_penalty_applied", None)
            return catalog.enrich(db, m.reservation, result)
        user = get(db, m.user, uid, lock=True)
        if id is None:
            require(
                user["credit_score"] >= int(setting(db, "MIN_CREDIT_FOR_RESERVATION", 60)),
                42002,
                "信誉分不足，无法预约",
            )
            require(
                not count(
                    db,
                    m.reservation,
                    m.reservation.c.user_id == uid,
                    m.reservation.c.status.in_(["WAITING", "ARRIVED", "CHARGING"]),
                ),
                42001,
                "已有进行中的预约",
            )
            v = get(db, m.vehicle, b["vehicleId"], uid)
            require(v["status"] == "NORMAL")
            p = get(db, m.pile, b["pileId"], lock=True)
            st = get(db, m.station, b["stationId"], lock=True)
            require(
                p["station_id"] == st["id"] and p["status"] == "IDLE" and st["status"] == "OPEN",
                42001,
                "预约设备不可用",
            )
            when = dt(b["reservationTime"])
            require(
                now() - timedelta(seconds=30) <= when <= now() + timedelta(days=1),
                message="预约时间需在未来24小时内",
            )
            r = add(
                db,
                m.reservation,
                reservation_no=number("RS"),
                user_id=uid,
                vehicle_id=v["id"],
                station_id=st["id"],
                pile_id=p["id"],
                reservation_time=when,
                expire_time=when
                + timedelta(minutes=int(setting(db, "RESERVATION_TIMEOUT_MINUTES", 15))),
            )
            change(db, m.pile, p["id"], status="RESERVED")
            notify(
                db,
                uid,
                "RESERVATION_SUCCESS",
                "预约成功",
                "请在到场截止时间前到达充电站",
                "RESERVATION",
                r["id"],
            )
            return r
        r = get(db, m.reservation, id, uid, lock=True)
        require(r["status"] in ("WAITING", "ARRIVED"), 42003, "预约已失效或开始充电")
        require(r["expire_time"] > now(), 42003, "预约已过期")
        if parts[-1] == "cancel":
            r = change(db, m.reservation, id, status="CANCELLED", cancelled_at=now())
            p = change(db, m.pile, r["pile_id"], status="IDLE")
            charging.idle_notify(db, p)
            notify(db, uid, "RESERVATION_CANCELLED", "预约已取消", biz="RESERVATION", id=id)
            return r
        require(r["status"] == "WAITING", 40901, "已确认到场")
        return change(db, m.reservation, id, status="ARRIVED", arrived_at=now())
    if root == "charging":
        if method == "POST" and path == "charging/sessions":
            return charging.session_view(db, charging.start(db, uid, b))
        if path == "charging/sessions/current":
            s = one(
                db,
                m.session,
                m.session.c.user_id == uid,
                m.session.c.leave_time.is_(None),
                required=False,
            )
            return charging.session_view(db, s)
        sid = int(parts[2])
        get(db, m.user, uid, lock=method != "GET")
        s = get(db, m.session, sid, uid, lock=method != "GET")
        if path.endswith("/fee-preview"):
            return charging.totals(s)[0]
        if method == "GET":
            return charging.session_view(db, s)
        if path.endswith("/stop"):
            from .security import DEMO

            if DEMO:
                s = charging.simulate(db, s)
            return charging.session_view(db, charging.stop(db, s))
        if path.endswith("/leave"):
            return charging.leave(db, s)
    if root == "orders":
        if id is None:
            return catalog.enrich(db, m.order, page(db, m.order, q, m.order.c.user_id == uid))
        if path.endswith("/pay"):
            return benefits.pay(db, uid, id, b)
        o = get(db, m.order, id, uid, lock=method != "GET")
        if len(parts) == 2:
            return catalog.order_detail(db, o)
        if parts[2] == "fee-details":
            return rows(db, m.fee, m.fee.c.order_id == id)
        if parts[2] == "quote":
            return benefits.quote(db, o, b.get("userCouponId"))
        if parts[2] == "available-coupons":
            result = []
            for c in rows(db, m.coupon, m.coupon.c.user_id == uid, m.coupon.c.status == "UNUSED"):
                try:
                    result.append(
                        {
                            **benefits.coupon_view(c),
                            "estimated_discount": benefits.quote(db, o, c["id"])["coupon_discount"],
                        }
                    )
                except BizError:
                    pass
            return result
    if root == "coupons":
        conditions = [m.coupon.c.user_id == uid]
        query = dict(q)
        status = query.pop("status", None)
        if status == "EXPIRED":
            conditions.append(
                or_(
                    m.coupon.c.status == "EXPIRED",
                    (m.coupon.c.status == "UNUSED") & (m.coupon.c.valid_to < now()),
                )
            )
        elif status:
            conditions.append(m.coupon.c.status == status)
        if status == "UNUSED":
            conditions.append(m.coupon.c.valid_to >= now())
        r = page(db, m.coupon, query, *conditions)
        r["list"] = [benefits.coupon_view(c) for c in r["list"]]
        return r
    if root == "coupon-templates":
        if method == "GET":
            return [
                {**t, "can_exchange": u["points_balance"] >= t["points_cost"]}
                for t in rows(
                    db, m.template, m.template.c.status == "ISSUING", m.template.c.points_cost > 0
                )
            ]
        get(db, m.user, uid, lock=True)
        t = get(db, m.template, id, lock=True)
        require(t["points_cost"] > 0, 43001, "该券不支持积分兑换")
        pb = balance(db, uid, -t["points_cost"], "COUPON_EXCHANGE", "COUPON", id, "积分兑换优惠券")
        c = benefits.grant(db, uid, id, "POINTS_EXCHANGE")
        return {
            "user_coupon": benefits.coupon_view(c),
            "points_change": -t["points_cost"],
            "points_balance": pb,
        }
    if path == "coupon-events/daily-login":
        return benefits.events(db, uid, "DAILY_LOGIN")
    if root in ("points", "credit"):
        if len(parts) == 1:
            return (
                {"points_balance": u["points_balance"]}
                if root == "points"
                else {"credit_score": u["credit_score"]}
            )
        t = m.points if root == "points" else m.credit
        return page(db, t, q, t.c.user_id == uid)
    if root == "messages":
        base = [m.message.c.user_id == uid, m.message.c.is_deleted.is_(False)]
        if method == "GET":
            if path.endswith("/unread-count"):
                return {"unread_count": count(db, m.message, *base, m.message.c.is_read.is_(False))}
            return page(db, m.message, q, *base)
        if path.endswith("/read-all"):
            return {
                "updated_count": db.execute(
                    update(m.message)
                    .where(*base, m.message.c.is_read.is_(False))
                    .values(is_read=True, read_at=now())
                ).rowcount
            }
        msg = get(db, m.message, id, uid)
        require(not msg["is_deleted"], 40400, "消息已删除")
        return change(
            db,
            m.message,
            id,
            **(
                {"is_deleted": True, "deleted_at": now()}
                if method == "DELETE"
                else {"is_read": True, "read_at": now()}
            ),
        )
    if root == "after-sales":
        if method == "GET":
            if id:
                a = get(db, m.after_sale, id, uid)
                return {
                    **a,
                    "refund": one(db, m.refund, m.refund.c.after_sales_id == id, required=False),
                }
            return page(db, m.after_sale, q, m.after_sale.c.user_id == uid)
        get(db, m.user, uid, lock=True)
        o = get(db, m.order, b["orderId"], uid, lock=True)
        require(o["payment_status"] in ("PAID", "REFUNDED"), 45001, "仅已支付订单可申请售后")
        require(
            not count(
                db,
                m.after_sale,
                m.after_sale.c.order_id == o["id"],
                m.after_sale.c.status.in_(["PENDING", "PROCESSING"]),
            ),
            45001,
            "已有待处理售后",
        )
        already = db.scalar(
            select(func.coalesce(func.sum(m.refund.c.refund_amount), 0)).where(
                m.refund.c.order_id == o["id"], m.refund.c.status == "SUCCESS"
            )
        )
        amount = money(b["requestedAmount"])
        require(
            0 < amount <= o["payable_amount"] - already, message="退款金额不合法或超出剩余可退金额"
        )
        require(
            b.get("type")
            in ("AMOUNT_ERROR", "CHARGING_ERROR", "DEVICE_ERROR", "DUPLICATE_CHARGE", "OTHER")
            and b.get("reason")
        )
        return add(
            db,
            m.after_sale,
            after_sales_no=number("AS"),
            user_id=uid,
            order_id=o["id"],
            type=b["type"],
            reason=b["reason"],
            evidence=b.get("evidence"),
            requested_amount=amount,
        )
    if root == "faults":
        p = get(db, m.pile, b["pileId"])
        sid = b.get("sessionId")
        if sid:
            require(get(db, m.session, sid, uid)["pile_id"] == p["id"])
        require(b.get("faultType") and b.get("faultDescription"))
        return add(
            db,
            m.fault,
            fault_no=number("FT"),
            pile_id=p["id"],
            station_id=p["station_id"],
            source_type="USER",
            reporter_user_id=uid,
            session_id=sid,
            fault_type=b["faultType"],
            fault_description=b["faultDescription"],
            fault_time=now(),
        )
    raise BizError(40400, "接口不存在")
