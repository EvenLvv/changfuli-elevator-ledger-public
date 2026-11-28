"""Project work and system operations onto Shanghai calendar days."""
import json
from datetime import date, datetime

from .db import SHANGHAI
from .location import active_elevator_labels


# The old schema also permits work records without an audit entry. Include
# their creation once, while keeping each subsequent audited edit or deletion.
OPERATIONS = """
WITH operations AS (
    SELECT id, action, target, target_id, created_at, after_json, before_json
    FROM audit_logs WHERE {window}
    UNION ALL
    SELECT -id, '新增', '工作记录', CAST(id AS TEXT), created_at, NULL,
        (SELECT before_json FROM audit_logs WHERE target='工作记录' AND target_id=CAST(events.id AS TEXT)
            AND before_json IS NOT NULL ORDER BY id LIMIT 1)
    FROM events WHERE ({window}) AND NOT EXISTS (
        SELECT 1 FROM audit_logs WHERE target='工作记录' AND action='新增'
            AND target_id=CAST(events.id AS TEXT))
)
SELECT a.*, e.id event_id, e.elevator_id event_lift, e.title event_title, e.type work_type,
       e.completed, e.work_content, e.deleted_at event_deleted
FROM operations a
LEFT JOIN attachments f ON a.target='附件' AND f.id=a.target_id
LEFT JOIN events e ON e.id=CASE
    WHEN a.target IN ('工作记录','附件顺序') THEN a.target_id
    WHEN a.target='附件' THEN f.event_id END
"""

SYSTEM_TYPES = {'楼栋': '楼栋与单元', '单元': '楼栋与单元', '电梯': '电梯档案', '电梯状态': '电梯档案',
                '附件顺序': '附件', '局域网访问地址': '系统设置'}


def day_window(start, end):
    # Indexed ISO timestamp bounds, widened for historical timezone offsets.
    # Exact local dates (including subsecond midnight boundaries) are checked below.
    return (date.fromordinal(max(1, start.toordinal() - 1)).isoformat(),
            date.fromordinal(min(date.max.toordinal(), end.toordinal() + 1)).isoformat() + 'Z')


def operation(row, labels):
    snapshot = json.loads(row['after_json'] or row['before_json'] or '{}')
    action, target = row['action'], row['target']
    work = target == '工作记录' and action != '恢复'
    lift = row['event_lift']
    if target in ('电梯', '电梯状态'):
        lift = int(row['target_id'])
    if work:
        category = snapshot.get('type') or row['work_type'] or '其他'
        title = snapshot.get('title') or row['event_title'] or target
        summary = snapshot.get('resolution') or snapshot.get('work_content') or snapshot.get('symptom')
        if not snapshot and row['id'] < 0:
            summary = row['work_content']
        done = snapshot.get('completed', row['completed'])
        tags = [category, '已完成' if done else '待完成']
        kind = action + (category + '记录' if action == '新增' else target)
        tone = 'fault' if category == '故障' and action == '新增' else 'ok' if done and category == '日常维保' else 'work'
    else:
        category = action if action in ('导入', '导出', '备份', '恢复') else SYSTEM_TYPES.get(target, target)
        kind = '系统操作'
        title = action + target if target != '系统' else '系统' + action
        summary = (snapshot.get('summary') or snapshot.get('original_name') or snapshot.get('title')
                   or snapshot.get('name') or snapshot.get('status') or snapshot.get('value'))
        if not summary and action in ('备份', '导出'):
            summary = row['target_id']
        tags = [category]
        tone = 'sys'
    if lift:
        place = labels.get(lift, f'电梯档案 {lift}')
        summary = ' · '.join(filter(None, [place, summary]))
    stamp = datetime.fromisoformat(row['created_at'])
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=SHANGHAI)
    return dict(id=row['id'], timestamp=stamp.astimezone(SHANGHAI).isoformat(timespec='microseconds'),
                kind=kind, title=title, summary=(summary or '')[:220], tags=tags, type=category, tone=tone,
                elevator_id=lift, event_id=row['event_id'] if not row['event_deleted'] and lift in labels else None)


def timeline(db, start, end, month_start, month_end, elevator_id, category):
    labels = active_elevator_labels(db)[1]
    window = 'created_at BETWEEN ? AND ? OR created_at BETWEEN ? AND ?'
    bounds = (*day_window(start, end), *day_window(month_start, month_end))
    first, last, month = start.isoformat(), end.isoformat(), month_start.isoformat()[:7]
    items, dates = [], set()
    for row in db.execute(OPERATIONS.format(window=window), bounds * 2):
        item = operation(row, labels)
        if elevator_id is not None and item['elevator_id'] != elevator_id:
            continue
        if category and category not in (item['type'], item['kind']):
            continue
        day = item['timestamp'][:10]
        if day.startswith(month):
            dates.add(day)
        if first <= day <= last:
            items.append(item)
    items.sort(key=lambda entry: (entry['timestamp'], entry['id']), reverse=True)
    return {'items': items, 'dates': sorted(dates), 'total': len(items)}
