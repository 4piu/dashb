"""Theme discovery and static asset resolution."""

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from dashb.paths import app_root

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
    return app_root() / "web-app" / "dist"


def default_builtin_theme_root(webroot: Optional[Path] = None) -> Path:
    """Themes shipped inside the app bundle. Replaced whenever the app is rebuilt/updated."""
    return (webroot or default_webroot()) / "theme"


def default_user_theme_root() -> Path:
    """Writable directory for user-installed themes, separate from the app bundle so a rebuild
    or app update never touches them.
    """
    env_path = os.getenv("DASHB_USER_THEME_PATH")
    if env_path:
        return Path(env_path).expanduser()

    if os.name == "nt":
        base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "dashb" / "themes"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "dashb" / "themes"

    xdg_data_home = os.getenv("XDG_DATA_HOME")
    base_dir = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base_dir / "dashb" / "themes"


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


def _discover_themes_in_root(root: Path) -> List[Theme]:
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


def discover_themes(theme_roots: Sequence[Path]) -> List[Theme]:
    """Scan theme_roots in order and merge by id, later roots overriding earlier ones.

    This lets a user-installed theme override a built-in theme of the same id when
    theme_roots is [builtin_root, user_root].
    """
    by_id: Dict[str, Theme] = {}
    for root in theme_roots:
        for theme in _discover_themes_in_root(root):
            by_id[theme.id] = theme
    return sorted(by_id.values(), key=lambda theme: theme.id)


def find_theme(theme_id: str, theme_roots: Sequence[Path]) -> Optional[Theme]:
    if not is_valid_theme_id(theme_id):
        return None
    for theme in discover_themes(theme_roots):
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
