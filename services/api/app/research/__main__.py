"""Run from services/api: python -m app.research prepare|run."""
import argparse
import asyncio
from filelock import FileLock, Timeout
from .dataset import DATA_ROOT, prepare, canonicalize
from .runner import run

parser = argparse.ArgumentParser(description="Offline public-data research; never writes the live signal database")
parser.add_argument("command", choices=("prepare", "audit", "run", "exit-study", "filter-study"))
args = parser.parse_args()
DATA_ROOT.mkdir(exist_ok=True, parents=True)
try:
    with FileLock(str(DATA_ROOT / ".research.lock"), timeout=0):
        if args.command == "prepare":
            manifest = asyncio.run(prepare())
            manifest = canonicalize()
            print(f"Dataset ready: {manifest['dataset_hash']}")
        elif args.command == "audit":
            canonicalize()
        elif args.command in ("exit-study", "filter-study"):
            from .exit_study import run as run_study
            if args.command == "filter-study":
                from .reports import FILTER_ROOT
                run_study(report_root=FILTER_ROOT, entry_study=True)
            else:
                run_study()
        else:
            run()
except Timeout:
    raise SystemExit("Another local research acquisition/replay is already running")
