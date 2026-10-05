"""Create a portable source release with explicit roots; exclude runtime data/secrets."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
DESTINATION = ROOT / "artifacts" / "releases"
DESTINATION.mkdir(parents=True, exist_ok=True)
DIRECTORIES = ("apps/web", "services/api", "packages", "docs", "tools", ".github", "deploy")
EXCLUDED = {"node_modules", ".next", ".venv", "__pycache__", ".pytest_cache", "test-results", "playwright-report", "secrets", "backups", ".runtime"}
ROOT_FILES = ("README.md", "AGENTS.md", "THIRD_PARTY_NOTICES.md", ".gitignore", ".gitattributes", ".dockerignore", ".prettierignore", ".env.example", "package.json", "package-lock.json", "compose.production.yml", "compose.validation.yml", "compose.research.yml", "compose.host-proxy.yml", "compose.ai.yml", "compose.telegram.yml")

def eligible(path):
    relative = path.relative_to(ROOT)
    return not path.is_symlink() and not any(p in EXCLUDED or p.endswith(".egg-info") for p in relative.parts) and not any(relative.name.endswith(s) for s in (".db", ".db-shm", ".db-wal", ".db.lock", ".lock", ".log", ".pyc", ".tsbuildinfo")) and not (relative.name.startswith(".env") and relative.name != ".env.example") and relative.as_posix() != "deploy/production.env"

files = {ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()}
for name in DIRECTORIES:
    for directory, children, names in os.walk(ROOT / name):
        children[:] = [d for d in children if d not in EXCLUDED and not d.endswith(".egg-info") and not (Path(directory)/d).is_symlink()]
        files.update(p for n in names if (p:=Path(directory)/n).is_file() and eligible(p))
secrets = [(ROOT / "deploy/secrets" / name).read_bytes().strip() for name in ("database_password", "database_admin_password", "database_url", "service_key", "openrouter_key", "telegram_token") if (ROOT / "deploy/secrets" / name).exists()]
manifest = {}
prefix = "mv-signal-" + VERSION
archive = DESTINATION / (prefix + ".tar.gz")
with archive.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w") as bundle:
    for path in sorted(files):
        name = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        if name.endswith(".sh"):
            data = data.replace(b"\r\n", b"\n")
        if any(secret and secret in data for secret in secrets):
            raise SystemExit("A local secret was found in a release source: " + name)
        info = tarfile.TarInfo(prefix + "/" + name)
        info.size, info.mode, info.mtime = len(data), 0o644, 0
        bundle.addfile(info, io.BytesIO(data))
        manifest[name] = hashlib.sha256(data).hexdigest()
    data = json.dumps({"version": VERSION, "files": manifest, "excluded": "runtime databases, secrets, backups, research archives/reports, build outputs and dependency directories"}, indent=2, sort_keys=True).encode()
    info = tarfile.TarInfo(prefix + "/release-manifest.json")
    info.size, info.mode, info.mtime = len(data), 0o644, 0
    bundle.addfile(info, io.BytesIO(data))
with archive.open("rb") as source:
    hasher=hashlib.sha256()
    for chunk in iter(lambda:source.read(1024*1024),b""):
        hasher.update(chunk)
    digest=hasher.hexdigest()
archive.with_suffix(".gz.sha256").write_text(digest + "  " + archive.name + "\n", encoding="utf-8")
with tarfile.open(archive, "r:gz") as bundle:
    for name, expected in manifest.items():
        assert hashlib.sha256(bundle.extractfile(prefix + "/" + name).read()).hexdigest() == expected
print(json.dumps({"archive": str(archive), "files": len(manifest), "bytes": archive.stat().st_size, "sha256": digest, "verified": "all archived bytes and local secret exclusion"}, indent=2))
