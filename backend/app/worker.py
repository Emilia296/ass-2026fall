"""Run separately from API. Multiple workers cooperate using row locks and SKIP LOCKED."""

import logging, os, socket, time
from datetime import timedelta
from sqlalchemy import select, update
from .common import *
from .db import Session
from .security import DEMO, cache
from .charging import stop, idle_notify, simulate
from .telemetry import consume_once, PARTITIONS


def maintenance_once():
    # Small indexed batches; no full table scans on the device hot path.
    with Session() as db:
        expired = list(
            db.scalars(
                select(m.reservation.c.id)
                .where(
                    m.reservation.c.status.in_(["WAITING", "ARRIVED"]),
                    m.reservation.c.expire_time < now(),
                )
                .limit(100)
            )
        )
        overdue = list(
            db.scalars(
                select(m.order.c.id)
                .where(
                    m.order.c.payment_status == "UNPAID",
                    m.order.c.overdue_at < now(),
                    m.order.c.overdue_at.is_not(None),
                )
                .limit(100)
            )
        )
        sessions = list(
            db.scalars(
                select(m.session.c.id)
                .where(m.session.c.status.in_(["CHARGING", "CHARGE_FINISHED", "OCCUPYING"]))
                .order_by(m.session.c.updated_at.asc().nulls_first())
                .limit(100)
            )
        )
    for rid in expired:
        with Session.begin() as db:
            peek = get(db, m.reservation, rid)
            get(db, m.user, peek["user_id"], lock=True)
            r = one(db, m.reservation, m.reservation.c.id == rid, lock=True)
            if r["status"] not in ("WAITING", "ARRIVED") or r["expire_time"] >= now():
                continue
            change(db, m.reservation, rid, status="NO_SHOW", credit_penalty_applied=True)
            if not r["credit_penalty_applied"]:
                balance(
                    db,
                    r["user_id"],
                    -5,
                    "RESERVATION_NO_SHOW",
                    "RESERVATION",
                    rid,
                    "预约超时未开始充电",
                    credit=True,
                )
            p = get(db, m.pile, r["pile_id"], lock=True)
            if p["status"] == "RESERVED":
                p = change(db, m.pile, p["id"], status="IDLE")
                idle_notify(db, p)
            notify(
                db,
                r["user_id"],
                "RESERVATION_CANCELLED",
                "预约超时，设备已释放",
                biz="RESERVATION",
                id=rid,
            )
    for oid in overdue:
        with Session.begin() as db:
            peek = get(db, m.order, oid)
            get(db, m.user, peek["user_id"], lock=True)
            o = get(db, m.order, oid, lock=True)
            if (
                o["payment_status"] != "UNPAID"
                or o["overdue_at"] is None
                or o["overdue_at"] >= now()
            ):
                continue
            # Nulling the scheduled deadline is the transactional once-only marker.
            change(db, m.order, oid, overdue_at=None)
            balance(
                db, o["user_id"], -10, "PAYMENT_OVERDUE", "ORDER", oid, "订单支付超时", credit=True
            )
            notify(db, o["user_id"], "ORDER_UNPAID", "订单已逾期，请及时支付", biz="ORDER", id=oid)
    for sid in sessions:
        with Session.begin() as db:
            peek = get(db, m.session, sid)
            get(db, m.user, peek["user_id"], lock=True)
            s = get(db, m.session, sid, lock=True)
            if (
                s["status"] == "CHARGING"
                and not DEMO
                and (s["telemetry_at"] or s["start_time"]) < now() - timedelta(seconds=60)
            ):
                stop(db, s, abnormal="设备超过60秒未上报")
                change(db, m.pile, s["pile_id"], status="OFFLINE")
            elif s["status"] == "CHARGE_FINISHED" and s["free_leave_deadline"] < now():
                change(db, m.session, sid, status="OCCUPYING")
                notify(
                    db,
                    s["user_id"],
                    "OCCUPANCY_STARTED",
                    "免费驶离时间已结束，开始计收占桩费",
                    biz="SESSION",
                    id=sid,
                )
            else:
                change(db, m.session, sid)  # rotate bounded scan fairly
    with Session.begin() as db:
        expired_coupons = (
            select(m.coupon.c.id)
            .where(m.coupon.c.status == "UNUSED", m.coupon.c.valid_to < now())
            .limit(1000)
            .with_for_update(skip_locked=True)
        )
        db.execute(
            update(m.coupon).where(m.coupon.c.id.in_(expired_coupons)).values(status="EXPIRED")
        )
    availability_sweep()
    daily_recovery()


