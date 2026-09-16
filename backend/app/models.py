"""33 business tables from 数据库.md. Additional snapshot columns preserve billing history."""

from sqlalchemy import (
    Table,
    Column,
    BigInteger,
    String,
    Text,
    Numeric,
    Boolean,
    DateTime,
    JSON,
    ForeignKey,
    Index,
    CheckConstraint,
    UniqueConstraint,
    text,
)
from .db import metadata, now


def table(name, fields, unique=(), checks=()):
    cols = [Column("id", BigInteger, primary_key=True)]
    for spec in fields.split():
        key, kind = spec.split(":", 1)
        nullable = kind.endswith("?")
        kind = kind.rstrip("?")
        default = None
        if "=" in kind:
            kind, default = kind.split("=")
        typ = {
            "s": String(255),
            "t": Text,
            "i": BigInteger,
            "n": Numeric(18, 6),
            "b": Boolean,
            "d": DateTime(timezone=True),
            "j": JSON,
        }.get(kind)
        args = []
        if kind.startswith("@"):
            typ = BigInteger
            args = [ForeignKey(kind[1:] + ".id")]
        if default is not None:
            default = {"true": True, "false": False}.get(
                default, int(default) if default.lstrip("-").isdigit() else default
            )
        cols.append(Column(key, typ, *args, nullable=nullable, default=default))
    if "created_at" not in [c.name for c in cols]:
        cols.append(Column("created_at", DateTime(timezone=True), nullable=False, default=now))
    return Table(
        name,
        metadata,
        *cols,
        *(UniqueConstraint(*x.split(",")) for x in unique),
        *(CheckConstraint(x) for x in checks),
    )


