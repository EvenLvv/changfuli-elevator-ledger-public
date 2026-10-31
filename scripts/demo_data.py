import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import connect, init_db, now
from backend.main import add_building, add_elevator, add_event, add_unit


def install_demo():
    init_db()
    with connect() as db:
        if db.execute("SELECT 1 FROM system_settings WHERE key='demo_ids'").fetchone():
            raise SystemExit("演示数据已经存在。")
        admin = db.execute("SELECT id FROM users WHERE role='admin' AND active=1 ORDER BY id LIMIT 1").fetchone()
    if not admin:
        raise SystemExit("请先在浏览器中设置管理员，再生成演示数据。")
    user = {"id": admin[0], "role": "admin"}
    with connect() as db:
        names = {row[0] for row in db.execute("SELECT name FROM buildings")}
    name = "演示18栋"
    number = 2
    while name in names:
        name = f"演示18栋（{number}）"
        number += 1
    building = add_building({"name": name}, user)["id"]
    unit = add_unit({"building_id": building, "name": "1单元"}, user)["id"]
    elevator_ids = []
    for number in (1, 2):
        elevator_ids.append(add_elevator({"unit_id": unit, "name": f"{number}号梯", "equipment_number": f"DEMO-18-1-{number}",
          "brand": "演示品牌", "maintenance_company": "演示维保单位",
          "inspection_on": (date.today() + timedelta(days=20)).isoformat(),
          "maintenance_due_on": (date.today() + timedelta(days=6)).isoformat()}, user)["id"])
    events = []
    for typ, title, offset in (("日常维保", "半月维保检查", -15), ("故障", "3层厅门无法关闭", -12),
                               ("维修", "检查门锁线路并恢复运行", -11)):
        events.append(add_event({"elevator_id": elevator_ids[0], "type": typ, "title": title,
             "occurred_on": (date.today() + timedelta(days=offset)).isoformat(),
             "work_content": "演示数据：检查现场并填写工作记录。", "resolution": "已完成处理。",
             "cost_yuan": "100" if typ == "维修" else "0", "notes": "[演示数据]"}, user)["id"])
    for offset, warranty in ((-400, 365), (-3, 10)):
        when = (date.today() + timedelta(days=offset)).isoformat()
        events.append(add_event({"elevator_id": elevator_ids[0], "type": "配件更换", "title": "更换门锁开关",
          "occurred_on": when, "work_content": "演示数据：更换门锁开关。", "notes": "[演示数据]",
          "parts": [{"name": "门锁开关", "quantity": 1, "unit_price_yuan": "260", "replaced_on": when,
                     "warranty_days": warranty}]}, user)["id"])
    with connect() as db:
        db.execute("INSERT INTO system_settings(key,value) VALUES('demo_ids',?)",
                   (json.dumps({"building": building, "unit": unit, "elevators": elevator_ids, "events": events}),))
    print(f"演示数据已生成：{name} / 1单元 / 1号梯、2号梯。")


def remove_demo():
    with connect() as db:
        row = db.execute("SELECT value FROM system_settings WHERE key='demo_ids'").fetchone()
        if not row:
            raise SystemExit("没有需要删除的演示数据。")
        ids = json.loads(row[0])
        placeholders = ','.join('?' for _ in ids['elevators'])
        other = db.execute(f"SELECT COUNT(*) FROM events WHERE elevator_id IN ({placeholders}) AND id NOT IN ({','.join('?' for _ in ids['events'])}) AND deleted_at IS NULL",
                           [*ids['elevators'], *ids['events']]).fetchone()[0]
        if other:
            raise SystemExit("演示电梯中已有新工作记录，已停止删除。请先人工核对。")
        if db.execute("SELECT 1 FROM units WHERE building_id=? AND id<>? AND deleted_at IS NULL", (ids['building'], ids['unit'])).fetchone():
            raise SystemExit("演示楼栋中已有新单元，已停止删除。")
        if db.execute(f"SELECT 1 FROM elevators WHERE unit_id=? AND id NOT IN ({placeholders}) AND deleted_at IS NULL", [ids['unit'], *ids['elevators']]).fetchone():
            raise SystemExit("演示单元中已有新电梯，已停止删除。")
        for event_id in ids['events']:
            changed = db.execute("SELECT 1 FROM events WHERE id=? AND updated_at<>created_at", (event_id,)).fetchone()
            edited = db.execute("SELECT 1 FROM audit_logs WHERE target='工作记录' AND target_id=? AND action='修改'", (str(event_id),)).fetchone()
            files = db.execute("SELECT 1 FROM attachments WHERE event_id=?", (event_id,)).fetchone()
            if changed or edited or files:
                raise SystemExit("演示记录已有修改或附件，已停止删除。请先人工核对。")
        stamp = now()
        for table, record_ids in (("events", ids['events']), ("elevators", ids['elevators']),
                                  ("units", [ids['unit']]), ("buildings", [ids['building']])):
            for record_id in record_ids:
                db.execute(f"UPDATE {table} SET deleted_at=? WHERE id=?", (stamp, record_id))
        db.execute("DELETE FROM system_settings WHERE key='demo_ids'")
    print("演示数据已从日常页面移除。历史数据库内容仍保留。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成或移除演示数据")
    parser.add_argument("--remove", action="store_true", help="软删除演示数据")
    args = parser.parse_args()
    remove_demo() if args.remove else install_demo()
