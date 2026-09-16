from sqlalchemy import case, or_, and_, cast, Float
from .common import *
from .charging import select_plan
from .billing import minute


def stations(db, q, uid=None, favorites=False):
    counts = (
        select(
            m.pile.c.station_id,
            func.count().filter(m.pile.c.pile_type == "FAST").label("fast_pile_count"),
            func.count().filter(m.pile.c.pile_type == "SLOW").label("slow_pile_count"),
            func.count()
            .filter(m.pile.c.pile_type == "FAST", m.pile.c.status == "IDLE")
            .label("idle_fast_count"),
            func.count()
            .filter(m.pile.c.pile_type == "SLOW", m.pile.c.status == "IDLE")
            .label("idle_slow_count"),
        )
        .group_by(m.pile.c.station_id)
        .subquery()
    )
    # A lateral lookup picks the current effective plan for each actual pile, then aggregates station minimums.
    chosen = (
        select(m.plan.c.id)
        .where(
            m.plan.c.station_id == m.pile.c.station_id,
            or_(m.plan.c.pile_id.is_(None), m.plan.c.pile_id == m.pile.c.id),
            m.plan.c.status == "ENABLED",
            m.plan.c.effective_from <= now(),
            or_(m.plan.c.effective_to.is_(None), m.plan.c.effective_to > now()),
        )
        .order_by(
            m.plan.c.pile_id.is_not(None).desc(), m.plan.c.effective_from.desc(), m.plan.c.id.desc()
        )
        .limit(1)
        .correlate(m.pile)
        .scalar_subquery()
    )
    hm = now().strftime("%H:%M")
    prices = (
        select(
            m.pile.c.station_id,
            func.min(m.period.c.electricity_price).label("min_electricity_price"),
            func.min(m.period.c.service_price).label("min_service_price"),
            func.min(m.period.c.electricity_price + m.period.c.service_price).label(
                "current_total_price"
            ),
        )
        .select_from(m.pile)
        .join(m.period, m.period.c.plan_id == chosen)
        .where(m.period.c.start_time <= hm, m.period.c.end_time > hm)
        .group_by(m.pile.c.station_id)
        .subquery()
    )
    cols = [
        m.station,
        *[
            func.coalesce(counts.c[k], 0).label(k)
            for k in ("fast_pile_count", "slow_pile_count", "idle_fast_count", "idle_slow_count")
        ],
        prices.c.min_electricity_price,
        prices.c.min_service_price,
        prices.c.current_total_price,
    ]
    distance = None
    if q.get("longitude") is not None and q.get("latitude") is not None:
        lon, lat = float(q["longitude"]), float(q["latitude"])
        require(-180 <= lon <= 180 and -90 <= lat <= 90)
        a = func.pow(
            func.sin(func.radians(cast(m.station.c.latitude, Float) - lat) / 2), 2
        ) + func.cos(func.radians(lat)) * func.cos(
            func.radians(cast(m.station.c.latitude, Float))
        ) * func.pow(func.sin(func.radians(cast(m.station.c.longitude, Float) - lon) / 2), 2)
        distance = (6371 * 2 * func.asin(func.sqrt(func.least(1.0, a)))).label("distance_km")
        cols.append(distance)
    stmt = (
        select(*cols)
        .select_from(m.station)
        .outerjoin(counts, counts.c.station_id == m.station.c.id)
        .outerjoin(prices, prices.c.station_id == m.station.c.id)
    )
    if favorites:
        stmt = stmt.join(
            m.favorite, and_(m.favorite.c.station_id == m.station.c.id, m.favorite.c.user_id == uid)
        )
    for key in ("city", "status"):
        if q.get(key):
            stmt = stmt.where(m.station.c[key] == q[key])
    if q.get("keyword"):
        stmt = stmt.where(
            or_(
                m.station.c.station_name.ilike("%" + q["keyword"] + "%"),
                m.station.c.address.ilike("%" + q["keyword"] + "%"),
            )
        )
    if q.get("pileType") in ("FAST", "SLOW"):
        stmt = stmt.where(
            counts.c.fast_pile_count > 0
            if q["pileType"] == "FAST"
            else counts.c.slow_pile_count > 0
        )
    if q.get("idleOnly") == "true":
        stmt = stmt.where(
            (
                counts.c.idle_fast_count
                if q.get("pileType") == "FAST"
                else counts.c.idle_slow_count
                if q.get("pileType") == "SLOW"
                else counts.c.idle_fast_count + counts.c.idle_slow_count
            )
            > 0
        )
    if q.get("maxPrice"):
        stmt = stmt.where(prices.c.current_total_price <= Decimal(q["maxPrice"]))
    if q.get("maxDistance") and distance is not None:
        stmt = stmt.where(distance <= float(q["maxDistance"]))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    sort = (
        prices.c.current_total_price
        if q.get("sortBy") == "PRICE"
        else distance
        if distance is not None
        else m.station.c.id
    )
    stmt = stmt.order_by(
        sort.desc().nulls_last() if q.get("sortOrder") == "DESC" else sort.asc().nulls_last(),
        m.station.c.id,
    )
    p = int(q.get("page", 1))
    size = int(q.get("pageSize", 10))
    require(p > 0 and 1 <= size <= 100)
    return {
        "list": [dict(r) for r in db.execute(stmt.offset((p - 1) * size).limit(size)).mappings()],
        "total": total,
        "page": p,
        "page_size": size,
    }