def availability_sweep():
    # The subscription row itself is durable pending work: a crash cannot lose a notification.
    from sqlalchemy import or_

    with Session.begin() as db:
        available = (
            select(m.pile.c.id)
            .where(
                m.pile.c.station_id == m.watch.c.station_id,
                m.pile.c.status == "IDLE",
                or_(m.watch.c.pile_type == "ALL", m.watch.c.pile_type == m.pile.c.pile_type),
            )
            .exists()
        )
        work = db.execute(
            select(m.watch)
            .where(m.watch.c.status == "ACTIVE", available)
            .order_by(m.watch.c.id)
            .limit(100)
            .with_for_update(skip_locked=True)
        ).mappings()
        for w in work:
            notify(
                db,
                w["user_id"],
                "PILE_AVAILABLE",
                "有符合条件的空闲充电桩，请前往查看",
                biz="STATION",
                id=w["station_id"],
            )
            change(db, m.watch, w["id"], status="NOTIFIED", last_notified_at=now())


def daily_recovery():
    today = int(now().strftime("%Y%m%d"))
    with Session() as db:
        done = select(m.credit.c.user_id).where(
            m.credit.c.change_type == "DAILY_RECOVERY", m.credit.c.biz_id == today
        )
        ids = list(
            db.scalars(
                select(m.user.c.id)
                .where(
                    m.user.c.status == "NORMAL",
                    m.user.c.credit_score < 100,
                    m.user.c.id.not_in(done),
                )
                .limit(100)
            )
        )
    for uid in ids:
        with Session.begin() as db:
            u = get(db, m.user, uid, lock=True)
            if u["credit_score"] >= 100 or count(
                db,
                m.credit,
                m.credit.c.user_id == uid,
                m.credit.c.change_type == "DAILY_RECOVERY",
                m.credit.c.biz_id == today,
            ):
                continue
            amount = min(100 - u["credit_score"], int(setting(db, "CREDIT_DAILY_RECOVERY", 1)))
            balance(db, uid, amount, "DAILY_RECOVERY", "SYSTEM", today, "每日信誉恢复", credit=True)


def run_iteration(assigned, name, last):
    had_error = False
    for i in assigned:
        try:
            consume_once(i, name)
        except Exception:
            had_error = True
            logging.exception("Telemetry consumer iteration failed: partition=%s", i)
    if time.monotonic() - last > 2:
        try:
            maintenance_once()
        except Exception:
            had_error = True
            logging.exception("Maintenance iteration failed")
        else:
            last = time.monotonic()
    try:
        cache.setex("worker:heartbeat:" + name, 15, str(time.time()))
    except Exception:
        had_error = True
        logging.exception("Worker heartbeat failed")
    return last, had_error


def main():
    logging.basicConfig(level=logging.INFO)
    name = socket.gethostname() + "-" + str(os.getpid())
    last = 0
    assigned = [
        int(x)
        for x in os.getenv("WORKER_PARTITIONS", ",".join(map(str, range(PARTITIONS)))).split(",")
    ]
    if not assigned or any(x < 0 or x >= PARTITIONS for x in assigned):
        raise ValueError("Invalid WORKER_PARTITIONS")
    while True:
        last, had_error = run_iteration(assigned, name, last)
        if had_error:
            time.sleep(1)


if __name__ == "__main__":
    main()
