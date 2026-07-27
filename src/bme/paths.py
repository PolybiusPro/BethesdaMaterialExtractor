"""Material-path discovery from loose assets and game data containers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .errors import BmeError


_MATERIAL_BYTES = re.compile(
    rb"(?i)(?:materials?[\\/])"
    rb"[A-Za-z0-9_ !#$%&'()+,\-.;=@\[\]^`{}~\\/]{1,500}?\.mat"
)


def sanitize_material_path(path: str) -> str:
    """Normalize an arbitrary local/game path to a Materials-relative path."""
    normalized = path.strip().replace("/", "\\")
    lowered = normalized.casefold()
    position = lowered.find("material")
    if position > 0:
        normalized = normalized[position:]
    elif position < 0:
        normalized = (
            f"Materials{normalized}"
            if normalized.startswith("\\")
            else f"Materials\\{normalized}"
        )
    return normalized


def _canonical_key(path: str) -> str:
    return path.replace("/", "\\").casefold()


def _paths_from_bytes(data: bytes) -> set[str]:
    found: set[str] = set()
    for match in _MATERIAL_BYTES.finditer(data):
        text = match.group().decode("utf-8", errors="ignore")
        if text:
            found.add(sanitize_material_path(text))
    return found


def _paths_from_text(path: Path) -> list[str]:
    found: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
        for line in stream:
            candidate = line.strip()
            if candidate.casefold().endswith(".mat"):
                normalized = sanitize_material_path(candidate)
                found.setdefault(_canonical_key(normalized), normalized)
    return list(found.values())


def _paths_from_archive(path: Path) -> set[str]:
    from .ba2 import Ba2Archive

    archive = Ba2Archive.open(path)
    found: set[str] = set()
    for entry in archive.entries:
        if entry.name.casefold().endswith(".nif"):
            found.update(_paths_from_bytes(archive.read(entry)))
    return found


def _paths_from_file(path: Path) -> Iterable[str]:
    suffix = path.suffix.casefold()
    if suffix == ".mat":
        return {sanitize_material_path(str(path))}
    if suffix == ".txt":
        return _paths_from_text(path)
    if suffix == ".ba2":
        return _paths_from_archive(path)
    if suffix in {".nif", ".esp", ".esm", ".esl"}:
        return _paths_from_bytes(path.read_bytes())
    return set()


def discover_material_paths(inputs: Iterable[str | Path]) -> list[str]:
    """Discover unique material paths while preserving discovery order."""
    result: dict[str, str] = {}
    failures: list[str] = []
    for raw_path in inputs:
        path = Path(raw_path)
        try:
            if path.is_dir():
                candidates: set[str] = set()
                for nif in path.rglob("*"):
                    if nif.is_file() and nif.suffix.casefold() == ".nif":
                        candidates.update(_paths_from_file(nif))
            elif path.is_file():
                candidates = _paths_from_file(path)
            elif str(raw_path).casefold().endswith(".mat"):
                candidates = {sanitize_material_path(str(raw_path))}
            else:
                failures.append(str(raw_path))
                continue
            for candidate in sorted(candidates, key=str.casefold):
                result.setdefault(_canonical_key(candidate), candidate)
        except (OSError, BmeError) as exc:
            failures.append(f"{raw_path}: {exc}")
    if failures and not result:
        raise BmeError("No material paths found; " + "; ".join(failures))
    return list(result.values())
