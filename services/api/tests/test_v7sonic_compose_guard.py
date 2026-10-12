"""Isolated V7 Compose guard must reject any merged V4/deploy service."""
from __future__ import annotations

from copy import deepcopy
from unittest import TestCase

from app.v7sonic_compose_guard import check_isolated_compose


def valid():
    return {
        "name": "mv-v7sonic-isolated",
        "services": {
            "v7-preflight": {
                "profiles": ["v7-private-diagnostics"],
                "image": "mv-v7sonic-private-test:sha-pinned",
                "command": ["python", "-m", "app.v7sonic_sql_paper_worker"],
                "network_mode": "none",
                "read_only": True,
                "user": "10001:10001",
                "restart": "no",
                "init": True,
                "privileged": False,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "tmpfs": ["/tmp:rw,nosuid,nodev,noexec,size=32m"],
            },
        },
    }


class IsolatedComposeTests(TestCase):
    def test_preflight_is_no_network_no_database_no_telegram(self):
        result = check_isolated_compose(valid())
        self.assertEqual(result["services_checked"], 1)
        self.assertFalse(result["network_allowed"])
        self.assertFalse(result["production_database_access_authorized"])
        self.assertFalse(result["telegram_publication_authorized"])
        self.assertFalse(result["exchange_orders_authorized"])

    def test_accidental_merge_with_v4_engine_telegram_or_db_refused(self):
        for forbidden_name in ("engine", "telegram", "db", "api", "v7-sender"):
            with self.subTest(name=forbidden_name):
                packet = valid()
                packet["services"][forbidden_name] = {"image": "mv-signal-api:0.14.0"}
                with self.assertRaisesRegex(ValueError, "extra Compose services"):
                    check_isolated_compose(packet)

    def test_wrong_compose_project_and_runtime_image_rejected(self):
        for bad_name in ("mv-signal", "v7", None):
            packet = valid()
            packet["name"] = bad_name
            with self.assertRaisesRegex(ValueError, "project name"):
                check_isolated_compose(packet)
        for image in ("mv-signal-api:0.14.0", "mv-v7:latest", "nginx:alpine"):
            packet = valid()
            packet["services"]["v7-preflight"]["image"] = image
            with self.assertRaises(ValueError):
                check_isolated_compose(packet)

    def test_network_ports_volumes_secrets_and_tty_writes_blocked(self):
        cases = (
            {"network_mode": "host"},
            {"ports": [{"target": 8000, "published": "8080"}]},
            {"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]},
            {"secrets": ["telegram_token"]},
            {"env_file": ["deploy/production.env"]},
            {"environment": {"MV_TELEGRAM_ENABLED": "true"}},
            {"depends_on": {"api": {"condition": "service_healthy"}}},
            {"read_only": False},
            {"privileged": True},
            {"restart": "always"},
        )
        for extra in cases:
            with self.subTest(extra=extra):
                packet = valid()
                packet["services"]["v7-preflight"].update(extra)
                with self.assertRaises(ValueError):
                    check_isolated_compose(packet)

    def test_unprivileged_staging_operator_cannot_replace_command_or_mount(self):
        cases = (
            {"command": ["python", "-m", "app.telegram.worker"]},
            {"entrypoint": ["bash", "-lc"]},
            {"user": "0:0"},
            {"cap_drop": []},
            {"security_opt": []},
            {"tmpfs": []},
            {"profiles": ["default"]},
        )
        for extra in cases:
            with self.subTest(extra=extra):
                packet = valid()
                packet["services"]["v7-preflight"].update(extra)
                with self.assertRaises(ValueError):
                    check_isolated_compose(packet)

    def test_top_level_credentials_volumes_or_secrets_always_rejected(self):
        for key in ("secrets", "volumes", "configs", "include"):
            with self.subTest(key=key):
                packet = valid()
                packet[key] = {"telegram_token": {"file": "/secrets/telegram_token"}}
                with self.assertRaises(ValueError):
                    check_isolated_compose(packet)


if __name__ == "__main__":
    import unittest
    unittest.main()
