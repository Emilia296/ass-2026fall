"""Bounded-cardinality runtime observations. Metrics are never authoritative business data."""

import os
import time
from redis import Redis
from redis.exceptions import RedisError
from .db import now
from .security import cache

metrics = Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
    socket_timeout=0.2,
    socket_connect_timeout=0.2,
)
BOUNDS = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 15000)


def record(method, route, status, elapsed):
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
        method = "OTHER"
    ms = max(0, int(elapsed * 1000))
    bucket = next((str(x) for x in BOUNDS if ms <= x), "inf")
    key = "observations:http:" + now().strftime("%Y%m%d")
    prefix = f"{method}|{route}|{status}"
    minute = "observations:minute:" + str(int(time.time()) // 60)
    try:
        p = metrics.pipeline()
        p.hincrby(key, prefix + "|count", 1)
        p.hincrby(key, prefix + "|duration_ms", ms)
        p.hincrby(key, prefix + "|bucket_" + bucket, 1)
        p.expire(key, 8 * 86400)
        p.hincrby(minute, "requests", 1)
        if status >= 500:
            p.hincrby(minute, "server_errors", 1)
        p.expire(minute, 3600)
        p.execute()
    except RedisError:
        # Observability outage must not alter payment/charging results.
        pass


def snapshot():
    values = cache.hgetall("observations:http:" + now().strftime("%Y%m%d"))
    endpoints = {}
    for field, value in values.items():
        method, path, status, metric = field.split("|")
        k = (method, path, int(status))
        endpoints.setdefault(k, {})[metric] = int(value)
    result = []
    for (method, path, status), v in sorted(endpoints.items()):
        count = v.get("count", 0)
        threshold = count * 0.95
        cumulative = 0
        p95 = None
        for bound in (*BOUNDS, "inf"):
            cumulative += v.get("bucket_" + str(bound), 0)
            if cumulative >= threshold:
                p95 = bound
                break
        result.append(
            {
                "method": method,
                "path": path,
                "http_status": status,
                "count": count,
                "mean_ms": round(v.get("duration_ms", 0) / max(count, 1), 2),
                "p95_bucket_upper_ms": p95,
            }
        )
    total = sum(r["count"] for r in result)
    errors = sum(r["count"] for r in result if r["http_status"] >= 500)
    previous = cache.hgetall("observations:minute:" + str(int(time.time()) // 60 - 1))
    queue = []
    for i in range(16):
        key = "telemetry:" + str(i)
        groups = cache.xinfo_groups(key) if cache.exists(key) else []
        group = next((g for g in groups if g["name"] == "billing"), {})
        queue.append(
            {
                "partition": i,
                "backlog": cache.xlen(key),
                "pending": group.get("pending", 0),
                "undelivered": group.get("lag"),
            }
        )
    workers = []
    for key in cache.scan_iter("worker:heartbeat:*", count=100):
        value = cache.get(key)
        if value:
            workers.append(
                {
                    "worker": key.removeprefix("worker:heartbeat:"),
                    "last_seen_seconds_ago": round(max(0, time.time() - float(value)), 1),
                }
            )
    return {
        "collected_at": now(),
        "window": "today Asia/Shanghai",
        "requests": total,
        "server_errors": errors,
        "server_error_rate": round(errors / max(total, 1), 6),
        "last_completed_minute_qps": int(previous.get("requests", 0)) / 60,
        "endpoints": result,
        "device_queues": queue,
        "dead_letters": cache.xlen("telemetry:dead-letter"),
        "workers": workers,
        "capacity_validated": False,
    }
