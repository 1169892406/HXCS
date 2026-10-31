from __future__ import annotations

import importlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import InvalidIntegration, UnsupportedAPI

BASELINE = "2026.10-phase2"
ALLOWED_MANIFEST_KEYS = {"domain", "name", "version", "config_flow", "documentation", "requirements",
                         "dependencies", "after_dependencies", "iot_class", "codeowners"}
PINNED = re.compile(r"^[A-Za-z0-9_.-]+==[^/\\\s]+$")


@dataclass(frozen=True, slots=True)
class IntegrationPackage:
    domain: str
    root: Path
    manifest: dict[str, Any]
    module_name: str


def inspect_package(path: Path) -> IntegrationPackage:
    path = path.resolve()
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file() or not (path / "__init__.py").is_file():
        raise InvalidIntegration("integration requires manifest.json and __init__.py")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidIntegration(f"invalid manifest: {exc}") from exc
    domain = manifest.get("domain")
    if not isinstance(domain, str) or not re.fullmatch(r"[a-z0-9_]+", domain):
        raise InvalidIntegration("manifest domain is missing or invalid")
    if path.name != domain:
        raise InvalidIntegration("directory name must match manifest domain")
    if not manifest.get("name"):
        raise InvalidIntegration("manifest name is required")
    if "custom_components" in path.parts and not manifest.get("version"):
        raise InvalidIntegration("custom component manifest version is required")
    for req in manifest.get("requirements", []):
        if not PINNED.fullmatch(req) or any(x in req for x in ("git+", "http:", "https:", "file:")):
            raise InvalidIntegration(f"requirement must be a pinned package: {req}")
    source = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in path.rglob("*.py"))
    forbidden = {"subprocess": "subprocess", "os.system": "os.system", "pip install": "pip install"}
    for needle, symbol in forbidden.items():
        if needle in source:
            raise UnsupportedAPI(f"forbidden runtime API: {symbol}", symbol=symbol)
    parent = path.parent
    module_name = f"custom_components.{domain}" if parent.name == "custom_components" else domain
    return IntegrationPackage(domain, path, manifest, module_name)


def load_package(package: IntegrationPackage):
    search_root = package.root.parent.parent if package.module_name.startswith("custom_components.") else package.root.parent
    if str(search_root) not in sys.path:
        sys.path.insert(0, str(search_root))
    try:
        return importlib.import_module(package.module_name)
    except ImportError as exc:
        if exc.name and exc.name.startswith("homeassistant"):
            raise UnsupportedAPI(f"unsupported HA API import: {exc.name}", symbol=exc.name) from exc
        raise
