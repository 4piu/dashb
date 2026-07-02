"""Validated install of a theme distributed as a zip archive.

A theme zip is untrusted input - it may come from a random URL a user was
given. Extraction always goes through a temp directory first so a bad or
malicious archive never touches the real themes directory: entries are
checked for path traversal / absolute paths and the archive's total size is
capped before anything is written, then the validated content is moved into
place as the last step.
"""

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from dashb.theme import Theme, is_valid_theme_id

# Themes are static HTML/CSS/JS/fonts/small images - generous but not
# unbounded, to keep a bad zip from filling the disk.
MAX_THEME_ZIP_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_THEME_ZIP_ENTRIES = 2000


class ThemeInstallError(Exception):
    """Raised when a theme zip fails validation or extraction."""


def _safe_extract(archive: zipfile.ZipFile, dest: Path) -> None:
    infos = archive.infolist()
    if len(infos) > MAX_THEME_ZIP_ENTRIES:
        raise ThemeInstallError(f"Theme archive has too many entries (> {MAX_THEME_ZIP_ENTRIES})")

    total_size = sum(info.file_size for info in infos)
    if total_size > MAX_THEME_ZIP_UNCOMPRESSED_BYTES:
        limit_mb = MAX_THEME_ZIP_UNCOMPRESSED_BYTES // (1024 * 1024)
        raise ThemeInstallError(f"Theme archive is too large (> {limit_mb} MB uncompressed)")

    dest_resolved = dest.resolve()
    for info in infos:
        member_path = Path(info.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ThemeInstallError(f"Theme archive has an unsafe path: {info.filename}")
        target = (dest / member_path).resolve()
        if dest_resolved != target and dest_resolved not in target.parents:
            raise ThemeInstallError(f"Theme archive entry escapes the archive: {info.filename}")

    archive.extractall(dest)


def _content_root(extracted_dir: Path) -> Path:
    """A zip may contain theme files directly at its root, or wrapped in a single
    top-level folder (e.g. what GitHub's "Download ZIP" produces). Support both.
    """
    entries = list(extracted_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extracted_dir


def _load_theme_from_dir(theme_dir: Path) -> Theme:
    manifest_path = theme_dir / "theme.json"
    if not manifest_path.is_file():
        raise ThemeInstallError("Theme archive is missing theme.json")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        raise ThemeInstallError(f"theme.json is not valid JSON: {ex}") from ex
    if not isinstance(manifest, dict):
        raise ThemeInstallError("theme.json must contain a JSON object")

    theme_id = str(manifest.get("id") or "")
    if not is_valid_theme_id(theme_id):
        raise ThemeInstallError(
            "theme.json 'id' must be lowercase letters, numbers, '-' or '_' only"
        )

    entry = str(manifest.get("entry") or "index.html")
    entry_path = Path(entry)
    if entry_path.is_absolute() or ".." in entry_path.parts:
        raise ThemeInstallError(f"theme.json 'entry' has an unsafe path: {entry}")
    if not (theme_dir / entry_path).is_file():
        raise ThemeInstallError(f"theme.json 'entry' file is missing: {entry}")

    return Theme(
        id=theme_id,
        name=str(manifest.get("name") or theme_id),
        path=theme_dir,
        entry=entry,
        description=str(manifest.get("description") or ""),
        version=str(manifest.get("version") or ""),
        author=str(manifest.get("author") or ""),
        min_server_version=str(manifest.get("minServerVersion") or ""),
    )


def theme_id_in_zip(zip_path: Path) -> str:
    """Peek at a theme zip's id without installing it, e.g. to ask "overwrite?" before
    calling install_theme_from_zip.
    """
    with tempfile.TemporaryDirectory(prefix="dashb-theme-peek-") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(zip_path) as archive:
            _safe_extract(archive, tmp_path)
        theme = _load_theme_from_dir(_content_root(tmp_path))
        return theme.id


def install_theme_from_zip(zip_path: Path, user_theme_root: Path) -> Theme:
    """Validate and install a theme zip into user_theme_root, overwriting any existing
    theme with the same id. Raises ThemeInstallError on any validation failure; the
    real themes directory is never touched until validation succeeds.
    """
    if not zip_path.is_file():
        raise ThemeInstallError(f"File not found: {zip_path}")

    with tempfile.TemporaryDirectory(prefix="dashb-theme-install-") as tmp:
        tmp_path = Path(tmp)
        try:
            with zipfile.ZipFile(zip_path) as archive:
                _safe_extract(archive, tmp_path)
        except zipfile.BadZipFile as ex:
            raise ThemeInstallError(f"Not a valid zip file: {ex}") from ex

        content_root = _content_root(tmp_path)
        theme = _load_theme_from_dir(content_root)

        user_theme_root.mkdir(parents=True, exist_ok=True)
        destination = user_theme_root / theme.id
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(content_root), str(destination))

    return Theme(
        id=theme.id,
        name=theme.name,
        path=destination,
        entry=theme.entry,
        description=theme.description,
        version=theme.version,
        author=theme.author,
        min_server_version=theme.min_server_version,
    )


def theme_exists(theme_id: str, user_theme_root: Path) -> bool:
    return (user_theme_root / theme_id).is_dir()
