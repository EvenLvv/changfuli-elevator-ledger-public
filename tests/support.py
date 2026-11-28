"""Isolated on-disk database and files for acceptance tests."""
import os
import tempfile
from contextlib import contextmanager, ExitStack
from pathlib import Path
from unittest.mock import patch


@contextmanager
def isolated_app(seed=None):
    from backend import db, main, backup, exporter
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory)
        paths = {name: root / folder for name, folder in (
            ('DATA', 'data'), ('STORAGE', 'storage'), ('EXPORTS', 'exports'),
            ('BACKUPS', 'backups'), ('LOGS', 'logs'))}
        for path in paths.values():
            path.mkdir()
        paths['DB'] = paths['DATA'] / 'elevator.db'
        for module in (db, main, backup, exporter):
            stack.enter_context(patch.multiple(module, **{k: v for k, v in paths.items() if hasattr(module, k)}))
        stack.enter_context(patch.object(main, 'ROOT', root))
        stack.enter_context(patch.dict(os.environ, ELEVATOR_SEED_LEDGER=str(seed or '')))
        with TestClient(main.app, client=('127.0.0.1', 50000)) as client:
            yield client, paths
