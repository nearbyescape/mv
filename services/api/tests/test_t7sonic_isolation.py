"""Prevent accidental revival of V4/V5/V6HBR inside T7Sonic research.

This test protects import closure, standalone image inputs and PR file scope.
It does NOT claim market performance, executable trade safety, nor ability
to prevent deliberate malicious code without OS-level isolation.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from app.research.t7sonic_isolation import (
    PROTECTED_PRODUCTION_FILES, validate_change_scope,
    validate_dedicated_image, validate_import_boundary,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES = REPO_ROOT / "services/api/app/research"


class T7SonicIsolationTests(unittest.TestCase):

    def test_source_has_only_t7sonic_and_stdlib_import_graph(self):
        report = validate_import_boundary(MODULES)
        self.assertEqual(report["production_strategy_runtime_imports"],0)
        self.assertEqual(len(report["checked_modules"]),8)
        self.assertFalse(report["permission_to_publish_signals"])
        for name, deps in report["direct_import_graph"].items():
            self.assertTrue(name.startswith("t7sonic_"))
            self.assertTrue(all(not dep.startswith(("v4","v5","v6hbr","mv_strategy"))
                                for dep in deps))

    def test_isolated_image_copies_no_legacy_model_code(self):
        report = validate_dedicated_image(REPO_ROOT)
        self.assertEqual(report["legacy_files_copied"],0)
        self.assertEqual(report["legacy_model_packages_installed"],0)
        self.assertEqual(report["runtime_user"],"10001:10001")

    def test_known_changes_are_research_only(self):
        files = {
            "services/api/app/research/t7sonic_isolation.py",
            "services/api/app/research/t7sonic_perception.py",
            "services/api/tests/test_t7sonic_isolation.py",
            "services/t7sonic/Dockerfile.research",
            ".github/workflows/t7sonic-research.yml",
            "packages/contracts/t7sonic-research-v1.json",
            "docs/T7SONIC_RESEARCH.md",
        }
        self.assertEqual(validate_change_scope(files)["changed_file_count"],len(files))
        for forbidden in PROTECTED_PRODUCTION_FILES:
            with self.assertRaisesRegex(ValueError,"protected production"):
                validate_change_scope(files|{forbidden})

    def test_invalid_non_research_file_change_rejected(self):
        for name in (
            "services/api/app/models.py", "packages/strategy/mv_strategy/signals.py",
            "compose.production.yml", ".github/workflows/ci.yml",
            "services/api/app/research/v6hbr_chronological_probability.py",
        ):
            with self.assertRaises(ValueError):
                validate_change_scope({name})

    def _edited_tree(self, path, replacement):
        temp=tempfile.TemporaryDirectory(prefix="t7sonic-isolation-test-")
        src=Path(temp.name)
        for p in MODULES.glob("t7sonic_*.py"):
            shutil.copyfile(p,src/p.name)
        target=src/path
        target.write_text(target.read_text()+replacement)
        return temp, src

    def test_importing_legacy_worker_fails_closed(self):
        for payload in (
            "\nfrom app.signals.worker import SignalWorker\n",
            "\nfrom ..signals import worker\n",
            "\nfrom .v6hbr_chronological_probability import train_logistic\n",
            "\nimport mv_strategy\n",
            "\nimport sqlalchemy\n",
        ):
            temp,src=self._edited_tree("t7sonic_experts.py",payload)
            try:
                with self.assertRaisesRegex(ValueError,"import"):
                    validate_import_boundary(src)
            finally:
                temp.cleanup()

    def test_dynamic_code_loader_fails_closed(self):
        for payload in (
            "\nx = __import__('app.signals.worker')\n",
            "\nx = eval('1+2')\n",
            "\nimport importlib\n",
            "\nx = compile('1','x','eval')\n",
        ):
            temp,src=self._edited_tree("t7sonic_experts.py",payload)
            try:
                with self.assertRaises(ValueError):
                    validate_import_boundary(src)
            finally:
                temp.cleanup()

    def test_new_unreviewed_model_file_cannot_auto_join_research_bundle(self):
        temp,src=self._edited_tree("t7sonic_experts.py","\n")
        try:
            (src/"t7sonic_legacy_model.py").write_text("x=1\n")
            with self.assertRaisesRegex(ValueError,"module name"):
                validate_import_boundary(src)
        finally:
            temp.cleanup()

    def test_standalone_image_scope_drift_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="t7sonic-image-guard-") as temp:
            p=Path(temp)/"services/t7sonic"
            p.mkdir(parents=True)
            current=(REPO_ROOT/"services/t7sonic/Dockerfile.research").read_text()
            (p/"Dockerfile.research").write_text(
                current+"\nCOPY services/api/app/signals/ /opt/t7sonic/app/signals/\n"
            )
            with self.assertRaisesRegex(ValueError,"legacy code"):
                validate_dedicated_image(Path(temp))


if __name__=="__main__":
    unittest.main()
