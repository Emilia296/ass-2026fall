"""Small functional device simulator; not a load generator. Sends through the real ingestion queue."""

import time, logging
from decimal import Decimal
from sqlalchemy import select
from .db import Session, now
from .common import rows, get, m
from .security import DEMO
from .telemetry import sign, ingest


def tick():
    with Session() as db:
        active = rows(db, m.session, m.session.c.status == "CHARGING")
        for s in active:
            p = get(db, m.pile, s["pile_id"])
            at = now()
            energy = p["power_kw"] * Decimal(str((at - s["start_time"]).total_seconds())) / 3600
            event = {
                "pileId": p["id"],
                "sessionId": s["id"],
                "sequence": int(at.timestamp() * 1000),
                "energyKwh": str(max(s["energy_kwh"], energy)),
                "powerKw": str(p["power_kw"]),
                "observedAt": at.isoformat(),
            }
            event["signature"] = sign(event)
            ingest([event])


if __name__ == "__main__":
    if not DEMO:
        raise SystemExit("Simulator requires DEMO_MODE=true")
    while True:
        try:
            tick()
        except Exception:
            # Cumulative energy lets the next tick recover a temporarily failed enqueue.
            logging.exception("Simulator temporarily unable to enqueue; retrying")
        time.sleep(2)
