"""Generate deployment secrets once, with no secret values printed."""
import os
from pathlib import Path
import secrets

root=Path(__file__).resolve().parents[1]/"deploy"/"secrets"
root.mkdir(parents=True,exist_ok=True)
if os.name != "nt":
    root.chmod(0o700)
paths=[root/name for name in ("database_password","database_url","service_key","database_admin_password")]
if any(p.exists() for p in paths):
    raise SystemExit("Secrets already exist; refusing partial replacement or credential rotation")
password=secrets.token_urlsafe(48)
values=[password,"postgresql+psycopg://mv:"+password+"@db:5432/mv_signal",secrets.token_urlsafe(48),secrets.token_urlsafe(48)]
for path,value in zip(paths,values):
    with path.open("x",encoding="utf-8",newline="\n") as target:
        target.write(value+"\n")
    # The secret directory is owner-only. Compose bind-mounted secrets must be
    # readable by the unprivileged container UID; never place them in a public dir.
    if os.name != "nt":
        path.chmod(0o444)
print("Deployment secrets generated. Keep deploy/secrets private and backed up separately.")
