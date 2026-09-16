from datetime import timedelta
from decimal import Decimal
import secrets
from .common import *


def coupon_view(c):
    return {
        **{k: v for k, v in c.items() if not k.endswith("_snapshot")},
        **{k.removesuffix("_snapshot"): v for k, v in c.items() if k.endswith("_snapshot")},
        "user_coupon_id": c["id"],
        "status": "EXPIRED" if c["status"] == "UNUSED" and c["valid_to"] < now() else c["status"],
    }


def grant(db, uid, tid, source):
    t = get(db, m.template, tid, lock=True)
    require(t["status"] == "ISSUING", 43001, "优惠券已停止发放")
    require(
        count(db, m.coupon, m.coupon.c.template_id == tid) < t["total_quantity"]
        and count(db, m.coupon, m.coupon.c.template_id == tid, m.coupon.c.user_id == uid)
        < t["per_user_limit"],
        43003,
        "优惠券库存不足或已达领取上限",
    )
    a = t["valid_from"] if t["valid_type"] == "FIXED" else now()
    z = t["valid_to"] if t["valid_type"] == "FIXED" else now() + timedelta(days=t["valid_days"])
    require(a is not None and z is not None and z > now(), 43001, "优惠券已过期")
    snapshots = {
        k + "_snapshot": t[k]
        for k in (
            "min_amount",
            "discount_amount",
            "discount_rate",
            "max_discount",
            "coupon_name",
            "coupon_type",
        )
    }
    c = add(
        db,
        m.coupon,
        user_id=uid,
        template_id=tid,
        coupon_code=number("CP"),
        source_type=source,
        received_at=now(),
        valid_from=a,
        valid_to=z,
        **snapshots,
    )
    notify(db, uid, "COUPON_RECEIVED", "优惠券已到账", t["coupon_name"], "COUPON", c["id"])
    return c


def events(db, uid, event, amount=0):
    get(db, m.user, uid, lock=True)
    result = {"triggered": False, "user_coupon": None}
    for rule in sorted(
        rows(
            db, m.event_rule, m.event_rule.c.event_type == event, m.event_rule.c.status == "ENABLED"
        ),
        key=lambda x: x["coupon_template_id"],
    ):
        if Decimal(str(amount)) < rule["min_consume_amount"]:
            continue
        if (
            count(
                db,
                m.event_log,
                m.event_log.c.user_id == uid,
                m.event_log.c.rule_id == rule["id"],
                m.event_log.c.created_at >= now() - timedelta(hours=24),
            )
            >= rule["daily_limit"]
        ):
            continue
        c = None
        if secrets.randbelow(1000000) < int(rule["probability"] * 1000000):
            try:
                with db.begin_nested():
                    c = grant(
                        db,
                        uid,
                        rule["coupon_template_id"],
                        "RANDOM_GIFT" if event == "DAILY_LOGIN" else "CONSUMPTION_GIFT",
                    )
            except BizError:
                pass
        add(
            db,
            m.event_log,
            user_id=uid,
            rule_id=rule["id"],
            event_type=event,
            triggered=c is not None,
            user_coupon_id=c["id"] if c else None,
        )
        if c:
            result = {"triggered": True, "user_coupon": coupon_view(c)}
    return result


def quote(db, o, cid=None):
    require(o["payment_status"] == "UNPAID", 44002, "订单已支付")
    require(o["order_status"] in ("WAITING_PAYMENT", "OVERDUE"), 44001, "订单状态不允许支付")
    discount = Decimal(0)
    if cid:
        c = get(db, m.coupon, cid, o["user_id"], lock=True)
        require(
            c["status"] == "UNUSED"
            and c["valid_from"] <= now() <= c["valid_to"]
            and o["original_amount"] >= c["min_amount_snapshot"],
            43001,
            "此优惠券不满足使用条件",
        )
        discount = (
            c["discount_amount_snapshot"]
            if c["coupon_type_snapshot"] == "FULL_CUT"
            else o["original_amount"] * (1 - c["discount_rate_snapshot"])
        )
        if c["max_discount_snapshot"] is not None:
            discount = min(discount, c["max_discount_snapshot"])
        discount = money(max(0, min(o["original_amount"], discount)))
    return {
        "order_id": o["id"],
        "original_amount": o["original_amount"],
        "user_coupon_id": cid,
        "coupon_discount": discount,
        "payable_amount": o["original_amount"] - discount,
    }


