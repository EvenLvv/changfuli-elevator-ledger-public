"""Read the two-sheet ledger and reconcile it within the caller's SQLite transaction."""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .location import archive_number


@dataclass
class OfficialWorkbook:
    elevators: list
    faults: list
    templates: int


def text(value):
    return '' if value is None else str(value).strip()


def timestamp(value, label, epoch):
    if value in (None, ''):
        return ''
    try:
        if type(value) in (int, float):
            value = epoch + timedelta(days=value)
        elif type(value) is date:
            value = datetime.combine(value, time())
        elif not isinstance(value, datetime):
            value = datetime.fromisoformat(text(value))
        return value.isoformat()
    except (ValueError, OverflowError) as exc:
        raise ValueError(f'{label}日期无效') from exc


def sheet_rows(sheet, width, headers, limit):
    sheet.reset_dimensions()
    rows = sheet.iter_rows(max_col=width)
    next(rows, None)  # merged title
    for expected in headers:
        row = next(rows, ())
        actual = [''.join(text(cell.value).split()) for cell in row]
        if actual[:len(expected)] != expected:
            raise ValueError(f'“{sheet.title.strip()}”表头不匹配，请保留正式台账列顺序')
    for number, row in enumerate(rows, 2 + len(headers)):
        if number > 1 + len(headers) + limit:
            raise ValueError(f'“{sheet.title.strip()}”每次最多检查{limit}行')
        if any(cell.data_type in ('f', 'e') for cell in row):
            raise ValueError(f'“{sheet.title.strip()}”第{number}行含公式或错误值')
        if any(cell.value is not None for cell in row):
            yield number, [cell.value for cell in row]


def read_official_workbook(workbook):
    assets = [s for s in workbook if s.title.strip().endswith('特种设备台账')]
    faults = [s for s in workbook if s.title.strip() == '故障消缺记录']
    if len(assets) != 1 or len(faults) != 1:
        raise ValueError('请选择电梯档案模板，或同时含“特种设备台账”和“故障消缺记录”的表格')
    lifts, events, templates = [], [], 0
    header = ['序号', '设备名称', '设备型号', '使用登记证号（车牌号）', '设备使用（内部编号）',
              '产权归属', '投入使用时间', '维保单位', '检验日期', '备注']
    for n, row in sheet_rows(assets[0], 10, [header], 500):
        if not any(text(v) for v in row[1:]):
            continue
        code = text(row[4]).upper()
        if code == 'WY0001':
            building, unit, name = '物业站', '站内', '站内电梯'
        elif re.fullmatch('[0-9]{6}', code):
            building, unit, name = (str(int(code[i:i+2])) + suffix for i, suffix in
                                    [(0, '栋'), (2, '单元'), (4, '号电梯')])
        else:
            raise ValueError(f'台账第{n}行内部编号应为六位数字或 WY0001')
        notes = [text(row[9])]
        if text(row[5]):
            notes.append('产权归属：' + text(row[5]))
        lifts.append((n, dict(building_name=building, unit_name=unit, name=name,
                              equipment_number=text(row[3]), internal_number=code, model=text(row[2]),
                              started_on=timestamp(row[6], f'台账第{n}行投入使用时间', workbook.epoch)[:10],
                              maintenance_company=text(row[7]), inspection_on=timestamp(row[8], f'台账第{n}行检验', workbook.epoch)[:10],
                              notes='\n'.join(filter(None, notes)))))
    headers = [['序号', '电梯安装地点', '设备型号', '电梯站数', '发生故障情况', '', '处理故障情况'],
               ['', '', '', '', '发生故障时间', '发生故障名称', '故障处理时间', '故障处理方法（含调试或更换配件的名称及数量）']]
    for n, row in sheet_rows(faults[0], 11, headers, 5000):
        if not any(text(row[i]) for i in (1, 3, 4, 5, 6, 7, 8, 9, 10)):
            templates += 1
            continue
        location, symptom, remedy = (text(row[i]) for i in (1, 5, 7))
        fault_at = timestamp(row[4], f'故障记录第{n}行发生', workbook.epoch)
        ended_at = timestamp(row[6], f'故障记录第{n}行处理', workbook.epoch)
        if not fault_at or not symptom:
            raise ValueError(f'故障记录第{n}行缺少发生故障时间或故障名称')
        part = re.match(r'^更换\s*(.+)', remedy)
        data = dict(type='配件更换' if part else '故障', title=symptom[:120], symptom=symptom,
                    occurred_on=fault_at[:10], fault_at=fault_at, ended_at=ended_at, remedy=remedy,
                    work_content=remedy, completed=bool(ended_at), uses_maintenance_fund=text(row[10]) == '维修资金')
        if part:
            data['parts'] = [dict(name=part[1].strip()[:100], replaced_on=(ended_at or fault_at)[:10])]
        events.append((n, location, data))
    return OfficialWorkbook(lifts, events, templates)


