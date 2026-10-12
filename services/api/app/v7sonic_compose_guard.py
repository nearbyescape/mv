"""Static guard for V7Sonic's isolated preflight-only Compose project.

Accepts the JSON emitted by:
  docker compose -f compose.v7sonic-isolated.yml --profile v7-private-diagnostics config --format json

This is a check, NOT a deployer. Reject accidental V4 service merges,
credentials, DB/Telegram service dependencies, writable image, networking,
ports, host mounts, privileged access and an auto-restarting V7 preflight.
The live release requires a different reviewed manifest and authority.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


def check_isolated_compose(document: dict) -> dict:
    if not isinstance(document, dict):
        raise ValueError("Invalid isolated Compose document")
    if document.get("name") != "mv-v7sonic-isolated":
        raise ValueError("V7 must use its dedicated isolated project name")
    if set(document.get("services", {})) != {"v7-preflight"}:
        raise ValueError("Refusing any production, V4, DB or extra Compose services")
    for key in ("secrets", "volumes", "configs", "include"):
        if document.get(key):
            raise ValueError("No " + key + " allowed in isolated V7 Compose")
    service = document["services"]["v7-preflight"]
    if not isinstance(service, dict):
        raise ValueError("Invalid V7 Compose service")
    forbidden = (
        "depends_on", "secrets", "env_file", "volumes", "ports", "expose",
        "devices", "device_cgroup_rules", "build", "links", "extra_hosts",
        "network", "networks", "dns", "dns_search", "external_links",
        "volumes_from", "mounts", "entrypoint", "container_name",
    )
    if any(service.get(k) for k in forbidden):
        raise ValueError("Forbidden V7 preflight network, mount or service dependency")
    if service.get("environment"):
        raise ValueError("No secret or account settings allowed in V7 preflight")
    if (service.get("profiles") != ["v7-private-diagnostics"] or
            service.get("network_mode") != "none" or
            service.get("read_only") is not True or
            str(service.get("user")) != "10001:10001" or
            str(service.get("restart")) != "no" or
            service.get("privileged", False) is not False or
            service.get("pid") == "host" or
            service.get("ipc") == "host" or
            service.get("uts") == "host" or
            service.get("init") is not True or
            service.get("command") != [
                "python", "-m", "app.v7sonic_sql_paper_worker"
            ]):
        raise ValueError("V7 isolated service safety/entrypoint mismatch")
    caps = service.get("cap_drop")
    if not isinstance(caps, list) or set(caps) != {"ALL"}:
        raise ValueError("V7 preflight Linux capabilities not dropped")
    opts = service.get("security_opt")
    if not isinstance(opts, list) or "no-new-privileges:true" not in opts:
        raise ValueError("V7 requires no-new-privileges")
    image = service.get("image")
    if not isinstance(image, str) or not image.startswith("mv-"):
        raise ValueError("Use an explicitly tagged isolated V7 test image")
    if image == "mv-signal-api:0.14.0" or image.endswith(":latest"):
        raise ValueError("V4/rolling image forbidden in V7 preflight")
    if not service.get("tmpfs"):
        raise ValueError("V7 read-only image needs private bounded tmpfs")
    return {
        "status": "V7_ISOLATED_COMPOSE_PREFLIGHT_ONLY_APPROVED",
        "project": "mv-v7sonic-isolated",
        "services_checked": 1,
        "network_allowed": False,
        "production_database_access_authorized": False,
        "telegram_publication_authorized": False,
        "exchange_orders_authorized": False,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.v7sonic_compose_guard <compose-config.json>")
    item = Path(sys.argv[1])
    if not item.is_file() or item.stat().st_size > 250_000:
        raise SystemExit("Missing or excessively large Compose config")
    result = check_isolated_compose(json.loads(item.read_bytes()))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