user = table(
    "user",
    "phone:s password_hash:s? nickname:s=车主 avatar:s? points_balance:i=0 credit_score:i=100 status:s=NORMAL failed_login_count:i=0 lock_until:d? manual_locked:b=false lock_reason:t? token_version:i=0 updated_at:d?",
    ["phone"],
    ["points_balance >= 0", "credit_score >= 0"],
)
vehicle = table(
    "user_vehicle",
    "user_id:@user plate_number:s vehicle_name:s? brand:s? model:s? battery_capacity:n current_soc:i=35 soc_source:s=MANUAL soc_updated_at:d? is_default:b=false status:s=NORMAL updated_at:d?",
    ["plate_number"],
    ["battery_capacity > 0", "current_soc BETWEEN 0 AND 100"],
)
station = table(
    "charging_station",
    "station_name:s city:s address:s longitude:n latitude:n business_start:s=00:00 business_end:s=24:00 contact_phone:s? parking_note:t? status:s=OPEN updated_at:d?",
)
pile = table(
    "charging_pile",
    "station_id:@charging_station pile_no:s pile_type:s power_kw:n qr_code:s status:s=IDLE updated_at:d?",
    ["pile_no", "qr_code"],
    ["pile_type IN ('FAST','SLOW')", "power_kw > 0"],
)
favorite = table(
    "station_favorite", "user_id:@user station_id:@charging_station", ["user_id,station_id"]
)
watch = table(
    "station_availability_watch",
    "user_id:@user station_id:@charging_station pile_type:s=ALL status:s=ACTIVE last_notified_at:d? cancelled_at:d?",
    ["user_id,station_id"],
)
reservation = table(
    "reservation",
    "reservation_no:s user_id:@user vehicle_id:@user_vehicle station_id:@charging_station pile_id:@charging_pile reservation_time:d expire_time:d arrived_at:d? status:s=WAITING updated_at:d? cancelled_at:d? credit_penalty_applied:b=false",
    ["reservation_no"],
)
plan = table(
    "charging_price_plan",
    "plan_name:s station_id:@charging_station pile_id:@charging_pile? version:s=v1 effective_from:d effective_to:d? status:s=ENABLED",
)
period = table(
    "charging_price_period",
    "plan_id:@charging_price_plan start_time:s end_time:s electricity_price:n service_price:n sort_no:i=0",
    checks=["electricity_price >= 0", "service_price >= 0"],
)
occupancy = table(
    "occupancy_fee_rule",
    "station_id:@charging_station? free_minutes:i=30 max_amount:n? status:s=ENABLED",
)
tier = table(
    "occupancy_fee_tier",
    "rule_id:@occupancy_fee_rule start_minute:i end_minute:i? price_per_minute:n",
)
session = table(
    "charging_session",
    "session_no:s user_id:@user vehicle_id:@user_vehicle station_id:@charging_station pile_id:@charging_pile reservation_id:@reservation? price_plan_id:@charging_price_plan occupancy_rule_id:@occupancy_fee_rule start_soc:i target_soc:i current_soc:i end_soc:i? energy_kwh:n=0 start_time:d charge_end_time:d? current_power_kw:n=0 free_leave_deadline:d? leave_time:d? status:s=CHARGING stop_reason:s? abnormal_reason:t? updated_at:d? price_snapshot:j occupancy_snapshot:j battery_capacity:n meter_sequence:i=-1 telemetry_at:d? fee_segments:j",
    ["session_no"],
    ["target_soc IN (80,90,100)"],
)
template = table(
    "coupon_template",
    "coupon_name:s coupon_type:s min_amount:n=0 discount_amount:n? discount_rate:n? max_discount:n? total_quantity:i per_user_limit:i=1 valid_type:s=AFTER_RECEIVE valid_from:d? valid_to:d? valid_days:i=15 points_cost:i=0 status:s=ISSUING",
    checks=["total_quantity >= 0", "per_user_limit > 0", "points_cost >= 0"],
)
coupon = table(
    "user_coupon",
    "user_id:@user template_id:@coupon_template coupon_code:s source_type:s status:s=UNUSED received_at:d valid_from:d valid_to:d used_at:d? order_id:i? min_amount_snapshot:n discount_amount_snapshot:n? discount_rate_snapshot:n? max_discount_snapshot:n? coupon_name_snapshot:s coupon_type_snapshot:s",
    ["coupon_code"],
)
event_rule = table(
    "coupon_event_rule",
    "event_type:s coupon_template_id:@coupon_template min_consume_amount:n=0 probability:n daily_limit:i=1 status:s=ENABLED",
    checks=["probability BETWEEN 0 AND 1", "daily_limit > 0"],
)
event_log = table(
    "coupon_event_log",
    "user_id:@user rule_id:@coupon_event_rule event_type:s triggered:b=false user_coupon_id:@user_coupon?",
)
points = table(
    "points_record",
    "user_id:@user change_type:s change_points:i balance_before:i balance_after:i biz_type:s biz_id:i remark:t?",
)
credit = table(
    "credit_record",
    "user_id:@user change_type:s change_score:i score_before:i score_after:i biz_type:s biz_id:i remark:t?",
)
order = table(
    "charging_order",
    "order_no:s user_id:@user session_id:@charging_session vehicle_id:@user_vehicle station_id:@charging_station pile_id:@charging_pile start_time:d charge_end_time:d leave_time:d duration_minutes:i energy_kwh:n electricity_fee:n service_fee:n occupancy_fee:n original_amount:n user_coupon_id:@user_coupon? coupon_discount:n=0 points_change:i=0 credit_change:i=0 payable_amount:n order_status:s=WAITING_PAYMENT payment_status:s=UNPAID overdue_at:d? paid_at:d? updated_at:d?",
    ["order_no", "session_id"],
    ["payable_amount >= 0"],
)
fee = table(
    "order_fee_detail",
    "order_id:@charging_order fee_type:s period_start:d period_end:d quantity:n unit_price:n amount:n description:t?",
)
payment = table(
    "payment_record",
    "payment_no:s order_id:@charging_order user_id:@user pay_method:s pay_amount:n status:s=SUCCESS transaction_no:s paid_at:d",
    ["payment_no", "order_id"],
)
message = table(
    "user_message",
    "user_id:@user message_type:s title:s content:t biz_type:s? biz_id:i? is_read:b=false read_at:d? is_deleted:b=false deleted_at:d?",
)
after_sale = table(
    "after_sales_application",
    "after_sales_no:s user_id:@user order_id:@charging_order type:s reason:t evidence:j? requested_amount:n status:s=PENDING handler_id:i? handle_result:t? handled_at:d?",
    ["after_sales_no"],
)
refund = table(
    "refund_record",
    "refund_no:s after_sales_id:@after_sales_application order_id:@charging_order payment_id:@payment_record refund_type:s refund_method:s=MOCK refund_amount:n refund_transaction_no:s coupon_returned:b=false status:s=SUCCESS failure_reason:t? refunded_at:d",
    ["refund_no", "after_sales_id"],
    ["refund_amount > 0"],
)
fault = table(
    "fault_record",
    "fault_no:s pile_id:@charging_pile station_id:@charging_station source_type:s reporter_user_id:@user? session_id:@charging_session? fault_type:s fault_description:t fault_time:d status:s=PENDING handler_id:i? handle_note:t? resolved_at:d?",
    ["fault_no"],
)
admin = table(
    "admin_user",
    "username:s password_hash:s real_name:s phone:s? status:s=ENABLED last_login_at:d? token_version:i=0",
    ["username"],
)
role = table("sys_role", "role_code:s role_name:s status:s=ENABLED", ["role_code"])
permission = table(
    "sys_permission",
    "permission_code:s permission_name:s permission_type:s parent_id:i? route:s?",
    ["permission_code"],
)
admin_role = table(
    "admin_user_role", "admin_user_id:@admin_user role_id:@sys_role", ["admin_user_id,role_id"]
)
role_permission = table(
    "role_permission", "role_id:@sys_role permission_id:@sys_permission", ["role_id,permission_id"]
)
audit = table(
    "operation_log",
    "admin_id:@admin_user role_name:s module:s operation_type:s target_type:s target_id:i? before_data:j? after_data:j? reason:t? result:s=SUCCESS",
)
login_log = table(
    "login_log",
    "account_type:s account_id:i? phone_or_username:s login_method:s ip_address:s? device_info:t? result:s fail_reason:t?",
)
config = table(
    "system_config", "config_key:s config_value:s description:t? updated_at:d?", ["config_key"]
)

