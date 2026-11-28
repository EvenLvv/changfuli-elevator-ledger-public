import io
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from docx import Document
from PIL import Image
from support import isolated_app


class AcceptanceAudit(unittest.TestCase):
    def setUp(self):
        self.context = isolated_app()
        self.client, self.paths = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.building = self.post('/api/buildings', {'name':'18栋'})['id']
        self.unit = self.post('/api/units', {'building_id':self.building,'name':'1单元'})['id']
        self.elevator = self.post('/api/elevators', {'unit_id':self.unit,'name':'1号梯'})['id']
        self.today = date.today().isoformat()

    def post(self, path, data):
        r=self.client.post(path,json=data)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def event(self, **values):
        data={'elevator_id':self.elevator,'title':'例行检查','type':'维修','occurred_on':self.today,'completed':True}
        data.update(values)
        return self.post('/api/events',data)['id']

    def test_cost_mode_survives_edit(self):
        part = {'name':'门锁','quantity':1,'unit_price_yuan':'260'}
        event = self.event(parts=[part])
        record = self.client.get(f'/api/events/{event}').json()
        self.assertEqual((record['cost_auto'], record['cost_cents']), (1, 26000))
        changed = {**record, 'cost_yuan':'', 'parts':[{**part, 'unit_price_yuan':'300'}]}
        self.assertEqual(self.client.put(f'/api/events/{event}',json=changed).status_code,200)
        record = self.client.get(f'/api/events/{event}').json()
        self.assertEqual((record['cost_auto'], record['cost_cents']), (1, 30000))
        self.assertEqual(self.client.put(f'/api/events/{event}',json={**record, 'cost_yuan':'0', 'parts':[part]}).status_code,200)
        record = self.client.get(f'/api/events/{event}').json()
        self.assertEqual((record['cost_auto'], record['cost_cents']), (0, 0))

    def test_replacement_fund_validates_and_stays_separate_from_legacy_costs(self):
        from backend.db import connect, init_db

        legacy = self.event(type='配件更换', cost_yuan='200', parts=[{'name':'旧门锁','unit_price_yuan':'200'}])
        with connect() as db:
            db.execute('ALTER TABLE events DROP COLUMN maintenance_fund_cents')
        init_db(); init_db()
        legacy_record = self.client.get(f'/api/events/{legacy}').json()
        self.assertIsNone(legacy_record['maintenance_fund_cents'])
        self.assertEqual(legacy_record['parts'][0]['unit_price_cents'], 20000)
        marked = self.event(type='故障', uses_maintenance_fund=True, maintenance_fund_yuan='')
        record = self.client.get(f'/api/events/{marked}').json()
        self.assertTrue(record['uses_maintenance_fund'])
        self.assertIsNone(record['maintenance_fund_cents'])
        self.assertIsNone(record['maintenance_fund_yuan'])

        parts = [{'name':'门锁','quantity':2}, {'name':'滚轮'}]
        payload = {'elevator_id':self.elevator, 'title':'更换门锁和滚轮', 'type':'维修',
                   'occurred_on':self.today, 'parts':parts}
        for changes in ({'uses_maintenance_fund':False, 'maintenance_fund_yuan':'10'},
                        {'uses_maintenance_fund':True, 'maintenance_fund_yuan':'0'},
                        {'uses_maintenance_fund':True, 'maintenance_fund_yuan':'-0.01'},
                        {'uses_maintenance_fund':True, 'maintenance_fund_yuan':'1.001'},
                        {'uses_maintenance_fund':True, 'maintenance_fund_yuan':'10', 'parts':[]}):
            with self.subTest(changes=changes):
                response = self.client.post('/api/events', json={**payload, **changes})
                self.assertEqual(response.status_code, 400, response.text)

        event = self.post('/api/events', {**payload, 'uses_maintenance_fund':True, 'maintenance_fund_yuan':'325.15'})['id']
        with connect() as db:
            db.execute('ALTER TABLE events DROP COLUMN uses_maintenance_fund')
        init_db()
        init_db()
        self.assertFalse(self.client.get(f'/api/events/{legacy}').json()['uses_maintenance_fund'])
        # Recreate the unpriced marker after simulating an upgrade from the amount-only schema.
        self.assertFalse(self.client.get(f'/api/events/{marked}').json()['uses_maintenance_fund'])
        self.assertEqual(self.client.put(f'/api/events/{marked}', json={**record, 'uses_maintenance_fund':True}).status_code, 200)
        endpoint = f'/api/events/{event}'
        self.assertEqual(self.client.put(endpoint, json=payload).status_code, 200)
        record = self.client.get(endpoint).json()
        self.assertTrue(record['uses_maintenance_fund'])
        self.assertEqual(record['maintenance_fund_cents'], 32515)
        self.assertEqual(record['cost_cents'], 0)
        total = self.client.get('/api/costs', params={'elevator_id':self.elevator}).json()
        self.assertEqual(total, {'cost_cents':20000, 'maintenance_fund_cents':32515, 'record_count':3})
        lift = self.client.get(f'/api/elevators/{self.elevator}').json()
        self.assertEqual(lift['total_cost_cents'], 20000)
        self.assertEqual(lift['total_maintenance_fund_cents'], 32515)

        filters = {'scope':'elevator', 'elevator_id':self.elevator}
        draft = self.post('/api/export-drafts', filters)
        draft_text = '\n'.join(block.get('text', '') for block in draft['blocks'])
        self.assertEqual(draft_text.count('住宅维修基金金额：325.15元'), 1)
        self.assertIn('历史登记费用：200.00元', draft_text)
        self.assertIn('已动用住宅维修资金，金额未登记', draft_text)
        raw = self.client.get('/api/export', params=filters)
        self.assertEqual(raw.status_code, 200)
        word_text = '\n'.join(p.text for p in Document(io.BytesIO(raw.content)).paragraphs)
        self.assertIn('本周期住宅维修基金金额合计：325.15元', word_text)
        self.assertIn('本周期一般登记费用合计：200.00元', word_text)
        self.assertIn('已动用住宅维修资金，金额未登记', word_text)

        self.assertEqual(self.client.put(endpoint, json={**payload, 'uses_maintenance_fund':False}).status_code, 200)
        cleared = self.client.get(endpoint).json()
        self.assertFalse(cleared['uses_maintenance_fund'])
        self.assertIsNone(cleared['maintenance_fund_cents'])
        self.assertEqual(self.client.get('/api/costs').json()['maintenance_fund_cents'], 0)

    def test_inline_elevator_location_and_edit(self):
        data = {'building_name':'20栋','unit_name':'2单元','name':'2号梯','equipment_number':'000021'}
        lift = self.post('/api/elevators',data)['id']
        self.assertEqual(self.client.get(f'/api/elevators/{lift}').json()['building_name'],'20栋')
        self.assertEqual(self.client.post('/api/elevators',json=data).status_code,409)
        current = self.client.get(f'/api/elevators/{lift}').json()
        self.assertEqual(self.client.put(f'/api/elevators/{lift}',json={**current,'building_name':'21栋'}).status_code,200)
        self.assertEqual(self.client.get(f'/api/elevators/{lift}').json()['building_name'],'21栋')
        self.assertEqual(self.client.post('/api/elevators',json={**data,'building_name':'','unit_name':'未建单元'}).status_code,400)

    def test_numbered_elevator_reuses_legacy_location_and_reserves_number_per_unit(self):
        numbered = {'building_number':'018','unit_number':'01','elevator_number':'1'}
        response = self.client.post('/api/elevators', json=numbered)
        self.assertEqual(response.status_code, 409, response.text)
        lift = self.post('/api/elevators', {**numbered, 'elevator_number':'2'})['id']
        record = self.client.get(f'/api/elevators/{lift}').json()
        self.assertEqual((record['building_id'], record['unit_id'], record['name']), (self.building, self.unit, '2号电梯'))
        self.post('/api/elevators', {**numbered, 'unit_number':'2'})
        self.post('/api/elevators', {**numbered, 'building_number':'2'})
        for field, value in (('building_number','18栋'), ('unit_number','2.5'), ('unit_number','0'), ('elevator_number','3')):
            self.assertEqual(self.client.post('/api/elevators', json={**numbered, field:value}).status_code, 400)
        match = self.client.get('/api/search', params={'q':'18栋1口1号电梯'}).json()
        self.assertEqual([item['id'] for item in match['elevators']], [self.elevator])

        path = f'/api/elevators/{self.elevator}'
        legacy = self.client.get(path).json()
        update = self.client.put(path, json={**legacy, **numbered, 'notes':'复核完成'})
        self.assertEqual(update.status_code, 200, update.text)
        latest = self.client.get(path).json()
        self.assertEqual((latest['unit_name'], latest['name'], latest['notes']), ('1单元','1号梯','复核完成'))
        self.assertEqual(self.client.put(path, json={**latest, **numbered, 'elevator_number':'2'}).status_code, 409)
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertEqual(self.client.post('/api/elevators', json=numbered).status_code, 409)

    def test_numbered_elevator_edit_keeps_existing_building_when_changing_unit(self):
        from backend.db import connect

        target_unit = self.post('/api/units', {'building_id': self.building, 'name': '2单元'})['id']
        with connect() as db:
            alias = db.execute('INSERT INTO buildings(name) VALUES(?)', ('018号楼',)).lastrowid
            db.execute('INSERT INTO units(building_id,name) VALUES(?,?)', (alias, '2口'))
            db.executemany('INSERT INTO buildings(name) VALUES(?)', [('20栋',), ('020号楼',)])

        path = f'/api/elevators/{self.elevator}'
        numbered = {'building_number': '018', 'unit_number': '2', 'elevator_number': '1'}
        record = self.client.get(path).json()
        response = self.client.put(path, json={**record, **numbered})
        self.assertEqual(response.status_code, 200, response.text)
        moved = self.client.get(path).json()
        self.assertEqual((moved['building_id'], moved['unit_id'], moved['name']), (self.building, target_unit, '1号梯'))

        audit = self.client.get('/api/audit').json()
        response = self.client.put(path, json={**moved, **numbered, 'building_number': '20'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('多条旧档案', response.json()['detail'])
        self.assertEqual(self.client.get(path).json(), moved)
        self.assertEqual(self.client.get('/api/audit').json(), audit)

    def test_numbered_elevator_edit_rejects_deleted_parent_without_changes(self):
        from backend.db import connect, now

        path = f'/api/elevators/{self.elevator}'
        numbered = {'building_number': '18', 'elevator_number': '1'}
        for table, record_id, name, unit_number in (
            ('buildings', self.building, '18栋', '1'),
            ('buildings', self.building, '18栋', '2'),
            ('units', self.unit, '1单元', '1'),
        ):
            with self.subTest(table=table, unit_number=unit_number):
                record = self.client.get(path).json()
                audit = self.client.get('/api/audit').json()
                with connect() as db:
                    db.execute(f'UPDATE {table} SET deleted_at=? WHERE id=?', (now(), record_id))
                response = self.client.put(path, json={**record, **numbered, 'unit_number': unit_number, 'notes': '应拒绝保存'})
                with connect() as db:
                    db.execute(f'UPDATE {table} SET deleted_at=NULL WHERE id=?', (record_id,))
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()['detail'], f'{name}已删除，请先在系统设置中恢复')
                self.assertEqual(self.client.get(path).json(), record)
                self.assertEqual(self.client.get('/api/audit').json(), audit)

    def test_numbered_location_rejects_ambiguity_and_excel_preserves_legacy_aliases(self):
        from backend.archive_excel import workbook_bytes
        from backend.db import connect

        self.assertEqual(self.client.post('/api/buildings', json={'name':'018号楼'}).status_code, 409)
        self.assertEqual(self.client.post('/api/units', json={'building_id':self.building,'name':'1口'}).status_code, 409)
        other_building = self.post('/api/buildings', {'name':'东楼'})['id']
        self.assertEqual(self.client.put(f'/api/buildings/{other_building}', json={'name':'18'}).status_code, 409)
        other_unit = self.post('/api/units', {'building_id':self.building,'name':'东侧'})['id']
        self.assertEqual(self.client.put(f'/api/units/{other_unit}', json={'name':'01单元口'}).status_code, 409)

        with connect() as db:
            db.execute('INSERT INTO units(building_id,name) VALUES(?,?)', (self.building, '1口'))
        response = self.client.post('/api/elevators', json={'building_number':'18','unit_number':'1','elevator_number':'2'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('多条旧档案', response.json()['detail'])

        def upload(records):
            return self.client.post('/api/elevator-archives/import?dry_run=false',
                files={'file':('档案.xlsx', workbook_bytes(records))}).json()

        old = {'building_name':'18栋','unit_name':'1单元','name':'1号梯'}
        self.assertEqual(upload([{**old, 'building_name':'18', 'name':'1号电梯'}])['skipped'], 1)
        same_unit = {**old, 'unit_name':'2口', 'name':'2号电梯'}
        self.assertFalse(upload([same_unit, {**same_unit, 'unit_name':'02单元', 'name':'2号梯'}])['valid'])
        self.assertEqual(len(self.client.get('/api/units').json()), 3)
        exported = self.client.get('/api/elevator-archives/export')
        replay = self.client.post('/api/elevator-archives/import?dry_run=false',
            files={'file':('档案.xlsx', exported.content)}).json()
        self.assertEqual((replay['added'], replay['skipped']), (0, 1))

    def test_excel_rejects_distinct_parent_names_that_resolve_to_one_location(self):
        from backend.archive_excel import workbook_bytes

        endpoints = ('/api/buildings', '/api/units', '/api/elevators', '/api/audit')
        original = [self.client.get(path).json() for path in endpoints]
        for building, field, alias, unit in (
            ('44栋', 'building_name', '044号楼', '2口'),
            ('45栋', 'unit_name', '1口', '1口'),
        ):
            first = {'building_name': building, 'unit_name': '1单元', 'name': '1号梯'}
            second = {**first, 'unit_name': unit, field: alias, 'name': '2号梯'}
            workbook = workbook_bytes([first, second])
            for dry_run in (True, False):
                with self.subTest(field=field, dry_run=dry_run):
                    response = self.client.post('/api/elevator-archives/import', params={'dry_run': dry_run},
                        files={'file': ('档案.xlsx', workbook)})
                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()
                    self.assertFalse(result['valid'], result)
                    self.assertEqual((result['added'], result['skipped']), (0, 0))
                    self.assertIn('第3行', result['errors'][0])
                    self.assertIn(first[field], result['errors'][0])
                    self.assertIn(alias, result['errors'][0])
                    self.assertEqual([self.client.get(path).json() for path in endpoints], original)

    def test_excel_keeps_exact_legacy_parents_distinct(self):
        from backend.archive_excel import workbook_bytes
        from backend.db import connect

        with connect() as db:
            other_unit = db.execute('INSERT INTO units(building_id,name) VALUES(?,?)', (self.building, '1口')).lastrowid
            other_building = db.execute('INSERT INTO buildings(name) VALUES(?)', ('018号楼',)).lastrowid
            other_building_unit = db.execute('INSERT INTO units(building_id,name) VALUES(?,?)', (other_building, '1单元')).lastrowid

        records = [
            {'building_name': '18栋', 'unit_name': '1单元', 'name': '2号梯'},
            {'building_name': '18栋', 'unit_name': '1口', 'name': '2号梯'},
            {'building_name': '018号楼', 'unit_name': '1单元', 'name': '2号梯'},
        ]
        workbook = workbook_bytes(records)
        response = self.client.post('/api/elevator-archives/import', params={'dry_run': False},
            files={'file': ('档案.xlsx', workbook)})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['added'], 3, response.text)
        self.assertEqual([row['place'] for row in result['rows']], [
            '18栋 / 1单元 / 2号梯',
            '18栋 / 1口 / 2号梯',
            '018号楼 / 1单元 / 2号梯',
        ])
        lifts = self.client.get('/api/elevators').json()
        self.assertCountEqual([lift['unit_id'] for lift in lifts if lift['name'] == '2号梯'],
            [self.unit, other_unit, other_building_unit])

    def test_excel_preview_shows_where_legacy_aliases_will_resolve(self):
        from backend.archive_excel import workbook_bytes

        rows = [{'building_name': '018号楼', 'unit_name': '01单元', 'name': name}
                for name in ('2号梯', '01号电梯')]
        files = {'file': ('档案.xlsx', workbook_bytes(rows))}
        expected = [
            {'row': 2, 'action': '新增', 'place': '表格：018号楼 / 01单元 / 2号梯 → 实际：18栋 / 1单元 / 2号梯'},
            {'row': 3, 'action': '跳过', 'place': '表格：018号楼 / 01单元 / 01号电梯 → 实际：18栋 / 1单元 / 1号梯'},
        ]
        preview = self.client.post('/api/elevator-archives/import', files=files)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()['rows'], expected)
        self.assertEqual([item['id'] for item in self.client.get('/api/elevators').json()], [self.elevator])

        commit = self.client.post('/api/elevator-archives/import?dry_run=false', files=files)
        self.assertEqual(commit.status_code, 200, commit.text)
        self.assertEqual(commit.json()['rows'], expected)
        elevators = self.client.get('/api/elevators').json()
        self.assertCountEqual([(item['name'], item['building_id'], item['unit_id']) for item in elevators],
                              [('1号梯', self.building, self.unit), ('2号梯', self.building, self.unit)])

    def test_excel_preview_preserves_location_field_boundaries(self):
        from backend.archive_excel import workbook_bytes

        records = [
            {'building_name': '东区', 'unit_name': '北楼', 'name': '客梯'},
            {'building_name': '东', 'unit_name': '区北楼', 'name': '客梯'},
        ]
        response = self.client.post('/api/elevator-archives/import',
            files={'file': ('档案.xlsx', workbook_bytes(records))})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result['valid'], result)
        self.assertEqual([row['place'] for row in result['rows']], ['东区 / 北楼 / 客梯', '东 / 区北楼 / 客梯'])
        self.assertEqual([lift['id'] for lift in self.client.get('/api/elevators').json()], [self.elevator])

    def test_excel_confirmation_rejects_changed_preview_targets(self):
        from backend.archive_excel import workbook_bytes

        files = {'file': ('档案.xlsx', workbook_bytes([
            {'building_name': '新建位置', 'unit_name': '1口', 'name': '1号梯'},
            {'building_name': '18', 'unit_name': '1单元', 'name': '2号梯'},
        ]))}
        path = '/api/elevator-archives/import'
        preview = self.client.post(path, files=files).json()
        self.assertIn('实际：18栋 / 1单元 / 2号梯', preview['rows'][1]['place'])
        self.assertEqual(self.client.put(f'/api/buildings/{self.building}', json={'name': '19栋'}).status_code, 200)
        replacement = self.post('/api/buildings', {'name': '018号楼'})['id']
        endpoints = ('/api/buildings', '/api/units', '/api/elevators', '/api/audit')
        original = [self.client.get(url).json() for url in endpoints]

        for token in ('', preview['preview_token']):
            with self.subTest(token=token):
                commit = self.client.post(path, params={'dry_run': False}, files=files, data={'preview_token': token})
                self.assertEqual(commit.status_code, 409, commit.text)
                self.assertIn('重新检查表格', commit.json()['detail'])
                self.assertEqual([self.client.get(url).json() for url in endpoints], original)

        unit = self.post('/api/units', {'building_id': replacement, 'name': '1单元'})['id']
        fresh = self.client.post(path, files=files).json()
        self.assertIn('实际：018号楼 / 1单元 / 2号梯', fresh['rows'][1]['place'])
        self.post('/api/elevators', {'unit_id': unit, 'name': '2号梯'})
        commit = self.client.post(path, params={'dry_run': False}, files=files,
                                  data={'preview_token': fresh['preview_token']})
        self.assertEqual(commit.status_code, 409, commit.text)
        self.assertNotIn('新建位置', {row['name'] for row in self.client.get('/api/buildings').json()})

        fresh = self.client.post(path, files=files).json()
        self.post('/api/buildings', {'name': '无关的新楼栋'})
        commit = self.client.post(path, params={'dry_run': False}, files=files,
                                  data={'preview_token': fresh['preview_token']})
        self.assertEqual(commit.status_code, 200, commit.text)
        self.assertTrue(commit.json()['committed'])
        self.assertEqual((commit.json()['added'], commit.json()['skipped']), (1, 1))
        self.assertIn(replacement, {row['building_id'] for row in self.client.get('/api/elevators').json()})

    def test_excel_reimport_uses_indexes_for_exact_names(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        from backend.db import connect

        workbook = self.client.get('/api/elevator-archives/export').content
        statements = []

        @contextmanager
        def traced_connect():
            with connect() as db:
                db.set_trace_callback(statements.append)
                yield db

        with patch('backend.main.connect', traced_connect):
            response = self.client.post('/api/elevator-archives/import', files={'file': ('档案.xlsx', workbook)})
        self.assertEqual(response.json()['skipped'], 1)
        lookups = [sql for sql in statements if sql.startswith('SELECT id,name,deleted_at FROM ')]
        self.assertCountEqual([sql.split()[3] for sql in lookups], ['buildings', 'units', 'elevators'])
        with connect() as db:
            for sql in lookups:
                plan = db.execute('EXPLAIN QUERY PLAN ' + sql).fetchone()['detail']
                self.assertRegex(plan, r'USING INDEX sqlite_autoindex_\w+ \([^)]*name=\?\)', plan)

    def test_excel_preview_commit_repeat_and_export(self):
        from backend.archive_excel import workbook_bytes
        from openpyxl import load_workbook
        raw = workbook_bytes([{'building_name':'新楼栋','unit_name':'1单元','name':'1号梯','maintenance_phone':'00123','equipment_number':'000042','notes':'=SUM(1,2)'}])
        def upload(preview):
            return self.client.post('/api/elevator-archives/import',params={'dry_run':preview},files={'file':('电梯.xlsx',raw)}).json()
        self.assertEqual(upload(True)['added'],1)
        self.assertFalse(any(b['name']=='新楼栋' for b in self.client.get('/api/buildings').json()))
        self.assertEqual(upload(False)['added'],1)
        self.assertEqual(upload(False)['skipped'],1)
        records = self.client.get('/api/elevators').json()
        lift = next(e for e in records if e['building_name']=='新楼栋')
        exported = self.client.get('/api/elevator-archives/export',params={'building_id':lift['building_id']})
        workbook=load_workbook(io.BytesIO(exported.content))
        self.assertEqual(workbook['电梯档案']['E2'].value,'000042')
        self.assertEqual(workbook['电梯档案']['L2'].value,'00123')
        self.assertEqual(workbook['电梯档案']['P2'].data_type,'s')
        self.assertEqual(workbook['电梯档案'].max_row,2)
        workbook.close()

    def test_excel_invalid_batch_is_atomic(self):
        from backend.archive_excel import workbook_bytes
        base={'building_name':'不能留下的楼栋','unit_name':'1单元','name':'1号梯'}
        invalid = {**base, 'name': '2号梯', 'inspection_on': '2026-02-30'}
        for records in ([base, invalid], [invalid, base], [base, base]):
            result=self.client.post('/api/elevator-archives/import?dry_run=false',files={'file':('批量.xlsx',workbook_bytes(records))})
            self.assertEqual(result.status_code,200,result.text)
            self.assertFalse(result.json()['valid'])
            self.assertFalse(any(b['name']=='不能留下的楼栋' for b in self.client.get('/api/buildings').json()))

    def test_excel_template_and_invalid_files(self):
        from openpyxl import load_workbook
        result=self.client.get('/api/elevator-archives/export?template=true')
        book=load_workbook(io.BytesIO(result.content))
        self.assertEqual(book['电梯档案']['L2'].number_format,'@')
        book['电梯档案']['A2']='18栋';book['电梯档案']['B2']='1单元';book['电梯档案']['C2']='=1+1'
        raw=io.BytesIO();book.save(raw);book.close()
        response=self.client.post('/api/elevator-archives/import',files={'file':('公式.xlsx',raw.getvalue())})
        self.assertEqual(response.status_code,400)
        self.assertIn('公式',response.json()['detail'])
        self.assertEqual(self.client.post('/api/elevator-archives/import',files={'file':('坏.xlsx',b'bad')}).status_code,400)
        self.assertEqual(self.client.get('/api/elevator-archives/export').status_code,200)

    def test_webp_export_and_original_bytes(self):
        event=self.event()
        photo=io.BytesIO();Image.new('RGB',(500,250),'blue').save(photo,format='WEBP')
        r=self.client.post(f'/api/events/{event}/attachments',files={'file':('现场.webp',photo.getvalue(),'image/webp')})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/attachments/'+r.json()['id']).content,photo.getvalue())
        r=self.client.get('/api/export',params={'scope':'elevator','elevator_id':self.elevator})
        self.assertEqual(r.status_code,200,r.text if r.status_code!=200 else '')
        self.assertEqual(len(Document(io.BytesIO(r.content)).inline_shapes),1)

    def test_state_follows_edit_and_not_backfill(self):
        recent=self.event(type='故障',title='当前故障',completed=False,recovered=False,elevator_status='故障')
        self.event(occurred_on='2020-01-01',title='旧维修')
        self.assertEqual(self.client.get(f'/api/elevators/{self.elevator}').json()['status'],'故障')
        r=self.client.put(f'/api/events/{recent}',json={'type':'故障','title':'当前故障','occurred_on':self.today,'completed':True,'recovered':True,'elevator_status':'正常'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get(f'/api/elevators/{self.elevator}').json()['status'],'正常')

    def test_search_all_keywords_same_record_and_company(self):
        self.event(title='门锁修复',company='精准维保有限公司')
        self.event(title='电机检查')
        self.assertFalse(self.client.get('/api/search',params={'q':'门锁 电机'}).json()['events'])
        results=self.client.get('/api/search',params={'q':'18栋 精准维保'}).json()['events']
        self.assertEqual(len(results),1)

    def test_search_calculates_location_once_per_elevator(self):
        from unittest.mock import patch
        from backend import location
        from backend.db import connect

        event = self.event(title='门锁维修')
        with connect() as db:
            db.executemany('''INSERT INTO events(elevator_id,type,title,occurred_on,created_by,created_at,updated_at)
                SELECT elevator_id,type,title,occurred_on,created_by,created_at,updated_at FROM events WHERE id=?''',
                [(event,)] * 124)

        with patch.object(location, 'archive_number', wraps=location.archive_number) as parse:
            response = self.client.get('/api/search', params={'q': '18栋1口1号电梯 门锁'})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual([row['id'] for row in result['elevators']], [self.elevator])
        self.assertEqual(len(result['events']), 100)
        self.assertTrue(result['truncated'])
        self.assertEqual(parse.call_count, 3)

    def test_search_and_overview_disambiguate_old_locations_without_a_full_ledger(self):
        from backend.db import connect

        with connect() as db:
            duplicate = db.execute('''INSERT INTO elevators(id,unit_id,name,maintenance_due_on,maintenance_company)
                VALUES(?,?,?,?,?)''', (42, self.unit, '01号电梯', self.today, '门锁服务公司')).lastrowid
            other = db.execute('INSERT INTO elevators(id,unit_id,name) VALUES(?,?,?)',
                               (142, self.unit, '001号电梯')).lastrowid
        self.event(elevator_id=other)
        other_work = self.event(elevator_id=duplicate, title='电机巡查')
        event_id = self.event(elevator_id=duplicate, title='更换门锁')
        label = f'18栋1口1号电梯（档案 {duplicate} · 18栋 / 1单元 / 01号电梯）'
        for query, events in ((label, [event_id, other_work]), ('档案 42', [event_id, other_work]),
                              ('档案 42 · 18栋1口1号电梯', [event_id, other_work]),
                              ('档案 42 · 18栋1口1号电梯 门锁', [event_id])):
            with self.subTest(query=query):
                results = self.client.get('/api/search', params={'q': query}).json()
                self.assertEqual([(item['id'], item['location_label']) for item in results['elevators']], [(duplicate, label)])
                self.assertEqual([(item['id'], item['location_label']) for item in results['events']], [(i, label) for i in events])
        dashboard = self.client.get('/api/dashboard').json()
        self.assertEqual(dashboard['recent'][0]['location_label'], label)
        self.assertEqual(self.client.get('/api/reminders').json()[0]['location_label'], label)
        ordinary = self.client.get('/api/search', params={'q': '门锁服务公司'}).json()
        self.assertEqual([item['id'] for item in ordinary['events']], [event_id, other_work])

    def test_search_saved_word_label_after_renaming_building(self):
        from backend.db import connect

        with connect() as db:
            db.execute('INSERT INTO elevators(unit_id,name) VALUES(?,?)', (self.unit, '01号梯'))
        event = self.event(title='更换门锁')
        self.event(title='电机巡查')
        exported = self.client.get('/api/export', params={'scope': 'elevator', 'elevator_id': self.elevator})
        self.assertEqual(exported.status_code, 200)
        old_label = next(p.text.removeprefix('电梯：') for p in Document(io.BytesIO(exported.content)).paragraphs
                         if p.text.startswith('电梯：档案 '))
        self.assertEqual(old_label, f'档案 {self.elevator} · 18栋1口1号电梯')
        self.assertEqual(self.client.put(f'/api/buildings/{self.building}', json={'name': '19栋'}).status_code, 200)
        results = self.client.get('/api/search', params={'q': old_label + ' 门锁'}).json()
        self.assertEqual([item['id'] for item in results['elevators']], [self.elevator])
        self.assertEqual([item['id'] for item in results['events']], [event])

    def test_validation_is_chinese_client_error(self):
        for value in ['Infinity','sNaN','NaN','-1','12.345']:
            r=self.client.post('/api/events',json={'elevator_id':self.elevator,'title':'非法费用','type':'维修','occurred_on':self.today,'cost_yuan':value})
            self.assertEqual(r.status_code,400,(value,r.text))
        r=self.client.post('/api/events',json={'elevator_id':self.elevator,'title':'日期越界','type':'配件更换','occurred_on':self.today,'parts':[{'name':'门锁','replaced_on':'9999-12-31','warranty_days':365}]})
        self.assertEqual(r.status_code,400,r.text)
        self.assertEqual(self.client.get('/api/events?elevator_id=abc').status_code,400)

    def test_deleted_elevator_records_hidden(self):
        event=self.event()
        self.assertEqual(self.client.delete(f'/api/elevators/{self.elevator}').status_code,200)
        self.assertEqual(self.client.get(f'/api/events/{event}').status_code,404)
        self.assertEqual(self.client.get('/api/dashboard').json()['stats']['monthly_repairs'],0)

    def test_export_contains_fault_times_and_completion(self):
        self.event(type='故障',title='3层故障',reported_at=self.today+'T09:12',arrived_at=self.today+'T09:30',restored_at=self.today+'T10:36',recovered=True,completed=True)
        r=self.client.get('/api/export',params={'scope':'elevator','elevator_id':self.elevator})
        self.assertEqual(r.status_code,200)
        text='\n'.join(p.text for p in Document(io.BytesIO(r.content)).paragraphs)
        for value in ('09:12','09:30','10:36','已完成','已恢复正常'):
            self.assertIn(value,text)

    def test_demo_can_be_recreated(self):
        from scripts.demo_data import install_demo,remove_demo
        install_demo();remove_demo();install_demo()
        self.assertTrue(any(x['name'].startswith('演示18栋') for x in self.client.get('/api/buildings').json()))

    def test_backup_can_restore_database_and_files(self):
        event=self.event()
        image=io.BytesIO();Image.new('RGB',(20,20),'red').save(image,format='PNG')
        attachment=self.client.post(f'/api/events/{event}/attachments',files={'file':('原图.png',image.getvalue(),'image/png')}).json()
        result=self.post('/api/backup',{})
        archive=self.client.get(result['download']).content
        import sqlite3
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertIsNone(z.testzip())
            restored=self.paths['DATA']/'restored.db';restored.write_bytes(z.read('data/elevator.db'))
            with sqlite3.connect(restored) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                row=db.execute('SELECT relative_path FROM attachments WHERE id=?',(attachment['id'],)).fetchone()
                self.assertEqual(z.read('storage/'+row[0]),image.getvalue())
                self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)

    def test_edit_conflict_and_boolean_values(self):
        event=self.event(completed=True)
        first=self.client.get(f'/api/events/{event}').json()
        self.assertIs(first['completed'],True)
        changed={**first,'title':'新修改','cost_yuan':'0'}
        self.assertEqual(self.client.put(f'/api/events/{event}',json=changed).status_code,200)
        self.assertEqual(self.client.put(f'/api/events/{event}',json={**first,'title':'过期修改'}).status_code,409)
        self.assertEqual(self.client.get(f'/api/events/{event}').json()['title'],'新修改')

    def test_restore_and_shared_attachments(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        event=self.event()
        raw=io.BytesIO();Image.new('RGB',(20,10),'green').save(raw,format='PNG')
        photo=self.client.post(f'/api/events/{event}/attachments',files={'file':('现场.png',raw.getvalue(),'image/png')}).json()['id']
        other=TestClient(app)
        self.assertEqual(other.post(f'/api/events/{event}/attachments',files={'file':('现场.png',raw.getvalue(),'image/png')}).status_code,200)
        self.assertEqual(other.get('/api/trash').status_code,200)
        self.assertEqual(self.client.delete(f'/api/events/{event}').status_code,200)
        self.assertEqual(self.client.get('/api/attachments/'+photo).status_code,404)
        self.assertEqual(self.client.post(f'/api/trash/events/{event}/restore').status_code,200)
        self.assertEqual(self.client.get('/api/attachments/'+photo).content,raw.getvalue())

    def test_missing_attachment_blocks_backup_and_export(self):
        event=self.event()
        raw=io.BytesIO();Image.new('RGB',(20,10),'green').save(raw,format='PNG')
        self.client.post(f'/api/events/{event}/attachments',files={'file':('现场.png',raw.getvalue(),'image/png')})
        next((self.paths['STORAGE']/'photos').glob('*')).unlink()
        self.assertEqual(self.client.post('/api/backup',json={}).status_code,400)
        self.assertEqual(self.client.get('/api/export',params={'scope':'all'}).status_code,400)
        self.assertFalse(list(self.paths['BACKUPS'].glob('*')))

    def test_photo_orientation_in_word(self):
        event=self.event()
        raw=io.BytesIO();photo=Image.new('RGB',(100,200),'blue');exif=photo.getexif();exif[274]=6;photo.save(raw,format='JPEG',exif=exif)
        item=self.client.post(f'/api/events/{event}/attachments',files={'file':('转向.jpg',raw.getvalue(),'image/jpeg')}).json()
        self.assertEqual(self.client.get('/api/attachments/'+item['id']).content,raw.getvalue())
        r=self.client.get('/api/export',params={'scope':'all'})
        image=Document(io.BytesIO(r.content)).inline_shapes[0]
        self.assertAlmostEqual(image.width/image.height,2.0,places=2)

    def test_date_and_type_filters_and_costs(self):
        self.event(type='日常维保',occurred_on='2026-01-01',cost_yuan='10')
        self.event(type='维修',occurred_on='2026-01-02',cost_yuan='20')
        self.event(type='维修',occurred_on='2026-01-03',cost_yuan='30')
        params={'start':'2026-01-01','end':'2026-01-02','type':'维修'}
        self.assertEqual(len(self.client.get('/api/events',params=params).json()),1)
        self.assertEqual(self.client.get('/api/costs',params=params).json()['cost_cents'],2000)
        for scope in ({'scope':'all'},{'scope':'unit','unit_id':self.unit}):
            r=self.client.get('/api/export',params={**scope,**params})
            document=Document(io.BytesIO(r.content))
            self.assertIn('1 条工作记录','\n'.join(p.text for p in document.paragraphs))
        self.assertEqual(self.client.get('/api/costs',params={'start':'2026-01-03','end':'2026-01-01'}).status_code,400)

    def test_request_validation_and_csrf(self):
        payload={'elevator_id':self.elevator,'title':'测试','type':'维修','occurred_on':self.today}
        for changes in ({'parts':[None]},{'type':[]},{'completed':'false'},{'cost_yuan':'Infinity'},{'title':{}},{'work_content':'bad\u0000text'},
                        {'started_at':self.today+'T10:00','ended_at':self.today+'T09:00'}):
            r=self.client.post('/api/events',json={**payload,**changes})
            self.assertEqual(r.status_code,400,r.text)
        r=self.client.post('/api/events',json=payload,headers={'origin':'http://evil.example'})
        self.assertEqual(r.status_code,403)
        self.assertEqual(self.client.get('/api/attachments/%2E%2E%2Frequirements.txt').status_code,404)
        self.assertEqual(self.client.get('/api/search',params={'q':"' OR 1=1 --"}).json()['events'],[])

    def test_demo_removal_protects_new_elevator(self):
        from scripts.demo_data import install_demo,remove_demo
        install_demo()
        units=self.client.get('/api/units').json()
        demo=next(x for x in units if x['building_name'].startswith('演示'))
        self.post('/api/elevators',{'unit_id':demo['id'],'name':'后来登记的电梯'})
        with self.assertRaises(SystemExit):
            remove_demo()
        self.assertTrue(any(x['name']=='后来登记的电梯' for x in self.client.get('/api/elevators').json()))

    def test_restart_from_restored_backup(self):
        import os, subprocess, sys, json
        event=self.event(title='重启后应保留的记录')
        backup=self.post('/api/backup',{})
        restored=self.paths['DATA'].parent/'restored'
        with zipfile.ZipFile(io.BytesIO(self.client.get(backup['download']).content)) as archive:
            archive.extractall(restored)
        environment=os.environ.copy()
        for key,folder in [('DATA','data'),('STORAGE','storage'),('EXPORT','exports'),('BACKUP','backups'),('LOG','logs')]:
            environment[f'ELEVATOR_{key}_DIR']=str(restored/folder)
        code="""from backend.main import app
from fastapi.testclient import TestClient
with TestClient(app) as c:
 assert not c.cookies
 records=c.get('/api/events').json()
 assert len(records)==1,records
 assert records[0]['title']=='重启后应保留的记录',records
 print('restored records available on restart')
"""
        result=subprocess.run([sys.executable,'-c',code],env=environment,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':
    unittest.main()
