from decimal import Decimal
from app.billing import split_energy, occupancy_details, validate_periods
from app.billing import settle_details
from app.common import dt
from datetime import timedelta
import pytest


def test_cross_tariff_midnight_decimal():
    p = [
        {
            "start_time": "00:00",
            "end_time": "22:00",
            "electricity_price": ".95",
            "service_price": ".4",
        },
        {
            "start_time": "22:00",
            "end_time": "24:00",
            "electricity_price": ".55",
            "service_price": ".3",
        },
    ]
    ds = split_energy("2026-09-15T21:30:00+08:00", "2026-09-15T23:30:00+08:00", 32, p)
    assert sum(Decimal(d["amount"]) for d in ds if d["fee_type"] == "ELECTRICITY") == Decimal(
        "20.80"
    )
    ds = split_energy("2026-09-15T23:30:00+08:00", "2026-09-16T00:30:00+08:00", 10, p)
    assert len(ds) == 4 and sum(
        Decimal(d["amount"]) for d in ds if d["fee_type"] == "ELECTRICITY"
    ) == Decimal("7.50")
    rounded = settle_details(
        [
            {"fee_type": "ELECTRICITY", "amount": ".005"},
            {"fee_type": "ELECTRICITY", "amount": ".005"},
        ]
    )
    assert sum(Decimal(x["amount"]) for x in rounded) == Decimal(".01")


@pytest.mark.parametrize(
    "seconds,expected",
    [(1800, "0"), (1801, ".1"), (3600, "3"), (3601, "3.2"), (7200, "15"), (18000, "30")],
)
def test_occupancy_boundaries(seconds, expected):
    a = dt("2026-09-15T10:00:00+08:00")
    r = {
        "free_minutes": 30,
        "max_amount": 30,
        "tiers": [
            {"start_minute": 31, "end_minute": 60, "price_per_minute": ".1"},
            {"start_minute": 61, "end_minute": None, "price_per_minute": ".2"},
        ],
    }
    ds = occupancy_details(a, a + timedelta(seconds=seconds), r)
    assert sum((Decimal(d["amount"]) for d in ds), Decimal(0)) == Decimal(expected)