Index(
    "uq_default_vehicle",
    vehicle.c.user_id,
    unique=True,
    postgresql_where=text("is_default AND status = 'NORMAL'"),
)
active = "status IN ('STARTING','CHARGING','STOPPING','CHARGE_FINISHED','OCCUPYING','SETTLING','ABNORMAL') AND leave_time IS NULL"
Index("uq_active_user_session", session.c.user_id, unique=True, postgresql_where=text(active))
Index("uq_active_pile_session", session.c.pile_id, unique=True, postgresql_where=text(active))
Index(
    "uq_active_reservation_pile",
    reservation.c.pile_id,
    unique=True,
    postgresql_where=text("status IN ('WAITING','ARRIVED','CHARGING')"),
)
Index(
    "uq_active_reservation_user",
    reservation.c.user_id,
    unique=True,
    postgresql_where=text("status IN ('WAITING','ARRIVED','CHARGING')"),
)
for t, names in [
    (pile, "station_id,status,pile_type"),
    (station, "city,status"),
    (session, "status,id"),
    (order, "user_id,created_at"),
    (order, "station_id,created_at"),
    (order, "payment_status,overdue_at"),
    (reservation, "status,expire_time"),
    (watch, "station_id,status,pile_type"),
    (message, "user_id,is_deleted,is_read"),
    (coupon, "template_id,user_id"),
    (coupon, "user_id,status"),
    (fault, "station_id,status"),
    (event_log, "user_id,rule_id,created_at"),
    (points, "user_id,created_at"),
    (credit, "user_id,created_at"),
    (fee, "order_id"),
    (refund, "order_id"),
]:
    Index("ix_" + t.name + "_" + names.replace(",", "_"), *(t.c[n] for n in names.split(",")))
for t, names in [
    (session, "status,updated_at"),
    (watch, "status,id"),
    (plan, "station_id,status,pile_id,effective_from"),
    (coupon, "status,valid_to"),
    (credit, "change_type,biz_id,user_id"),
    (audit, "created_at"),
    (login_log, "created_at"),
    (reservation, "user_id,created_at"),
    (after_sale, "user_id,status"),
    (order, "created_at"),
    (payment, "paid_at"),
    (refund, "refunded_at"),
]:
    Index("ix_" + t.name + "_" + names.replace(",", "_"), *(t.c[n] for n in names.split(",")))