def station_detail(db, id, uid):
    s = get(db, m.station, id)
    piles = rows(db, m.pile, m.pile.c.station_id == int(id))
    for typ in ("FAST", "SLOW"):
        s[typ.lower() + "_pile_count"] = sum(p["pile_type"] == typ for p in piles)
        s["idle_" + typ.lower() + "_count"] = sum(
            p["pile_type"] == typ and p["status"] == "IDLE" for p in piles
        )
    s["is_favorite"] = bool(
        count(db, m.favorite, m.favorite.c.station_id == int(id), m.favorite.c.user_id == uid)
    )
    s["availability_watch"] = one(
        db, m.watch, m.watch.c.station_id == int(id), m.watch.c.user_id == uid, required=False
    )
    s["piles"] = piles
    s["price_periods"] = []
    s["current_price"] = None
    if piles:
        try:
            plan = select_plan(db, piles[0])
            s["price_periods"] = rows(db, m.period, m.period.c.plan_id == plan["id"])
            hm = now().strftime("%H:%M")
            s["current_price"] = next(
                (p for p in s["price_periods"] if p["start_time"] <= hm < p["end_time"]), None
            )
        except BizError:
            pass
    return s


def order_detail(db, o):
    coupon = None
    if o["user_coupon_id"]:
        c = get(db, m.coupon, o["user_coupon_id"])
        coupon = {
            "user_coupon_id": c["id"],
            "coupon_name": c["coupon_name_snapshot"],
            "discount": o["coupon_discount"],
        }
    return {
        **o,
        "coupon": coupon,
        "station": get(db, m.station, o["station_id"]),
        "pile": get(db, m.pile, o["pile_id"]),
        "vehicle": get(db, m.vehicle, o["vehicle_id"]),
        "fee_details": rows(db, m.fee, m.fee.c.order_id == o["id"]),
        "payment_records": rows(db, m.payment, m.payment.c.order_id == o["id"]),
        "refund_records": rows(db, m.refund, m.refund.c.order_id == o["id"]),
    }


def enrich(db, t, data):
    items = data["list"] if isinstance(data, dict) and "list" in data else data
    if not items:
        return data
    for ref, idkey, fields in [
        (m.station, "station_id", ["station_name"]),
        (m.pile, "pile_id", ["pile_no", "pile_type"]),
        (m.vehicle, "vehicle_id", ["plate_number"]),
    ]:
        ids = {r[idkey] for r in items if r.get(idkey)}
        lookup = {r["id"]: r for r in rows(db, ref, ref.c.id.in_(ids))} if ids else {}
        for r in items:
            if r.get(idkey) in lookup:
                r.update({k: lookup[r[idkey]][k] for k in fields})
    return data
