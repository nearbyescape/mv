"""Run isolated PostgreSQL checks against the LOOPBACK validation stack only."""
from pathlib import Path
import os
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
url=(root/"deploy/secrets/database_url").read_text().strip().replace("@db:5432/","@127.0.0.1:55432/")
environment={**os.environ,"MV_TEST_PG_URL":url}
raise SystemExit(subprocess.run([sys.executable,"-m","pytest","-q","tests/test_postgres_operations.py"],cwd=root/"services/api",env=environment).returncode)
