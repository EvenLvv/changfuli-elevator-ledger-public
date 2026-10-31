"""Regression coverage for PR #1, using only isolated synthetic records."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from support import isolated_app


class ReviewFixesTest(unittest.TestCase):
    def setUp(self):
        self.context = isolated_app()
        self.client, self.paths = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.post('/api/setup', {'username': 'test-admin-a', 'display_name': '测试管理员甲',
                                 'password': 'synthetic-password-123'})
        self.post('/api/login', {'username': 'test-admin-a', 'password': 'synthetic-password-123'})
        self.actor = self.client.get('/api/me').json()

    def post(self, path, data):
        response = self.client.post(path, json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def lift(self):
        return self.post('/api/elevators', {'building_name': '测试楼栋', 'unit_name': '测试单元',
                                           'name': '测试梯'})['id']

    def event(self, lift, **extra):
        return self.post('/api/events', {'elevator_id': lift, 'type': '故障', 'title': '合成测试记录',
                                         'occurred_on': '2026-01-01', **extra})['id']

    def race(self, *operations):
        """Start real SQLite writers together, retaining already-authenticated actors.

        Trace the transactions as well as the outcome, so a lucky serial schedule
        cannot hide a regression that reads business data before acquiring a lock.
        """
        from backend import db, main
        barrier = threading.Barrier(len(operations))
        traces = []

        @contextmanager
        def traced_connect():
            with db.connect() as connection:
                statements = []
                traces.append(statements)
                connection.set_trace_callback(statements.append)
                yield connection

        def run(operation):
            barrier.wait(timeout=5)
            try:
                return 200, operation()
            except HTTPException as exc:
                return exc.status_code, exc.detail

        with patch.object(main, 'connect', traced_connect), ThreadPoolExecutor(len(operations)) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(len(traces), len(operations))
        for statements in traces:
            self.assertEqual(statements[0].upper(), 'BEGIN IMMEDIATE', statements)
        return results

    def check_mutual_admin_changes(self, change):
        from backend import db, main
        other_id = self.post('/api/users', {'username': 'test-admin-b', 'display_name': '测试管理员乙',
                                           'password': 'synthetic-password-456', 'role': 'admin'})['id']
        other = {'id': other_id, 'role': 'admin'}
        results = self.race(lambda: main.edit_user(other_id, change, self.actor),
                            lambda: main.edit_user(self.actor['id'], change, other))
        self.assertEqual(sorted(status for status, _ in results), [200, 403], results)
        with db.connect() as connection:
            admins = connection.execute("SELECT id FROM users WHERE role='admin' AND active=1").fetchall()
            self.assertEqual(len(admins), 1)
            loser = other if admins[0]['id'] == self.actor['id'] else self.actor
        # A request authenticated before revocation must also fail in sequence.
        with self.assertRaises(HTTPException) as raised:
            main.edit_user(admins[0]['id'], change, loser)
        self.assertEqual(raised.exception.status_code, 403)

    def test_admins_cannot_disable_each_other_concurrently(self):
        self.check_mutual_admin_changes({'active': False})

    def test_admins_cannot_demote_each_other_concurrently(self):
        self.check_mutual_admin_changes({'role': 'staff'})

    def test_building_delete_races_unit_creation(self):
        from backend import main
        building = self.post('/api/buildings', {'name': '测试空楼栋'})['id']
        results = self.race(lambda: main.delete_building(building, self.actor),
                            lambda: main.add_unit({'building_id': building, 'name': '测试单元'}, self.actor))
        self.assertEqual(sorted(status for status, _ in results), [200, 400], results)
        if results[1][0] == 200:
            self.assertIn(results[1][1]['id'], [row['id'] for row in self.client.get('/api/units').json()])
            self.assertEqual(self.client.delete(f'/api/buildings/{building}').status_code, 400)
        else:
            self.assertEqual(self.client.post('/api/units', json={'building_id': building, 'name': '另一个单元'}).status_code, 400)

    def test_unit_delete_races_elevator_creation(self):
        from backend import main
        for inline in (False, True):
            with self.subTest(inline=inline):
                name = f'测试楼栋{inline}'
                building = self.post('/api/buildings', {'name': name})['id']
                unit = self.post('/api/units', {'building_id': building, 'name': '测试单元'})['id']
                data = {'name': '测试梯', **({'building_name': name, 'unit_name': '测试单元'} if inline else {'unit_id': unit})}
                results = self.race(lambda: main.delete_unit(unit, self.actor),
                                    lambda: main.add_elevator(data, self.actor))
                self.assertEqual(sum(status == 200 for status, _ in results), 1, results)
                self.assertIn(next(status for status, _ in results if status != 200), (400, 409))
                if results[1][0] == 200:
                    self.assertIn(results[1][1]['id'], [row['id'] for row in self.client.get('/api/elevators').json()])
                    self.assertEqual(self.client.delete(f'/api/units/{unit}').status_code, 400)
                else:
                    self.assertIn(self.client.post('/api/elevators', json=data).status_code, (400, 409))

    def test_parent_checks_in_both_sequential_orders(self):
        building = self.post('/api/buildings', {'name': '测试空楼栋'})['id']
        self.assertEqual(self.client.delete(f'/api/buildings/{building}').status_code, 200)
        self.assertEqual(self.client.post('/api/units', json={'building_id': building, 'name': '隐藏单元'}).status_code, 400)
        lift = self.lift()
        unit = self.client.get(f'/api/elevators/{lift}').json()['unit_id']
        building = self.client.get(f'/api/elevators/{lift}').json()['building_id']
        self.assertEqual(self.client.delete(f'/api/buildings/{building}').status_code, 400)
        self.assertEqual(self.client.delete(f'/api/units/{unit}').status_code, 400)
        self.assertEqual(self.client.delete(f'/api/elevators/{lift}').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/units/{unit}').status_code, 200)
        self.assertEqual(self.client.post('/api/elevators', json={'unit_id': unit, 'name': '隐藏梯'}).status_code, 400)

    def test_old_archive_cannot_overwrite_event_status(self):
        lift = self.lift()
        url = f'/api/elevators/{lift}'
        old = self.client.get(url).json()
        event = self.event(lift, elevator_status='停梯')
        current = self.client.get(url).json()
        self.assertEqual((current['status'], current['version']), ('停梯', old['version'] + 1))
        response = self.client.put(url, json={**old, 'maintenance_phone': '000-TEST', 'building_name': '不应创建的楼栋'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('刷新', response.json()['detail'])
        self.assertEqual(self.client.get(url).json(), current)
        self.assertNotIn('不应创建的楼栋', [row['name'] for row in self.client.get('/api/buildings').json()])
        self.assertEqual(self.client.put(url, json={**current, 'maintenance_phone': '000-TEST'}).status_code, 200)
        updated = self.client.get(url).json()
        self.assertEqual((updated['status'], updated['version']), ('停梯', current['version'] + 1))
        # Editing a work record shares the same version counter as creating one.
        record = self.client.get(f'/api/events/{event}').json()
        self.assertEqual(self.client.put(f'/api/events/{event}', json={**record, 'elevator_status': '维修中'}).status_code, 200)
        self.assertEqual(self.client.put(url, json=updated).status_code, 409)
        self.assertEqual(self.client.get(url).json()['status'], '维修中')

    def test_archive_versions_are_required_and_conflict_with_other_archive_edits(self):
        lift = self.lift()
        url = f'/api/elevators/{lift}'
        old = self.client.get(url).json()
        missing = {key: value for key, value in old.items() if key != 'version'}
        for data in (missing, {**old, 'version': True}, {**old, 'version': str(old['version'])}):
            self.assertEqual(self.client.put(url, json=data).status_code, 409)
        self.assertEqual(self.client.put(url, json={**old, 'notes': '先保存的内容'}).status_code, 200)
        self.assertEqual(self.client.put(url, json=old).status_code, 409)
        self.assertEqual(self.client.get(url).json()['notes'], '先保存的内容')

    def test_existing_database_gets_version_without_losing_records(self):
        from backend import db
        lift = self.lift()
        with db.connect() as connection:
            connection.execute('ALTER TABLE elevators DROP COLUMN version')
        db.init_db()
        self.assertEqual(self.client.get(f'/api/elevators/{lift}').json()['version'], 1)
        db.init_db()
        self.assertEqual(len(self.client.get('/api/elevators').json()), 1)

    def symlink(self, link, target):
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Symlink creation unavailable: {exc}')

    def test_upload_rejects_escaping_nested_directory_links(self):
        event = self.event(self.lift())
        outside = self.paths['DATA'].parent / 'outside'
        outside.mkdir()
        for folder, filename, raw in (('attachments', '测试.pdf', b'%PDF-1.4\n%%EOF'),
                                      ('photos', '测试.png', Path('tests/fixtures/archive-photo.png').read_bytes())):
            for exists in (True, False):
                with self.subTest(folder=folder, target_exists=exists):
                    target = outside if exists else outside / 'must-not-be-created'
                    link = self.paths['STORAGE'] / folder
                    self.symlink(link, target)
                    try:
                        response = self.client.post(f'/api/events/{event}/attachments', files={'file': (filename, raw)})
                        self.assertEqual(response.status_code, 400, response.text)
                        self.assertEqual(self.client.get(f'/api/events/{event}').json()['attachments'], [])
                        self.assertEqual(list(outside.iterdir()), [])
                    finally:
                        link.unlink()
            # The same upload works once the storage directory is safe.
            response = self.client.post(f'/api/events/{event}/attachments', files={'file': (filename, raw)})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.get('/api/attachments/' + response.json()['id']).content, raw)
            # Keep the next subtest's database assertions independent.
            self.assertEqual(self.client.delete('/api/attachments/' + response.json()['id']).status_code, 200)

    def test_upload_rejects_final_file_link_without_overwriting_external_file(self):
        from backend import main
        event = self.event(self.lift())
        outside = self.paths['DATA'] / 'external.pdf'
        outside.write_bytes(b'external sentinel')
        folder = self.paths['STORAGE'] / 'attachments'
        folder.mkdir()
        link = folder / 'synthetic-id.pdf'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Symlink creation unavailable: {exc}')
        with patch.object(main.uuid, 'uuid4', return_value=SimpleNamespace(hex='synthetic-id')):
            response = self.client.post(f'/api/events/{event}/attachments', files={'file': ('测试.pdf', b'%PDF-1.4\n%%EOF')})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(outside.read_bytes(), b'external sentinel')
        self.assertEqual(self.client.get(f'/api/events/{event}').json()['attachments'], [])
