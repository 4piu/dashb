"""Theme discovery and static asset resolution."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


THEME_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    path: Path
    entry: str = "index.html"
    description: str = ""
    version: str = ""
    author: str = ""
    min_server_version: str = ""

    def to_api_dict(self) -> Dict[str, str]:
        result = {
            "id": self.id,
            "name": self.name,
            "path": f"/theme/{self.id}/",
            "description": self.description,
        }
        if self.version:
            result["version"] = self.version
        if self.author:
            result["author"] = self.author
        if self.min_server_version:
            result["minServerVersion"] = self.min_server_version
        return result


def default_webroot() -> Path:
    env_path = os.getenv("DASHB_WEBROOT_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path(__file__).resolve().parent.parent / "web-app" / "dist"


def default_theme_root(webroot: Optional[Path] = None) -> Path:
    env_path = os.getenv("DASHB_THEME_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return (webroot or default_webroot()) / "theme"


def is_valid_theme_id(theme_id: str) -> bool:
    return bool(THEME_ID_PATTERN.fullmatch(theme_id))


def _read_manifest(theme_dir: Path) -> Dict[str, Any]:
    manifest_path = theme_dir / "theme.json"
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def discover_themes(theme_root: Optional[Path] = None) -> List[Theme]:
    root = theme_root or default_theme_root()
    if not root.exists():
        return []

    themes: List[Theme] = []
    for theme_dir in sorted(root.iterdir()):
        if not theme_dir.is_dir():
            continue

        manifest = _read_manifest(theme_dir)
        theme_id = str(manifest.get("id") or theme_dir.name)
        if not is_valid_theme_id(theme_id):
            continue

        entry = str(manifest.get("entry") or "index.html")
        if Path(entry).is_absolute() or ".." in Path(entry).parts:
            continue
        if not (theme_dir / entry).is_file():
            continue

        themes.append(
            Theme(
                id=theme_id,
                name=str(manifest.get("name") or theme_id),
                path=theme_dir,
                entry=entry,
                description=str(manifest.get("description") or ""),
                version=str(manifest.get("version") or ""),
                author=str(manifest.get("author") or ""),
                min_server_version=str(manifest.get("minServerVersion") or ""),
            )
        )
    return themes


def find_theme(theme_id: str, theme_root: Optional[Path] = None) -> Optional[Theme]:
    if not is_valid_theme_id(theme_id):
        return None
    for theme in discover_themes(theme_root):
        if theme.id == theme_id:
            return theme
    return None


def resolve_theme_asset(theme: Theme, asset_path: str) -> Optional[Path]:
    relative_path = Path(asset_path or theme.entry)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return None

    resolved_root = theme.path.resolve()
    resolved_asset = (theme.path / relative_path).resolve()
    if resolved_root != resolved_asset and resolved_root not in resolved_asset.parents:
        return None
    if not resolved_asset.is_file():
        return None
    return resolved_asset


def resolve_webroot_asset(webroot: Path, asset_path: str) -> Optional[Path]:
    relative_path = Path(asset_path or "index.html")
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return None

    resolved_root = webroot.resolve()
    resolved_asset = (webroot / relative_path).resolve()
    if resolved_root != resolved_asset and resolved_root not in resolved_asset.parents:
        return None
    if not resolved_asset.is_file():
        return None
    return resolved_asset
