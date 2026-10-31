import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import DB, init_db

init_db()
print(f"数据库已准备好：{DB}")
