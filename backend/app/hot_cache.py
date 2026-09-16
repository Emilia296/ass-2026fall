"""Cross-process single-flight for read-only caches, with bounded waiting and fenced publication."""

import json
import secrets
import time
from .common import BizError, serial
from .security import cache

RELEASE = (
    "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end; return 0"
)
PUBLISH = """if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end
redis.call('SET',KEYS[2],ARGV[2],'EX',ARGV[3]); return 1"""


def remember(key, loader, ttl=2, wait_seconds=0.15):
    deadline = time.monotonic() + wait_seconds
    lock_key = key + ":fill"
    token = secrets.token_hex(16)
    while True:
        cached = cache.get(key)
        if cached is not None:
            return json.loads(cached)
        if cache.set(lock_key, token, nx=True, ex=35):
            try:
                # Another writer may have populated the value just before this lock acquisition.
                cached = cache.get(key)
                if cached is not None:
                    return json.loads(cached)
                value = serial(loader())
                # An expired owner cannot overwrite a successor's result.
                cache.eval(PUBLISH, 2, lock_key, key, token, json.dumps(value), ttl)
                return value
            finally:
                cache.eval(RELEASE, 1, lock_key, token)
        if time.monotonic() >= deadline:
            raise BizError(50300, "查询正在刷新，请稍后重试")
        time.sleep(0.01)
