"""Fail-closed T7Sonic import-graph and isolated build-surface auditor.

This is a *static regression gate* for T7Sonic-only code and deployment
packaging, NOT a security sandbox. A separate networkless, nonprivileged,
read-only container is still required for running untrusted archive data.

No application or model import is executed during analysis.
"""
from __future__ import annotations

import ast
from pathlib import Path

PREFIX = "t7sonic_"
STDLIB_MODULES = frozenset({
    "__future__", "argparse", "calendar", "collections", "csv",
    "dataclasses", "datetime", "decimal", "hashlib", "io",
    "json", "pathlib", "re", "zipfile", "ast",
})
# Deny potential escape paths even if later code includes new imports.
DYNAMIC_CALLS = frozenset({"__import__", "eval", "exec", "compile", "open"})
DYNAMIC_MODULES = frozenset({"importlib", "subprocess", "socket", "urllib", "http",
                             "requests", "httpx", "sqlalchemy", "mv_strategy"})
FORBIDDEN_ROOTS = frozenset({"app", "packages", "mv_strategy", "torch", "tensorflow",
                              "xgboost", "sklearn", "requests", "httpx", "sqlalchemy"})
PROTECTED_PRODUCTION_FILES = frozenset({
    "compose.production.yml", "compose.telegram.yml", "compose.ai.yml",
    "services/api/Dockerfile", "services/api/app/signals/worker.py",
    "services/api/app/signals/service.py", "services/api/app/market/collector.py",
    "services/api/app/telegram/worker.py", "services/api/app/main.py",
    "packages/strategy/pyproject.toml",
})
EXECUTION_DOCKERFILE = "services/t7sonic/Dockerfile.research"


def _module_tree(source_dir: Path) -> dict[str, ast.Module]:
    files = sorted(source_dir.glob(PREFIX + "*.py"))
    if len(files) < 6 or not all(f.is_file() and not f.is_symlink() for f in files):
        raise ValueError("Missing or symlinked dedicated T7Sonic research modules")
    if {f.stem for f in files} != {
        "t7sonic_cli", "t7sonic_experts", "t7sonic_perception",
        "t7sonic_history", "t7sonic_history_cli", "t7sonic_isolation",
    }:
        raise ValueError("Unreviewed T7Sonic model/runtime module name; extend allowlist explicitly")
    return {f.stem:ast.parse(f.read_text(encoding="utf8"),filename=str(f))
            for f in files}


def validate_import_boundary(source_dir: Path) -> dict:
    modules = _module_tree(source_dir)
    edges = {}
    for module, tree in modules.items():
        deps = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in STDLIB_MODULES or root in FORBIDDEN_ROOTS:
                        raise ValueError(f"{module} imports non-allowlisted module: {alias.name}")
                    deps.add(root)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 1:
                    if node.module not in modules:
                        raise ValueError(
                            f"{module} imports non-T7Sonic sibling module: {node.module}"
                        )
                    deps.add(node.module)
                elif node.level != 0 or (node.module or "").split(".")[0] not in STDLIB_MODULES:
                    raise ValueError(f"{module} imports application or non-stdlib dependency")
                else:
                    deps.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in DYNAMIC_CALLS:
                    raise ValueError(f"{module} uses prohibited dynamic import/eval/filesystem call")
                if isinstance(fn, ast.Attribute) and fn.attr in {"import_module","exec_module",
                                                                  "system","popen","run","Popen"}:
                    raise ValueError(f"{module} uses prohibited dynamic execution")
        edges[module] = sorted(deps)
    return {
        "status":"ONLY_EXPLICIT_T7SONIC_MODULES_AND_ALLOWLISTED_STDLIB_IMPORTS",
        "checked_modules":sorted(modules),
        "direct_import_graph":edges,
        "production_strategy_runtime_imports":0,
        "permission_to_publish_signals":False,
    }


def validate_dedicated_image(root: Path) -> dict:
    dockerfile = root / EXECUTION_DOCKERFILE
    if dockerfile.is_symlink() or not dockerfile.is_file():
        raise ValueError("Missing standalone research image Dockerfile")
    instructions = []
    logical = dockerfile.read_text(encoding="utf8")
    for raw in logical.splitlines():
        line=raw.strip()
        if line and not line.startswith("#"):
            instructions.append(line)
    copies=[x for x in instructions if x.upper().startswith(("COPY ","ADD "))]
    permitted_copies={
        "COPY services/api/app/research/t7sonic_*.py /opt/t7sonic/app/research/",
        "COPY packages/contracts/t7sonic-research-v1.json /opt/t7sonic/contracts/",
    }
    if set(copies) != permitted_copies or len(copies)!=len(permitted_copies):
        raise ValueError("Standalone image would include legacy code or unreviewed files")
    if not any(line=="USER 10001:10001" for line in instructions):
        raise ValueError("Standalone image must run unprivileged")
    if any(
        line.upper().startswith("ENTRYPOINT ") or
        ("app.signals" in line or "app.market.collector" in line or
         "docker compose" in line or "mv_strategy" in line)
        for line in instructions
    ):
        raise ValueError("Standalone research image references legacy application services")
    return {
        "status":"DOCKERFILE_ONLY_T7SONIC_MODULES_AND_CONTRACT",
        "allowed_copy_instructions":sorted(permitted_copies),
        "legacy_files_copied":0,
        "legacy_model_packages_installed":0,
        "runtime_user":"10001:10001",
    }


def validate_change_scope(paths: set[str]) -> dict:
    if paths & PROTECTED_PRODUCTION_FILES:
        raise ValueError("T7Sonic PR modifies protected production runtime files")
    if any(p.startswith(("services/api/app/signals/",
                          "services/api/app/telegram/",
                          "services/api/app/ai/",
                          "services/api/app/market/",
                          "packages/strategy/")) for p in paths):
        raise ValueError("T7Sonic PR touches old strategy/worker implementation")
    allowed_roots=(
        "services/api/app/research/t7sonic_",
        "services/api/tests/test_t7sonic_",
        "packages/contracts/t7sonic-research-v1.json",
        "docs/T7SONIC_RESEARCH.md",
        ".github/workflows/t7sonic-research.yml",
        "services/t7sonic/",
    )
    if any(not any(p.startswith(prefix) for prefix in allowed_roots) for p in paths):
        raise ValueError("T7Sonic PR modifies an unrelated file; explicit review required")
    return {"status":"RESEARCH_ONLY_CHANGED_PATHS","changed_file_count":len(paths)}
