"""Starfield resource identifiers and path hashing."""

from __future__ import annotations

from dataclasses import dataclass


def _make_crc_table() -> tuple[int, ...]:
    entries: list[int] = []
    for value in range(256):
        current = value
        for _ in range(8):
            current = (current >> 1) ^ (0xEDB88320 if current & 1 else 0)
        entries.append(current & 0xFFFFFFFF)
    return tuple(entries)


_CRC_TABLE = _make_crc_table()


def _game_path_bytes(path: str) -> bytes:
    raw = path.encode("utf-8")
    return bytes(
        0x5C if byte == 0x2F else byte + 0x20 if 0x41 <= byte <= 0x5A else byte
        for byte in raw
    )


def material_crc(path: str) -> int:
    """Return the unsigned decimal material ID shown by the application."""
    result = 0
    for byte in _game_path_bytes(path):
        result = _CRC_TABLE[(result ^ byte) & 0xFF] ^ (result >> 8)
    return result & 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class ResourceId:
    directory: int
    filename: int
    extension: int

    def __str__(self) -> str:
        return (
            f"res:{self.directory:08X}:{self.filename:08X}:"
            f"{self.extension:08X}"
        )


def _extension_code(extension: str) -> int:
    encoded = extension.encode("ascii", errors="replace")[:4]
    return int.from_bytes(encoded.ljust(4, b"\0"), "little")


def resource_id(path: str) -> ResourceId:
    """Create the three-part resource ID used by Starfield's material DB."""
    slash = max(path.rfind("/"), path.rfind("\\"))
    dot = path.rfind(".")
    if slash >= 0:
        stem_end = dot if dot > slash else len(path)
        directory = material_crc(path[:slash])
        filename = material_crc(path[slash + 1 : stem_end])
    else:
        directory = filename = material_crc(path)
    extension = _extension_code(path[dot + 1 :] if dot >= 0 else "")
    return ResourceId(directory, filename, extension)

