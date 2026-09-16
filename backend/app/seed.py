"""Idempotent development seed, explicit invocation only."""

from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.schema import CreateTable, CreateIndex
from pathlib import Path
from .db import Session, engine, metadata, now
from .common import *
from .security import passwords, DEMO
from .admin_api import MODULES


def seed():
    require(DEMO, message="示例数据只能在DEMO_MODE=true下初始化")
    metadata.create_all(engine)
    for table in metadata.sorted_tables:
        for index in table.indexes:
            index.create(engine, checkfirst=True)
    with Session.begin() as db:
        if count(db, m.admin):
            return
        admin = add(
            db,
            m.admin,
            username="admin",
            password_hash=passwords.hash("Admin123!"),
            real_name="系统管理员",
        )
        operator = add(
            db,
            m.admin,
            username="operator",
            password_hash=passwords.hash("Operator123!"),
            real_name="运营人员",
        )
        maintainer = add(
            db,
            m.admin,
            username="maintainer",
            password_hash=passwords.hash("Maintainer123!"),
            real_name="运维人员",
        )
        roles = [
            add(db, m.role, role_code=c, role_name=n)
            for c, n in [
                ("ADMIN", "系统管理员"),
                ("OPERATOR", "运营人员"),
                ("MAINTAINER", "运维人员"),
            ]
        ]
        for a, r in zip([admin, operator, maintainer], roles):
            add(db, m.admin_role, admin_user_id=a["id"], role_id=r["id"])
        for module in sorted(set(MODULES.values())):
            parent = add(
                db,
                m.permission,
                permission_code=module,
                permission_name=module,
                permission_type="MENU",
                route="/admin/" + module,
            )
            for action in ("view", "edit"):
                p = add(
                    db,
                    m.permission,
                    permission_code=module + ":" + action,
                    permission_name="查看" if action == "view" else "编辑",
                    permission_type="BUTTON",
                    parent_id=parent["id"],
                )
                for r in roles:
                    if (
                        r["role_code"] == "ADMIN"
                        or r["role_code"] == "OPERATOR"
                        and module not in ("system", "audit")
                        or r["role_code"] == "MAINTAINER"
                        and module in ("pile", "fault", "station", "dashboard")
                        and (module in ("pile", "fault") or action == "view")
                    ):
                        add(db, m.role_permission, role_id=r["id"], permission_id=p["id"])
        for phone, name in [("13800138000", "演示车主"), ("13800138001", "第二位车主")]:
            u = add(
                db,
                m.user,
                phone=phone,
                nickname=name,
                password_hash=passwords.hash("User123!"),
                points_balance=1000,
            )
            add(
                db,
                m.vehicle,
                user_id=u["id"],
                plate_number="京A·D1234" + str(u["id"]),
                vehicle_name="我的 E7",
                brand="演示车型",
                model="E7",
                battery_capacity=75,
                current_soc=40,
                is_default=True,
                soc_updated_at=now(),
            )
        for name, addr, lon, lat in [
            ("朝阳大悦城充电站", "北京市朝阳区青年路99号", 116.518, 39.925),
            ("国贸 CBD 充电站", "北京市朝阳区建国门外大街1号", 116.461, 39.909),
            ("三里屯太古里充电站", "北京市朝阳区三里屯路19号", 116.455, 39.937),
        ]:
            s = add(
                db,
                m.station,
                station_name=name,
                city="北京",
                address=addr,
                longitude=lon,
                latitude=lat,
                contact_phone="010-12345678",
                parking_note="充电结束后30分钟免费驶离，之后按阶梯收取占桩费。",
            )
            for i in range(1, 7):
                no = f"BJ-{s['id']:03d}-{i:03d}"
                add(
                    db,
                    m.pile,
                    station_id=s["id"],
                    pile_no=no,
                    pile_type="FAST" if i <= 4 else "SLOW",
                    power_kw=120 if i <= 4 else 7,
                    qr_code="PILE:" + no,
                    status="FAULT" if i == 6 else "IDLE",
                )
            p = add(
                db,
                m.plan,
                plan_name=name + "标准分时电价",
                station_id=s["id"],
                effective_from=now() - timedelta(days=1),
            )
            for i, (a, z, e, f) in enumerate(
                [
                    ("00:00", "07:00", ".45", ".30"),
                    ("07:00", "10:00", ".85", ".40"),
                    ("10:00", "17:00", ".65", ".35"),
                    ("17:00", "22:00", ".95", ".45"),
                    ("22:00", "24:00", ".55", ".30"),
                ]
            ):
                add(
                    db,
                    m.period,
                    plan_id=p["id"],
                    start_time=a,
                    end_time=z,
                    electricity_price=Decimal(e),
                    service_price=Decimal(f),
                    sort_no=i + 1,
                )
        r = add(db, m.occupancy, free_minutes=30, max_amount=30)
        add(
            db,
            m.tier,
            rule_id=r["id"],
            start_minute=31,
            end_minute=60,
            price_per_minute=Decimal(".1"),
        )
        add(db, m.tier, rule_id=r["id"], start_minute=61, price_per_minute=Decimal(".2"))
        t = add(
            db,
            m.template,
            coupon_name="满20减5",
            coupon_type="FULL_CUT",
            min_amount=20,
            discount_amount=5,
            total_quantity=1000,
            per_user_limit=5,
            points_cost=500,
        )
        add(
            db,
            m.event_rule,
            event_type="DAILY_LOGIN",
            coupon_template_id=t["id"],
            probability=Decimal(".2"),
            daily_limit=1,
        )
        for key, val, desc in [
            ("PAYMENT_OVERDUE_HOURS", "24", "订单欠费超时小时数"),
            ("MIN_CREDIT_FOR_RESERVATION", "80", "允许预约的最低信誉分"),
            ("MAX_CREDIT_SCORE", "120", "最高信誉分"),
            ("CREDIT_DAILY_RECOVERY", "1", "每日信誉恢复"),
            ("RESERVATION_TIMEOUT_MINUTES", "15", "预约到场宽限分钟数"),
            ("CUSTOMER_SERVICE_PHONE", "400-000-0000", "客服电话"),
            ("CUSTOMER_SERVICE_TIME", "09:00-18:00", "客服时间"),
        ]:
            add(db, m.config, config_key=key, config_value=val, description=desc)
    print("Initialized 33 business tables and development seed.")


def export_sql():
    sql = "-- Generated schema from app/models.py. PostgreSQL 16+.\n"
    for table in metadata.sorted_tables:
        sql += str(CreateTable(table).compile(engine)) + ";\n"
    for table in metadata.sorted_tables:
        for index in sorted(table.indexes, key=lambda x: x.name):
            sql += str(CreateIndex(index).compile(engine)) + ";\n"
    path = Path(__file__).parent.parent / "migrations/001_initial.sql"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(line.rstrip() for line in sql.splitlines()) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys

    seed()
    if "--export-sql" in sys.argv:
        export_sql()
