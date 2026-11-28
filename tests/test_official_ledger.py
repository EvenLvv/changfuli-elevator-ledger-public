import io
import json
import os
import shutil
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900

from backend.official_ledger import location_key, read_official_workbook
from support import isolated_app


FIXTURE = Path(__file__).parent / 'fixtures/synthetic-ledger-fixture.xlsx'


class OfficialLedgerTest(unittest.TestCase):
    def setUp(self):
        self.context = isolated_app()
        self.client, self.paths = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    def post(self, path, data):
        response = self.client.post(path, json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def upload(self, *, token=None, raw=None):
        return self.client.post('/api/elevator-archives/import', params={'dry_run': token is None},
                                files={'file': (FIXTURE.name, raw or FIXTURE.read_bytes())},
                                data={} if token is None else {'preview_token': token})

    def test_location_key(self):
        for label in ('昌福里社区27区41栋1单元1号电梯', '41栋1单元1号电梯', '41栋 1单元 1电梯'):
            self.assertEqual(location_key(label), ('41', '1', '1'))
        self.assertEqual(location_key('馨河44栋1单元电梯'), ('44', '1'))
        self.assertEqual(location_key('物业站'), ('物业站',))

    def test_workbook_date_epochs(self):
        for epoch, day in ((CALENDAR_WINDOWS_1900, '2021-01-04'), (CALENDAR_MAC_1904, '2025-01-05')):
            with self.subTest(epoch=epoch):
                workbook = load_workbook(FIXTURE)
                workbook.epoch = epoch
                assets, faults = workbook.worksheets[:2]
                for cell in (assets['G3'], assets['I3'], faults['E4'], faults['G4']):
                    cell.value = 44200
                    cell.number_format = 'General'
                faults['E5'] = datetime(2025, 1, 5, 8, 35)
                stream = io.BytesIO()
                workbook.save(stream)
                workbook.close()
                stream.seek(0)
                workbook = load_workbook(stream, read_only=True)
                try:
                    ledger = read_official_workbook(workbook)
                finally:
                    workbook.close()
                lift, fault = ledger.elevators[0][1], ledger.faults[0][2]
                self.assertEqual((lift['started_on'], lift['inspection_on']), (day, day))
                self.assertEqual((fault['fault_at'], fault['ended_at']), (day + 'T00:00:00',) * 2)
                self.assertEqual(ledger.faults[1][2]['fault_at'], '2025-01-05T08:35:00')

    def test_two_sheet_preview_commit_and_reimport(self):
        preview = self.upload().json()
        self.assertEqual(self.client.get('/api/elevators').json(), [])
        self.assertEqual(self.client.get('/api/events').json(), [])
        report = self.upload(token=preview['preview_token']).json()
        for item in (preview, report):
            self.assertEqual((item['added'], item['skipped'], item['events_added'], item['events_skipped'],
                              item['templates_skipped']), (9, 0, 5, 0, 3))
            self.assertEqual(item['unmatched'], [dict(row=9, location='馨河44栋1单元电梯', reason='位置对应多部电梯')])
            self.assertEqual(len(item['warnings']), 1)
            self.assertIn('440201', item['warnings'][0])
        self.assertTrue(report['committed'])
        lifts = self.client.get('/api/elevators').json()
        self.assertCountEqual([e['internal_number'] for e in lifts],
                              ['410101', '410201', '410301', '440101', '440102', '530102', 'WY0001', '440201', '440201'])
        duplicates = [e for e in lifts if e['internal_number'] == '440201']
        self.assertCountEqual([e['equipment_number'] for e in duplicates], ['测C-20001', '测C-20002'])
        self.assertEqual(len({e['name'] for e in duplicates}), 2)
        by_code = {e['internal_number']: e for e in lifts}
        first = by_code['410101']
        self.assertEqual((first['building_name'], first['unit_name'], first['name']), ('41栋','1单元','1号电梯'))
        self.assertEqual(first['inspection_on'], '2025-06-15')
        self.assertIn('合成夹具备注', first['notes'])
        self.assertIn('测试物业', first['notes'])
        self.assertEqual(first['model'], 'OH5100')
        self.assertEqual(first['maintenance_company'], '测试维保公司')
        self.assertTrue(first['started_on'])
        self.assertFalse(by_code['WY0001']['started_on'])
        self.assertFalse(by_code['WY0001']['model'])
        self.assertEqual(by_code['WY0001']['building_name'], '物业站')

        events = self.client.get('/api/events').json()
        self.assertCountEqual([v['elevator_id'] for v in events],
                              [by_code[c]['id'] for c in ('410101','410101','440102','530102','WY0001')])
        for event in events:
            self.assertEqual(event['type'], '配件更换')
            self.assertEqual(event['remedy'], '更换' + event['parts'][0]['name'])
            self.assertEqual(event['symptom'], event['title'])
            self.assertEqual(event['ended_at'][:10], event['parts'][0]['replaced_on'])
        earliest = min(events, key=lambda v: v['fault_at'])
        self.assertEqual((earliest['occurred_on'], earliest['fault_at'][:10]), ('2025-01-05','2025-01-05'))
        funded, = [v for v in events if v['uses_maintenance_fund']]
        self.assertEqual(funded['elevator_id'], by_code['440102']['id'])
        self.assertIsNone(funded['maintenance_fund_cents'])
        replay = self.upload().json()
        again = self.upload(token=replay['preview_token']).json()
        self.assertEqual((again['added'], again['skipped'], again['events_added'], again['events_skipped']), (0,9,0,5))
        self.assertEqual(again['unmatched'], report['unmatched'])

    def test_naive_fault_time_matches_existing_shanghai_event(self):
        lift = self.post('/api/elevators', dict(building_name='41栋', unit_name='1单元',
                         name='1号电梯', internal_number='410101'))
        workbook = load_workbook(FIXTURE)
        faults = workbook.worksheets[1]
        faults.delete_rows(5, faults.max_row - 4)
        faults['E4'] = datetime(2025, 1, 5, 8, 35)
        event = dict(elevator_id=lift['id'], type='故障', title=faults['F4'].value,
                     remedy=faults['H4'].value, occurred_on='2025-01-05')
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()

        # Same clock reading in UTC is a different fault instant.
        self.post('/api/events', dict(event, fault_at='2025-01-05T08:35:00+00:00'))
        raw = stream.getvalue()
        different = self.upload(raw=raw).json()
        self.assertEqual((different['events_added'], different['events_skipped']), (1, 0))

        local_time = '2025-01-05T08:35:00+08:00'
        duplicate = self.post('/api/events', dict(event, fault_at=local_time))
        preview = self.upload(raw=raw).json()
        committed = self.upload(raw=raw, token=preview['preview_token']).json()
        for result in (preview, committed):
            self.assertEqual((result['events_added'], result['events_skipped']), (0, 1))
            self.assertEqual(result['event_rows'][0]['existing_id'], duplicate['id'])
        self.assertEqual(len(self.client.get('/api/events').json()), 2)
        self.assertEqual(self.client.get(f"/api/events/{duplicate['id']}").json()['fault_at'], local_time)

    def test_existing_identities_real_time_and_stale_preview(self):
        old = dict(building_name='41栋', unit_name='1口', name='1号梯', internal_number='410101',
                   maintenance_contact='测试人员', maintenance_phone='000000', brand='测试品牌',
                   maintenance_due_on='2026-12-01', status='待处理')
        lift = self.post('/api/elevators', old)['id']
        # Same registration takes precedence over a different internal number.
        second = self.post('/api/elevators', dict(building_name='41栋', unit_name='2口', name='1号梯',
                           internal_number='990101', equipment_number='测C-10002'))['id']
        workbook = load_workbook(FIXTURE)
        assets, faults = workbook.worksheets[:2]
        assets['E9'] = 'wy0001'
        assets['E3'] = 410101
        faults['E4'] = datetime(2025, 1, 5, 8, 35)
        faults['G4'] = datetime(2025, 1, 5, 9, 40)
        faults['H4'] = '现场调试'
        faults['B4'] = '昌福里社区27区41栋1单元1号电梯'
        faults['K4'] = ' 维修资金 '
        stream = io.BytesIO()
        workbook.save(stream)
        workbook.close()
        raw = stream.getvalue()
        preview = self.upload(raw=raw).json()
        self.assertEqual(preview['skipped'], 2)
        self.assertEqual(preview['rows'][1]['elevator_id'], second)
        self.post('/api/elevators', dict(building_name='41栋', unit_name='1口', name='2号梯'))
        self.assertEqual(self.upload(raw=raw, token=preview['preview_token']).status_code, 409)
        self.assertEqual(len(self.client.get('/api/elevators').json()), 3)
        self.assertEqual(self.client.get('/api/events').json(), [])
        fresh = self.upload(raw=raw).json()
        report = self.upload(raw=raw, token=fresh['preview_token']).json()
        self.assertEqual(report['events_added'], 4)
        self.assertEqual(len(report['unmatched']), 2)
        event, = self.client.get('/api/events', params={'elevator_id': lift}).json()
        self.assertEqual(event['type'], '故障')
        self.assertEqual(event['fault_at'], '2025-01-05T08:35:00')
        self.assertEqual(event['ended_at'], '2025-01-05T09:40:00')
        self.assertTrue(event['uses_maintenance_fund'])
        self.assertEqual(event['parts'], [])
        stored = self.client.get(f'/api/elevators/{lift}').json()
        for key, value in old.items():
            self.assertEqual(stored[key], value)

    def restart(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        with TestClient(app) as client:
            self.assertFalse(client.get('/api/setup/status').json()['needed'])

    def test_first_launch_seeds_and_retries_when_elevator_table_is_empty(self):
        from backend.db import connect
        with isolated_app(seed=FIXTURE.resolve()) as (client, paths):
            report_path = paths['LOGS'] / 'seed-import-report.json'
            self.assertEqual(len(client.get('/api/elevators').json()), 9)
            self.assertEqual(len(client.get('/api/events').json()), 5)
            summary = json.loads(report_path.read_text(encoding='utf-8'))
            self.assertEqual((summary['added'], summary['events_added'], len(summary['unmatched'])), (9, 5, 1))
            self.assertIn('440201', summary['warnings'][0])
            self.assertNotIn('测C-', report_path.read_text(encoding='utf-8'))
            # Non-empty elevator table skips re-seeding.
            with patch('backend.main.read_records', side_effect=AssertionError('unexpected read when non-empty')) as reader:
                self.restart()
                reader.assert_not_called()
            with connect() as db:
                saved = db.execute("SELECT value FROM system_settings WHERE key='official_ledger_imported'").fetchone()[0]
                self.assertEqual(json.loads(saved), summary)
                # Simulate an empty elevator table even when a previous official_ledger_imported flag exists.
                db.execute('DELETE FROM event_parts')
                db.execute('DELETE FROM events')
                db.execute('DELETE FROM elevators')
            self.assertEqual(client.get('/api/elevators').json(), [])
            self.restart()
            self.assertEqual(len(client.get('/api/elevators').json()), 9)
            self.assertEqual(len(client.get('/api/events').json()), 5)

            # Also retry when official_ledger_imported holds a stale/failed payload and elevator table is empty.
            with connect() as db:
                db.execute('DELETE FROM event_parts')
                db.execute('DELETE FROM events')
                db.execute('DELETE FROM elevators')
                db.execute(
                    "UPDATE system_settings SET value=? WHERE key='official_ledger_imported'",
                    (json.dumps({'committed': False, 'added': 0}),),
                )
            self.restart()
            self.assertEqual(len(client.get('/api/elevators').json()), 9)
            self.assertTrue(json.loads(report_path.read_text(encoding='utf-8'))['committed'])

    def test_seed_status_does_not_warn_without_seed_and_reports_counts_or_redacted_failure_with_seed(self):
        from backend.db import connect
        from backend import main
        # 1) No seed file on empty DB -> normal empty workstation, no warning/error/message
        empty = self.client.get('/api/seed-status').json()
        self.assertEqual(empty['status'], 'empty')
        self.assertFalse(empty['seed_present'])
        self.assertFalse(empty['committed'])
        self.assertEqual((empty['elevator_count'], empty['event_count']), (0, 0))
        self.assertEqual(empty['error'], '')
        self.assertEqual(empty['message'], '')
        self.assertNotIn('预置台账尚未导入', json.dumps(empty, ensure_ascii=False))
        self.assertNotIn('未检测到随包预置台账', json.dumps(empty, ensure_ascii=False))
        self.assertEqual(self.client.get('/api/dashboard').json()['seed_status'], empty)

        # Even if a stale failed report file exists, no warning is emitted when no seed file is present.
        (self.paths['LOGS'] / 'seed-import-report.json').write_text(
            json.dumps({'committed': False, 'error': '旧报告'}), encoding='utf-8'
        )
        still_empty = self.client.get('/api/seed-status').json()
        self.assertEqual(still_empty['status'], 'empty')
        self.assertFalse(still_empty['seed_present'])
        self.assertEqual(still_empty['error'], '')
        self.assertEqual(still_empty['message'], '')
        (self.paths['LOGS'] / 'seed-import-report.json').unlink()

        # Verify Home and 电梯档案 UI source never nags on empty installations without a seed file.
        app_vue = (Path(__file__).resolve().parents[1] / 'frontend/src/App.vue').read_text(encoding='utf-8')
        self.assertNotIn('预置台账尚未导入', app_vue)
        self.assertNotIn('未检测到随包预置台账', app_vue)
        self.assertIn("seedStatus.value?.seed_present && (seedStatus.value.status === 'imported' || seedStatus.value.status === 'failed')", app_vue)
        self.assertEqual(app_vue.count('v-if="visibleSeedBanner"'), 2)

        # 2) Failed seed must set committed=False, not insert official_ledger_imported, and never leak 测C-
        seed = main.ROOT / 'seed/official-ledger.xlsx'
        seed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, seed)
        with connect() as db:
            db.execute("INSERT INTO system_settings(key,value) VALUES('official_ledger_imported','{\"committed\":true}')")
        with patch('backend.main.insert_event', side_effect=ValueError('1号电梯（测C-20001）与测C-10002校验中断')):
            self.restart()
        report_raw = (self.paths['LOGS'] / 'seed-import-report.json').read_text(encoding='utf-8')
        report_data = json.loads(report_raw)
        self.assertFalse(report_data['committed'])
        self.assertNotIn('测C-', report_raw)
        with connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM system_settings WHERE key='official_ledger_imported'").fetchone())
        failed = self.client.get('/api/seed-status').json()
        self.assertEqual(failed['status'], 'failed')
        self.assertTrue(failed['seed_present'])
        self.assertFalse(failed['committed'])
        self.assertIn('logs/seed-import-report.json', failed['message'])
        self.assertNotIn('测C-', json.dumps(failed, ensure_ascii=False))

        # 3) Next launch succeeds without deleting data dir and shows preloaded counts
        self.restart()
        imported = self.client.get('/api/seed-status').json()
        self.assertEqual(imported['status'], 'imported')
        self.assertTrue(imported['seed_present'])
        self.assertTrue(imported['committed'])
        self.assertEqual((imported['seed_elevators'], imported['seed_events']), (9, 5))
        self.assertEqual((imported['elevator_count'], imported['event_count']), (9, 5))
        self.assertIn('9 部电梯', imported['message'])
        self.assertIn('5 条工作记录', imported['message'])
        self.assertNotIn('测C-', json.dumps(imported, ensure_ascii=False))
        self.assertEqual(self.client.get('/api/dashboard').json()['seed_status'], imported)

    def test_late_seed_restart_retry_and_priority(self):
        report_path = self.paths['LOGS'] / 'seed-import-report.json'
        self.assertFalse(report_path.exists())
        from backend import main
        for base in (main.DATA, main.ROOT):
            seed = base / 'seed/official-ledger.xlsx'
            seed.parent.mkdir()
            shutil.copyfile(FIXTURE, seed)
        # A failure after elevator insertion rolls back the entire attempt.
        with patch('backend.main.insert_event', side_effect=ValueError('测试中断')):
            self.restart()
        self.assertFalse(json.loads(report_path.read_text(encoding='utf-8'))['committed'])
        self.assertEqual(self.client.get('/api/elevators').json(), [])
        with patch.object(Path, 'open', autospec=True, side_effect=Path.open) as opened:
            self.restart()
            paths = [args[0] for args, _ in opened.call_args_list]
            self.assertIn(main.ROOT / 'seed/official-ledger.xlsx', paths)
            self.assertNotIn(main.DATA / 'seed/official-ledger.xlsx', paths)
        self.assertEqual(len(self.client.get('/api/elevators').json()), 9)
        self.assertTrue(json.loads(report_path.read_text(encoding='utf-8'))['committed'])

    def test_data_dir_seed_and_nonempty_ledger_guard(self):
        target = self.paths['DATA'] / 'seed/official-ledger.xlsx'
        target.parent.mkdir()
        shutil.copyfile(FIXTURE, target)
        self.post('/api/elevators', dict(building_name='41栋', unit_name='1单元', name='1号电梯'))
        self.restart()
        self.assertFalse((self.paths['LOGS'] / 'seed-import-report.json').exists())
        with isolated_app() as (client, paths):
            target = paths['DATA'] / 'seed/official-ledger.xlsx'
            target.parent.mkdir()
            shutil.copyfile(FIXTURE, target)
            self.restart()
            self.assertEqual(json.loads((paths['LOGS'] / 'seed-import-report.json').read_text())['added'], 9)

    def test_absolute_configured_seed_takes_precedence(self):
        from backend import main
        fallback = main.ROOT / 'seed/official-ledger.xlsx'
        fallback.parent.mkdir()
        shutil.copyfile(FIXTURE, fallback)
        with patch.dict(os.environ, ELEVATOR_SEED_LEDGER=str(FIXTURE.resolve())), \
                patch.object(Path, 'open', autospec=True, side_effect=Path.open) as opened:
            self.restart()
            files = [args[0] for args, _ in opened.call_args_list]
            self.assertIn(FIXTURE.resolve(), files)
            self.assertNotIn(fallback, files)
        self.assertEqual(len(self.client.get('/api/elevators').json()), 9)
