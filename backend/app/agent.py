"""Bounded, read-only business agent; deterministic planning, no LLM dependency."""

from datetime import timedelta
from .common import *
from . import catalog, charging
from .security import rate_limit


def chat(db, u, scope, b):
    require(set(b) <= {"message", "longitude", "latitude"}, message="不支持的Agent参数")
    text = (b.get("message") or "").strip()
    require(0 < len(text) <= 500, message="message须为1至500字")
    rate_limit(f"agent:{scope}:{u['id']}", 30, 60)
    result = {
        "engine": "RULE_BASED_TOOL_AGENT",
        "status": "answered",
        "answer": "",
        "tool_calls": [],
        "as_of": now(),
        "limitations": ["规则驱动的只读工具编排，未接入大模型；不执行预约、支付或设备控制。"],
    }

    def reply(answer, status="answered"):
        result.update(answer=answer, status=status)
        return result

    def record(name, source, data):
        result["tool_calls"].append({"tool": name, "source": source, "data": data})
        return data

    def allowed(*permissions):
        require(
            all(p + ":view" in u["permissions"] for p in permissions),
            40300,
            "当前账号无此Agent工具的数据查看权限",
        )

    if any(w in text for w in ("餐厅", "吃饭", "美食")):
        return reply("尚未接入餐饮地图数据，无法提供有依据的餐厅推荐。", "unsupported")
    if scope == "admin":
        report = any(w in text for w in ("报告", "报表", "总结"))
        revenue = report or any(w in text for w in ("收入", "营收", "收益"))
        ranking = report or "订单" in text or ("站点" in text and "排名" in text)
        faults = report or any(w in text for w in ("故障", "异常"))
        if not (revenue or ranking or faults):
            return reply(
                "可查询：今日站点订单排名、近一周营收、故障设备排行、近一周运营报告。",
                "unsupported",
            )
        # Preflight the entire plan before executing any tool.
        allowed(
            *(
                ({"dashboard"} if revenue else set())
                | ({"order", "station"} if ranking else set())
                | ({"fault", "pile"} if faults else set())
                | ({"user"} if report else set())
            )
        )
        end = now()
        begin = end.replace(hour=0, minute=0, second=0, microsecond=0)
        if "今天" not in text and "今日" not in text:
            begin -= timedelta(days=6)
        result["period"] = {"start": begin, "end": end}
        answers = []
        if revenue:
            from .admin_api import dashboard

            data = dashboard(
                db, {"startDate": begin.date().isoformat(), "endDate": end.date().isoformat()}
            )
            if report:
                data["new_user_count"] = count(
                    db, m.user, m.user.c.created_at >= begin, m.user.c.created_at <= end
                )
            record("operations_summary", "/api/v1/admin/dashboard/summary", data)
            answers.append(
                f"统计期内订单{data['order_count']}笔，净营收{money(data['platform_revenue'])}元（成功支付减成功退款）。"
            )
            if report:
                answers.append(
                    f"新增用户{data['new_user_count']}人；当前故障桩{data['fault_pile_count']}台。"
                )
        if ranking:
            data = [
                dict(r)
                for r in db.execute(
                    select(
                        m.station.c.id.label("station_id"),
                        m.station.c.station_name,
                        func.count().label("order_count"),
                    )
                    .join(m.order, m.order.c.station_id == m.station.c.id)
                    .where(m.order.c.created_at >= begin, m.order.c.created_at <= end)
                    .group_by(m.station.c.id)
                    .order_by(func.count().desc(), m.station.c.id)
                    .limit(5)
                ).mappings()
            ]
            record("station_order_ranking", "/api/v1/admin/orders", data)
            answers.append(
                "站点订单排名："
                + (
                    "；".join(f"{x['station_name']} {x['order_count']}笔" for x in data)
                    or "统计期内无订单"
                )
                + "。"
            )
        if faults:
            data = [
                dict(r)
                for r in db.execute(
                    select(
                        m.pile.c.id.label("pile_id"),
                        m.pile.c.pile_no,
                        func.count().label("fault_count"),
                    )
                    .join(m.fault, m.fault.c.pile_id == m.pile.c.id)
                    .where(m.fault.c.fault_time >= begin, m.fault.c.fault_time <= end)
                    .group_by(m.pile.c.id)
                    .order_by(func.count().desc(), m.pile.c.id)
                    .limit(5)
                ).mappings()
            ]
            record("fault_frequency", "/api/v1/admin/faults", data)
            answers.append(
                "故障记录排行："
                + (
                    "；".join(f"{x['pile_no']} {x['fault_count']}次" for x in data)
                    or "统计期内无故障记录"
                )
                + "。"
            )
        return reply("".join(answers))

    if any(w in text for w in ("附近", "推荐", "找站", "快充")):
        lon, lat = b.get("longitude"), b.get("latitude")
        if lon is None or lat is None:
            return reply(
                "请提供当前位置经纬度，以便按距离推荐附近空闲站点。", "needs_clarification"
            )
        require(-180 <= lon <= 180 and -90 <= lat <= 90, message="经纬度超出范围")
        q = {
            "longitude": str(lon),
            "latitude": str(lat),
            "sortBy": "DISTANCE",
            "idleOnly": "true",
            "pageSize": "3",
            "maxDistance": "10",
            "status": "OPEN",
        }
        if "快充" in text:
            q["pileType"] = "FAST"
        data = record(
            "nearby_idle_stations", "/api/v1/app/stations", catalog.stations(db, q, u["id"])
        )
        return reply(
            "附近10公里空闲站点："
            + (
                "；".join(f"{x['station_name']}，约{x['distance_km']}公里" for x in data["list"])
                or "暂无符合条件的站点"
            )
            + "。空闲状态可能变化，请进站前刷新。"
        )
    if any(w in text for w in ("最近", "上次", "历史", "上一")):
        o = (
            db.execute(
                select(m.order)
                .where(m.order.c.user_id == u["id"])
                .order_by(m.order.c.created_at.desc(), m.order.c.id.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        data = (
            None
            if not o
            else {
                k: o[k]
                for k in (
                    "id",
                    "order_no",
                    "payable_amount",
                    "payment_status",
                    "energy_kwh",
                    "created_at",
                )
            }
        )
        record("my_latest_order", "/api/v1/app/orders", data)
        return reply(
            "暂无充电订单。"
            if not data
            else f"最近订单{data['order_no']}，充电{data['energy_kwh']}度，应付{money(data['payable_amount'])}元，支付状态{data['payment_status']}。"
        )
    if any(w in text for w in ("充电", "费用", "多少钱", "故障", "异常", "电价")):
        s = one(
            db,
            m.session,
            m.session.c.user_id == u["id"],
            m.session.c.leave_time.is_(None),
            required=False,
        )
        if not s:
            record("my_current_session", "/api/v1/app/charging/sessions/current", None)
            return reply("当前没有未离场的充电会话。可查询最近订单或附近空闲站点。")
        view = record(
            "my_current_session",
            "/api/v1/app/charging/sessions/current",
            charging.session_view(db, s),
        )
        if "电价" in text:
            hm = now().strftime("%H:%M")
            price = next(
                (p for p in s["price_snapshot"] if p["start_time"] <= hm < p["end_time"]), None
            )
            record("session_price", "/api/v1/app/charging/sessions/current", price)
            return reply(
                "当前会话锁定费率中，此时段电价为"
                + str(price["electricity_price"])
                + "元/度，服务费为"
                + str(price["service_price"])
                + "元/度。"
                if price
                else "当前时段无可用费率记录。"
            )
        if any(w in text for w in ("故障", "异常")):
            p = get(db, m.pile, s["pile_id"])
            record(
                "current_pile_status",
                f"/api/v1/app/stations/{s['station_id']}",
                {"pile_id": p["id"], "status": p["status"]},
            )
            return reply(
                f"当前会话状态{s['status']}，设备状态{p['status']}。这只能辅助排查，无法远程确定故障原因；如设备异常，请停止操作并通过故障反馈联系工作人员。"
            )
        return reply(
            f"当前会话状态{s['status']}，已充{view['energy_kwh']}度，当前预估费用{money(view['current_amount'])}元，最终费用以离场订单为准。"
        )
    return reply(
        "可查询：附近空闲快充站、当前充电费用、最近一次订单、当前充电故障排查。", "unsupported"
    )