def location_key(location):
    label = ''.join(location.split())
    if label == '物业站':
        return ('物业站',)
    match = re.fullmatch(r'(?:[^0-9]|[0-9]+[^0-9栋])*([0-9]+)栋([0-9]+)(?:单元|口)(?:([0-9]+)号?)?电梯', label)
    return tuple(str(int(v)) for v in match.groups() if v is not None) if match else None


def index_location(index, item, lift_id):
    if text(item['internal_number']).upper() == 'WY0001':
        index[('物业站',)].add(lift_id)
    building = archive_number('buildings', item['building_name'])
    unit = archive_number('units', item['unit_name'])
    if building is None or unit is None:
        return
    index[building, unit].add(lift_id)
    number = archive_number('elevators', item['name'])
    code = text(item['internal_number'])
    if number is None and re.fullmatch('[0-9]{6}', code):
        number = str(int(code[-2:]))
    if number is not None:
        index[building, unit, number].add(lift_id)


def reconcile(db, workbook, user, create_lift, insert_event):
    # All lookups include this transaction's additions. Deleted identities must
    # be restored explicitly, even when their registration number matches.
    locations = defaultdict(set)
    by_code, by_registration = defaultdict(list), defaultdict(list)
    labels = {}

    def index_identity(item):
        labels[item['id']] = ' / '.join(item[k] for k in ('building_name', 'unit_name', 'name'))
        by_code[text(item['internal_number']).upper()].append(item)
        if text(item['equipment_number']):
            by_registration[text(item['equipment_number'])].append(item)

    for item in db.execute("""SELECT e.*, u.name unit_name, b.name building_name,
            COALESCE(e.deleted_at,u.deleted_at,b.deleted_at) inactive FROM elevators e
            JOIN units u ON u.id=e.unit_id JOIN buildings b ON b.id=u.building_id"""):
        index_identity(item)
        if not item['inactive']:
            index_location(locations, item, item['id'])

    counts = Counter(data['internal_number'] for _, data in workbook.elevators)
    report = dict(format='official', valid=True, errors=[], rows=[], added=0, skipped=0,
                  events_added=0, events_skipped=0, event_rows=[], warnings=[], unmatched=[], templates_skipped=workbook.templates)
    for n, data in workbook.elevators:
        code, registration = data['internal_number'], data['equipment_number']
        matches = by_registration.get(registration, [])
        if not matches and counts[code] == 1 and len(by_code[code]) == 1:
            candidate = by_code[code][0]
            if not registration or not text(candidate['equipment_number']):
                matches = [candidate]
        if len(matches) > 1 or (matches and matches[0]['inactive']):
            raise ValueError(f'台账第{n}行匹配多部或已删除的电梯，请先核对档案')
        if not registration and (counts[code] > 1 or len(by_code[code]) > 1):
            raise ValueError(f'台账第{n}行内部编号重复，请补齐使用登记证号')
        if matches:
            lift = matches[0]
            action = '跳过'
            report['skipped'] += 1
        else:
            lift = create_lift(db, data, user)
            index_identity(lift)
            action = '新增'
            report['added'] += 1
        index_location(locations, data, lift['id'])
        report['rows'].append(dict(row=n, place=labels[lift['id']],
                                   action=action, elevator_id=lift['id'], unit_id=lift['unit_id']))
    for code in counts:
        if counts[code] > 1 or len(by_code[code]) > 1:
            report['warnings'].append(f'内部编号 {code} 重复，可能为笔误。请按使用登记证号核对，原编号已保留。')

    for n, place, data in workbook.faults:
        ids = locations.get(location_key(place), set())
        if len(ids) != 1:
            reason = '位置对应多部电梯' if ids else '未找到对应电梯'
            report['unmatched'].append(dict(row=n, location=place, reason=reason))
            continue
        lift_id, = ids
        existing = db.execute("""SELECT id, fault_at FROM events WHERE elevator_id=? AND deleted_at IS NULL
            AND COALESCE(NULLIF(symptom,''), title)=?
            AND COALESCE(NULLIF(remedy,''), NULLIF(work_content,''), resolution, '')=?""",
                              (lift_id, data['symptom'], data['remedy']))
        matched = next((r['id'] for r in existing if r['fault_at'] and
                        datetime.fromisoformat(r['fault_at']) == datetime.fromisoformat(data['fault_at'])), None)
        if matched is None:
            insert_event(db, dict(data, elevator_id=lift_id), user)
            report['events_added'] += 1
        else:
            report['events_skipped'] += 1
        report['event_rows'].append(dict(row=n, title=data['title'], place=labels[lift_id],
                                         date=data['occurred_on'], elevator_id=lift_id, existing_id=matched,
                                         action='新增' if matched is None else '跳过'))
    return report
