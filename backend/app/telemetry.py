"""Partitioned Redis Streams: bounded backlog, acknowledgment after DB commit, retries and DLQ."""

import hashlib, hmac, json, os, socket, time, logging
from datetime import timedelta
from sqlalchemy import select
from .common import *
from .security import cache, DEMO
from .db import Session
from .charging import meter, stop

PARTITIONS = 16
DEVICE_SECRET = os.getenv("DEVICE_SECRET", "local-device-secret-change-before-deploying")
if not DEMO and DEVICE_SECRET.startswith("local-device"):
    raise RuntimeError("Set DEVICE_SECRET")


def sign(event):
    device_key = hmac.new(
        DEVICE_SECRET.encode(), str(event["pileId"]).encode(), hashlib.sha256
    ).digest()
    raw = "|".join(
        str(event[k])
        for k in ("pileId", "sessionId", "sequence", "energyKwh", "powerKw", "observedAt")
    )
    if event.get("faultReason"):
        raw += "|" + event["faultReason"]
    return hmac.new(device_key, raw.encode(), hashlib.sha256).hexdigest()


def ingest(events):
    require(
        isinstance(events, list) and 1 <= len(events) <= 1000, message="单批设备数据数量需为1~1000"
    )
    entries = []
    for e in events:
        require(isinstance(e, dict))
        if e.get("faultReason"):
            require(isinstance(e["faultReason"], str) and len(e["faultReason"]) <= 500)
        for k in ("pileId", "sessionId", "sequence"):
            require(type(e.get(k)) is int and e[k] >= 0)
        for k in ("energyKwh", "powerKw"):
            require(Decimal(str(e[k])).is_finite() and 0 <= Decimal(str(e[k])) <= 1000000)
        at = dt(e["observedAt"])
        require(abs((now() - at).total_seconds()) <= 300, message="上报时间超出5分钟窗口")
        require(hmac.compare_digest(sign(e), str(e.get("signature", ""))), 40300, "设备签名错误")
        entries.append(
            ("telemetry:" + str(e["pileId"] % PARTITIONS), json.dumps(e, separators=(",", ":")))
        )
    # Lua validates all involved partitions before enqueueing any entry.
    script = """for i=1,#KEYS do if redis.call('XLEN',KEYS[i]) >= tonumber(ARGV[1])-#KEYS then return 0 end end
    for i=1,#KEYS do redis.call('XADD',KEYS[i],'*','event',ARGV[i+1]) end; return #KEYS"""
    n = cache.eval(script, len(entries), *[x[0] for x in entries], 100000, *[x[1] for x in entries])
    require(n > 0, 50300, "设备队列繁忙，请保留数据并重试")
    return {"accepted": n}


def consume_once(partition, consumer):
    key = "telemetry:" + str(partition)
    group = "billing"
    try:
        cache.xgroup_create(key, group, id="0", mkstream=True)
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            raise
    recovered = cache.xautoclaim(key, group, consumer, 30000, "0-0", count=100)[1]
    batches = cache.xreadgroup(group, consumer, {key: ">"}, count=100, block=20)
    entries = recovered + [entry for _, batch in batches for entry in batch]
    done = []
    for mid, fields in entries:
        try:
            e = json.loads(fields["event"])
            with Session.begin() as db:
                peek = get(db, m.session, e["sessionId"])
                get(db, m.user, peek["user_id"], lock=True)
                s = get(db, m.session, e["sessionId"], lock=True)
                require(s["pile_id"] == e["pileId"], 40300, "设备与会话不匹配")
                previous_sequence = s["meter_sequence"]
                s = meter(
                    db,
                    s,
                    e["energyKwh"],
                    e["observedAt"],
                    e["sequence"],
                    Decimal(str(e["powerKw"])),
                )
                if (
                    e.get("faultReason")
                    and e["sequence"] > previous_sequence
                    and s["status"] == "CHARGING"
                ):
                    stop(db, s, abnormal=e["faultReason"], at=dt(e["observedAt"]))
                    change(db, m.pile, s["pile_id"], status="FAULT")
            done.append(mid)
        except Exception as exc:
            retry = cache.hincrby(key + ":retries", mid, 1)
            if retry >= 5 or isinstance(exc, (BizError, ValueError, KeyError)):
                cache.xadd(
                    "telemetry:dead-letter",
                    {
                        "source": key,
                        "sourceId": mid,
                        "event": fields.get("event", ""),
                        "error": str(exc)[:500],
                    },
                    maxlen=10000,
                )
                done.append(mid)
            logging.exception("Telemetry processing failed: %s %s", key, mid)
    if done:
        pipe = cache.pipeline()
        pipe.xack(key, group, *done)
        pipe.xdel(key, *done)
        pipe.hdel(key + ":retries", *done)
        pipe.execute()
    return len(done)
