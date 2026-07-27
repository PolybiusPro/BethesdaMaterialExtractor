"""Application-level operations shared by the CLI and desktop UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .ba2 import Ba2TextureArchive
from .cdb import MaterialDatabase, load_material_database
from .errors import FormatError, MissingMaterialError
from .paths import discover_material_paths


Progress = Callable[[int, int, str], None]
Discovery = Callable[[list[str]], None]


def starfield_install_path() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        key_path = (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
            r"\Steam App 1716740"
        )
        views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
        for view in views:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    key_path,
                    0,
                    winreg.KEY_READ | view,
                ) as key:
                    value, _kind = winreg.QueryValueEx(key, "InstallLocation")
                    candidate = Path(value)
                    if candidate.exists():
                        return candidate
            except OSError:
                continue
    except (ImportError, OSError):
        pass
    return None


def default_database_path() -> Path | None:
    install = starfield_install_path()
    if install is None:
        return None
    candidates = (
        install / "Data" / "Materials" / "materialsbeta.cdb",
        install / "Data" / "Starfield - Materials.ba2",
    )
    return next((path for path in candidates if path.exists()), None)


def _base_database_for(database: Path) -> Path | None:
    candidates = (
        database.parent / "Materials" / "materialsbeta.cdb",
        database.parent / "Starfield - Materials.ba2",
        default_database_path(),
    )
    selected = database.resolve()
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            if candidate.resolve() != selected:
                return candidate
    return None


def corresponding_texture_archive(main_archive: str | Path) -> Path | None:
    """Find the sibling texture BA2 paired with a ``- Main.ba2`` archive."""
    main_path = Path(main_archive)
    suffix = " - main.ba2"
    if not main_path.name.casefold().endswith(suffix):
        return None
    prefix = main_path.name[: -len(suffix)]
    wanted = {
        f"{prefix} - textures.ba2".casefold(),
        f"{prefix} - texture.ba2".casefold(),
    }
    try:
        return next(
            (
                sibling
                for sibling in main_path.parent.iterdir()
                if sibling.is_file() and sibling.name.casefold() in wanted
            ),
            None,
        )
    except OSError:
        return None


def export_from_inputs(
    database: str | Path,
    output: str | Path,
    inputs: list[str | Path],
    *,
    explicit_materials: list[str] | None = None,
    progress: Progress | None = None,
    discovered: Discovery | None = None,
) -> list[Path]:
    database_path = Path(database)
    texture_path = corresponding_texture_archive(database_path)
    texture_archive = (
        Ba2TextureArchive.open(texture_path) if texture_path is not None else None
    )
    discovery_inputs = list(inputs)
    if database_path.suffix.casefold() == ".ba2":
        selected = database_path.resolve()
        if not any(Path(item).resolve() == selected for item in discovery_inputs):
            discovery_inputs.insert(0, database_path)
    paths = discover_material_paths(discovery_inputs)
    if explicit_materials:
        from .paths import sanitize_material_path

        paths.extend(sanitize_material_path(path) for path in explicit_materials)
    unique = list(
        {
            path.replace("/", "\\").casefold(): path
            for path in paths
        }.values()
    )
    if discovered:
        discovered(unique)
    if not unique and texture_archive is None:
        return []
    written: list[Path] = []
    material_steps = len(unique) + 1 if unique else 0
    texture_steps = len(texture_archive.entries) if texture_archive else 0
    maximum = material_steps + texture_steps
    if unique:
        if progress:
            progress(0, maximum, "Reading material database")
        base_path = (
            _base_database_for(database_path)
            if database_path.suffix.casefold() == ".ba2"
            else None
        )
        try:
            loaded = load_material_database(database_path)
        except FormatError as exc:
            if (
                database_path.suffix.casefold() != ".ba2"
                or not str(exc).startswith("No materialsbeta.cdb is present in ")
                or base_path is None
            ):
                raise
            loaded = load_material_database(base_path)
        else:
            if base_path is not None:
                loaded = MaterialDatabase.layered(
                    load_material_database(base_path), loaded
                )
        if progress:
            progress(1, maximum, "Writing materials")
        # Write one at a time so callers receive useful progress and partial
        # results.
        id_to_path: dict[int, str] = {}
        from .cdb import ROOT_MATERIAL_PATHS

        for path in [*unique, *ROOT_MATERIAL_PATHS]:
            db_id = loaded.material_id(path)
            if db_id:
                id_to_path.setdefault(db_id, path)
        import json

        output_root = Path(output)
        for index, path in enumerate(unique, 2):
            try:
                document = loaded.export_document(path, id_to_path)
            except MissingMaterialError:
                if progress:
                    progress(
                        index,
                        maximum,
                        f"Skipping (not in database): {path}",
                    )
                continue
            destination = output_root / Path(
                *path.replace("/", "\\").split("\\")
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(document, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            written.append(destination)
            if progress:
                progress(index, maximum, path)

    if texture_archive is not None:
        if progress:
            progress(
                material_steps,
                maximum,
                f"Reading texture archive: {texture_archive.path.name}",
            )

        def texture_progress(index: int, _count: int, label: str) -> None:
            if progress:
                progress(material_steps + index, maximum, f"Texture: {label}")

        written.extend(
            texture_archive.extract_all(
                output,
                progress=texture_progress,
            )
        )
    return written
