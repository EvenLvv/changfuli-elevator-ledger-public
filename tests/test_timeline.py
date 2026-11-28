"""Operation history uses the time of entry, including for historical imports."""
import unittest
from pathlib import Path
from unittest.mock import patch

from support import isolated_app


class TimelineTest(unittest.TestCase):
    def setUp(self):
        context = isolated_app()
        self.client, _ = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        clock = patch('backend.db.now', return_value='2026-11-28T09:18:00+08:00')
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.lift = self.write('POST', '/elevators', dict(building_number='44', unit_number='2', elevator_number='1'))['id']

    def write(self, method, path, data=None, **kwargs):
        response = self.client.request(method, '/api' + path, json=data, **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def feed(self, **params):
        query = dict(start='2026-11-28', end='2026-11-28', month='2026-11-01')
        response = self.client.get('/api/timeline', params={**query, **params})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['total'], len(result['items']))
        return result

    def event(self, title):
        return self.write('POST', '/events', dict(elevator_id=self.lift, type='故障', title=title,
                          occurred_on='2024-03-01', completed=False))['id']

    def test_mutations_produce_distinct_filterable_snapshots(self):
        lift_url = f'/elevators/{self.lift}'
        self.write('PUT', lift_url, {**self.client.get('/api'+lift_url).json(), 'brand':'测试'})
        event_id = self.event('门锁故障')
        event_url = f'/events/{event_id}'
        self.write('PUT', event_url, dict(title='补充处理情况', type='故障', occurred_on='2024-03-01', completed=True))
        self.write('POST', event_url+'/attachments', files={'file': ('报告.pdf', b'%PDF-1.4\n%%EOF')})
        self.write('DELETE', event_url)
        work = self.feed(type='故障', elevator_id=self.lift)['items']
        self.assertEqual([x['kind'] for x in work], ['删除工作记录', '修改工作记录', '新增故障记录'])
        self.assertEqual([x['title'] for x in work], ['补充处理情况', '补充处理情况', '门锁故障'])
        self.assertEqual(work[-1]['tags'], ['故障', '待完成'])
        self.assertTrue(all(x['event_id'] is None for x in work))
        self.write('POST', f'/trash/events/{event_id}/restore')
        self.assertEqual(self.feed(type='恢复')['items'][0]['event_id'], event_id)
        self.assertEqual(self.feed(type='附件', elevator_id=self.lift)['items'][0]['event_id'], event_id)
        self.write('DELETE', lift_url)
        self.assertEqual([x['title'] for x in self.feed(type='电梯档案')['items']],
                         ['删除电梯','修改电梯','新增电梯'])
        self.assertIsNone(self.feed(type='故障')['items'][0]['event_id'])
        self.write('POST', f'/trash/elevators/{self.lift}/restore')
        self.write('PUT', '/network', dict(base_url='http://192.168.1.2:8765'))
        self.write('POST', '/backup')
        titles = [x['title'] for x in self.feed(type='系统操作')['items']]
        for title in ('系统备份', '修改局域网访问地址', '恢复电梯', '恢复工作记录', '新增附件'):
            self.assertIn(title, titles)
        self.assertEqual(self.feed(type='备份', elevator_id=self.lift)['total'], 0)

    def test_default_range_is_seven_shanghai_days(self):
        from datetime import datetime
        from backend.db import SHANGHAI
        for stamp in ('2026-11-21T15:59:59+00:00', '2026-11-21T16:00:00+00:00', '2026-11-28T09:00:00+08:00'):
            self.clock.return_value = stamp
            self.event(stamp)
        with patch('backend.main.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 28, tzinfo=SHANGHAI)
            result = self.client.get('/api/timeline', params={'type':'故障'}).json()
            clock.now.assert_called_once_with(SHANGHAI)
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['dates'], ['2026-11-21','2026-11-22','2026-11-28'])

    def test_frontend_all_period_is_default_and_returns_records_outside_last_seven_days(self):
        root = Path(__file__).resolve().parents[1]
        calendar_ts = (root / 'frontend/src/calendar.ts').read_text(encoding='utf-8')
        timeline_vue = (root / 'frontend/src/components/OperationTimeline.vue').read_text(encoding='utf-8')
        self.assertIn("export const presets = ['全部', '今天', '近7天', '本月', '本季度'] as const", calendar_ts)
        self.assertIn("if (period === '全部') return ['1900-01-01', '9999-12-31']", calendar_ts)
        self.assertIn("const period = ref<Period | '单日'>('全部')", timeline_vue)
        self.assertIn("const range = ref(periodRange('全部', current.value))", timeline_vue)

        stamps = ('2024-02-15T10:20:00+08:00', '2025-01-05T08:35:00+08:00', '2026-11-28T09:00:00+08:00')
        for stamp in stamps:
            self.clock.return_value = stamp
            self.event('记录-' + stamp[:10])
        seven_days = self.feed(start='2026-11-22', end='2026-11-28', type='故障')
        self.assertEqual([x['title'] for x in seven_days['items']], ['记录-2026-11-28'])
        all_history = self.feed(start='1900-01-01', end='9999-12-31', month='2026-11-01', type='故障')
        self.assertEqual(
            [x['title'] for x in all_history['items']],
            ['记录-2026-11-28', '记录-2025-01-05', '记录-2024-02-15'],
        )
        self.assertEqual(all_history['dates'], ['2026-11-28'])

    def test_shanghai_range_order_and_independent_calendar_month(self):
        times = ('2026-10-31T15:59:59.999999+00:00', '2026-10-31T16:00:00+00:00',
                 '2026-11-02T01:30:00+09:00', '2026-11-01T17:00:00+00:00')
        for n, stamp in enumerate(times):
            self.clock.return_value = stamp
            self.event(str(n))
        query = dict(start='2026-11-01', end='2026-11-02', type='故障')
        result = self.feed(**query)
        self.assertEqual([x['title'] for x in result['items']], ['3','2','1'])
        self.assertEqual(result['items'][-1]['timestamp'], '2026-11-01T00:00:00.000000+08:00')
        self.assertEqual(result['dates'], ['2026-11-01','2026-11-02'])
        prev = self.feed(**query, month='2026-10-01')
        self.assertEqual(prev['dates'], ['2026-10-31'])
        self.assertEqual(prev['items'], result['items'])
        self.assertEqual(self.feed(start='2026-11-01', end='2026-11-01', type='故障')['total'], 1)
        self.assertEqual(self.feed(**query, elevator_id=self.lift+1)['dates'], [])

    def test_legacy_work_without_audit_uses_creation_and_preserves_author(self):
        from backend.db import connect, init_db
        event_id = self.event('旧记录')
        with connect() as db:
            author = db.execute("SELECT id FROM users WHERE username=''").fetchone()[0]
            db.execute("UPDATE users SET username='former',display_name='原工作人员',active=1 WHERE id=?", (author,))
            db.execute("DELETE FROM audit_logs WHERE target='工作记录'")
            db.execute("UPDATE events SET created_by=?,created_at=? WHERE id=?",
                       (author, '2026-11-28T00:00:00', event_id))
        init_db()
        item, = self.feed(type='故障')['items']
        self.assertEqual((item['id'],item['event_id']), (-event_id,event_id))
        self.assertEqual(self.client.get(f'/api/events/{event_id}').json()['created_by'], author)
        self.write('PUT', f'/events/{event_id}', dict(type='维修',title='修复',occurred_on='2024-03-02'))
        with connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE username=''").fetchone()[0], 1)
        original, = self.feed(type='故障')['items']
        self.assertEqual(original['title'], '旧记录')
        items = self.feed(elevator_id=self.lift)['items']
        self.assertEqual(sum(x['event_id']==event_id for x in items), 2)

    def test_preview_is_silent_and_historical_import_appears_on_operation_day(self):
        fixture = Path(__file__).parent / 'fixtures/synthetic-ledger-fixture.xlsx'
        files = {'file': (fixture.name, fixture.read_bytes())}
        preview = self.write('POST', '/elevator-archives/import', files=files)
        self.assertEqual(self.feed(type='导入')['total'], 0)
        response = self.client.post('/api/elevator-archives/import?dry_run=false', files=files,
                                    data={'preview_token': preview['preview_token']})
        self.assertTrue(response.json()['committed'])
        imported, = self.feed(type='导入')['items']
        self.assertIn('5 条工作记录', imported['summary'])
        self.assertEqual(self.feed(type='配件更换')['total'], 5)
        self.assertEqual(self.feed(start='2025-01-01',end='2025-12-31',type='配件更换')['total'], 0)