def pay(db, uid, oid, b):
    get(db, m.user, uid, lock=True)
    o = get(db, m.order, oid, uid, lock=True)
    method = b.get("payMethod")
    require(method in ("MOCK", "WECHAT", "ALIPAY"), message="请选择支付方式")
    # All listed methods use the documented simulator, never a real payment gateway.
    q = quote(db, o, b.get("userCouponId"))
    p = add(
        db,
        m.payment,
        payment_no=number("PAY"),
        order_id=o["id"],
        user_id=uid,
        pay_method=method,
        pay_amount=q["payable_amount"],
        transaction_no=number("MOCK"),
        paid_at=now(),
    )
    if q["user_coupon_id"]:
        change(db, m.coupon, q["user_coupon_id"], status="USED", used_at=now(), order_id=o["id"])
    charged = get(db, m.session, o["session_id"])
    reward = 0
    score = get(db, m.user, uid)["credit_score"]
    before = score
    if not charged["abnormal_reason"]:
        balance(db, uid, 10, "CHARGE_REWARD", "ORDER", o["id"], "正常完成充电")
        reward += 10
        score = balance(db, uid, 1, "NORMAL_CHARGE", "ORDER", o["id"], "正常完成充电", credit=True)
    consume = int(q["payable_amount"])
    reward += consume
    pb = balance(db, uid, consume, "CONSUME_REWARD", "ORDER", o["id"], "每消费1元奖励1积分")
    o = change(
        db,
        m.order,
        o["id"],
        **{k: v for k, v in q.items() if k not in ("order_id", "original_amount")},
        order_status="COMPLETED",
        payment_status="PAID",
        points_change=reward,
        credit_change=score - before,
        paid_at=now(),
    )
    notify(
        db, uid, "PAYMENT_SUCCESS", "订单支付成功", f"实付 ¥{q['payable_amount']}", "ORDER", o["id"]
    )
    events(db, uid, "CONSUMPTION", q["payable_amount"])
    return {"payment": p, "order": o, "user_benefit": {"points_balance": pb, "credit_score": score}}


def handle_refund(db, aid, a, b):
    require(a["status"] in ("PENDING", "PROCESSING"), 45001, "售后已处理")
    require(b.get("handleResult"), message="请填写处理说明")
    if b.get("action") == "REJECT":
        return change(
            db,
            m.after_sale,
            a["id"],
            status="REJECTED",
            handler_id=aid,
            handle_result=b["handleResult"],
            handled_at=now(),
        )
    require(b.get("action") == "REFUND")
    o = get(db, m.order, a["order_id"], lock=True)
    p = one(db, m.payment, m.payment.c.order_id == o["id"])
    refunded = db.scalar(
        select(func.coalesce(func.sum(m.refund.c.refund_amount), 0)).where(
            m.refund.c.order_id == o["id"], m.refund.c.status == "SUCCESS"
        )
    )
    amount = money(b["refundAmount"])
    remaining = o["payable_amount"] - refunded
    require(
        0 < amount <= remaining and amount <= a["requested_amount"],
        45001,
        "退款金额超出可退金额或申请金额",
    )
    require(b.get("refundType") in ("FULL", "PARTIAL"))
    require(
        b["refundType"] != "FULL" or amount == remaining, 45001, "全额退款金额必须等于剩余可退金额"
    )
    returned = False
    if o["user_coupon_id"]:
        c = get(db, m.coupon, o["user_coupon_id"], lock=True)
        if c["order_id"] == o["id"] and c["status"] == "USED" and c["valid_to"] >= now():
            change(db, m.coupon, c["id"], status="UNUSED", used_at=None, order_id=None)
            returned = True
    r = add(
        db,
        m.refund,
        refund_no=number("RF"),
        after_sales_id=a["id"],
        order_id=o["id"],
        payment_id=p["id"],
        refund_type=b["refundType"],
        refund_amount=amount,
        refund_transaction_no=number("RFTXN"),
        coupon_returned=returned,
        refunded_at=now(),
    )
    a = change(
        db,
        m.after_sale,
        a["id"],
        status="REFUNDED",
        handler_id=aid,
        handle_result=b["handleResult"],
        handled_at=now(),
    )
    # V1.1 deliberately uses REFUNDED for both full and partial refunds; records carry amounts.
    change(db, m.order, o["id"], order_status="REFUNDED", payment_status="REFUNDED")
    notify(db, a["user_id"], "REFUND_SUCCESS", "退款成功", f"模拟退款 ¥{amount}", "ORDER", o["id"])
    return {**a, "after_sales_id": a["id"], "refund": r}
