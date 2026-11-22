import re
from collections import Counter


NUMBER_PATTERNS = {
    'buildings': re.compile(r'([0-9]+)\s*(?:栋|号楼|楼)?'),
    'units': re.compile(r'([0-9]+)\s*(?:单元口|单元|口)?'),
    'elevators': re.compile(r'([0-9]+)\s*(?:号电梯|号梯|号|梯)?'),
}


def archive_number(table, name):
    match = NUMBER_PATTERNS[table].fullmatch(name.strip())
    return (match[1].lstrip('0') or '0') if match else None


def elevator_label(item):
    name = item['elevator_name'] if 'elevator_name' in item.keys() else item['name']
    parts = []
    for table, value, suffix in (
        ('buildings', item['building_name'], '栋'),
        ('units', item['unit_name'], '口'),
        ('elevators', name, '号电梯'),
    ):
        number = archive_number(table, value)
        parts.append(number + suffix if number is not None else value)
    return ''.join(parts)


def active_elevator_labels(db):
    locations = list(db.execute('''
        SELECT e.id,e.name,u.name unit_name,b.name building_name FROM elevators e
        JOIN units u ON u.id=e.unit_id JOIN buildings b ON b.id=u.building_id
        WHERE e.deleted_at IS NULL AND u.deleted_at IS NULL AND b.deleted_at IS NULL
    '''))
    canonical = {item['id']: elevator_label(item) for item in locations}
    counts = Counter(canonical.values())
    display = canonical.copy()
    for item in locations:
        elevator_id = item['id']
        label = canonical[elevator_id]
        if counts[label] > 1:
            display[elevator_id] = f"{label}（档案 {elevator_id} · {item['building_name']} / {item['unit_name']} / {item['name']}）"
    return canonical, display


def add_elevator_labels(items, labels):
    for item in items:
        elevator_id = item['elevator_id'] if 'elevator_id' in item else item['id']
        item['location_label'] = labels.get(elevator_id) or elevator_label(item)
    return items


def export_elevator_label(item):
    return item.get('export_label') or f"{item['building_name']} {item['unit_name']} {item['name']}"
