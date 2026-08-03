"""Reader for the general BA2 archives used by Fallout 4 and Starfield."""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .crc import resource_id
from .errors import FormatError


_MAX_FILES = 4_000_000
_MAX_ENTRY_SIZE = 2 * 1024 * 1024 * 1024
_SENTINEL = 0xBAADF00D


def _lz4_block(data: bytes, output_size: int) -> bytes:
    """Decode a raw LZ4 block without requiring a third-party module."""
    source = memoryview(data)
    target = bytearray()
    cursor = 0
    while cursor < len(source):
        token = source[cursor]
        cursor += 1
        literal_length = token >> 4
        if literal_length == 15:
            while True:
                if cursor >= len(source):
                    raise FormatError("Truncated LZ4 literal length")
                extra = source[cursor]
                cursor += 1
                literal_length += extra
                if extra != 255:
                    break
        end = cursor + literal_length
        if end > len(source):
            raise FormatError("Truncated LZ4 literal")
        target.extend(source[cursor:end])
        cursor = end
        if cursor == len(source):
            break
        if cursor + 2 > len(source):
            raise FormatError("Truncated LZ4 match offset")
        offset = int.from_bytes(source[cursor : cursor + 2], "little")
        cursor += 2
        if offset == 0 or offset > len(target):
            raise FormatError("Invalid LZ4 match offset")
        match_length = token & 0x0F
        if match_length == 15:
            while True:
                if cursor >= len(source):
                    raise FormatError("Truncated LZ4 match length")
                extra = source[cursor]
                cursor += 1
                match_length += extra
                if extra != 255:
                    break
        match_length += 4
        for _ in range(match_length):
            target.append(target[-offset])
        if len(target) > output_size:
            raise FormatError("LZ4 output exceeds its declared size")
    if len(target) != output_size:
        raise FormatError(
            f"LZ4 size mismatch: expected {output_size}, got {len(target)}"
        )
    return bytes(target)


@dataclass(slots=True)
class Ba2Chunk:
    offset: int
    packed_size: int
    unpacked_size: int


@dataclass(slots=True)
class Ba2Entry:
    name_hash: tuple[int, int, int]
    name: str
    chunks: list[Ba2Chunk]


@dataclass(slots=True)
class Ba2TextureChunk:
    offset: int
    packed_size: int
    unpacked_size: int
    first_mip: int
    last_mip: int


@dataclass(slots=True)
class Ba2TextureEntry:
    name_hash: tuple[int, int, int]
    name: str
    height: int
    width: int
    mip_count: int
    dxgi_format: int
    flags: int
    chunks: list[Ba2TextureChunk]


class Ba2Archive:
    def __init__(
        self,
        path: Path,
        *,
        version: int,
        compression: str,
        entries: list[Ba2Entry],
    ) -> None:
        self.path = path
        self.version = version
        self.compression = compression
        self.entries = entries

    @classmethod
    def open(cls, path: str | Path) -> "Ba2Archive":
        archive_path = Path(path)
        with archive_path.open("rb") as stream:
            fixed = stream.read(24)
            if len(fixed) != 24:
                raise FormatError("Truncated BA2 header")
            magic, version, kind, count, names_offset = struct.unpack(
                "<4sI4sIQ", fixed
            )
            if magic != b"BTDX":
                raise FormatError("Not a BA2 archive")
            if version not in {1, 2, 3}:
                raise FormatError(f"Unsupported BA2 version {version}")
            if kind != b"GNRL":
                raise FormatError(
                    f"Only general BA2 archives are supported, not {kind!r}"
                )
            if count > _MAX_FILES:
                raise FormatError("Unreasonable BA2 entry count")
            compression = "zlib"
            if version >= 2:
                if len(stream.read(8)) != 8:
                    raise FormatError("Truncated BA2 v2 header")
            if version >= 3:
                marker_data = stream.read(4)
                if len(marker_data) != 4:
                    raise FormatError("Truncated BA2 v3 header")
                compression = (
                    "lz4" if struct.unpack("<I", marker_data)[0] == 3 else "zlib"
                )

            entries: list[Ba2Entry] = []
            for _ in range(count):
                hash_data = stream.read(12)
                file_data = stream.read(4)
                if len(hash_data) != 12 or len(file_data) != 4:
                    raise FormatError("Truncated BA2 entry table")
                name_hash = struct.unpack("<III", hash_data)
                _mod, chunk_count, header_size = struct.unpack("<BBH", file_data)
                if header_size != 0x10:
                    raise FormatError("Invalid general BA2 chunk header size")
                chunks: list[Ba2Chunk] = []
                for _ in range(chunk_count):
                    chunk_data = stream.read(20)
                    if len(chunk_data) != 20:
                        raise FormatError("Truncated BA2 chunk table")
                    offset, packed, unpacked, sentinel = struct.unpack(
                        "<QIII", chunk_data
                    )
                    if sentinel != _SENTINEL:
                        raise FormatError("Invalid BA2 chunk sentinel")
                    stored = packed or unpacked
                    if stored > _MAX_ENTRY_SIZE or unpacked > _MAX_ENTRY_SIZE:
                        raise FormatError("BA2 entry exceeds safety limit")
                    chunks.append(Ba2Chunk(offset, packed, unpacked))
                entries.append(Ba2Entry(name_hash, "", chunks))

            if names_offset:
                stream.seek(names_offset)
                for entry in entries:
                    length_data = stream.read(2)
                    if len(length_data) != 2:
                        raise FormatError("Truncated BA2 filename table")
                    length = struct.unpack("<H", length_data)[0]
                    encoded = stream.read(length)
                    if len(encoded) != length:
                        raise FormatError("Truncated BA2 filename")
                    entry.name = encoded.decode("utf-8", errors="replace")

        return cls(
            archive_path,
            version=version,
            compression=compression,
            entries=entries,
        )

    def find(self, name: str) -> Ba2Entry | None:
        normalized = name.replace("\\", "/").casefold()
        for entry in self.entries:
            if entry.name.replace("\\", "/").casefold() == normalized:
                return entry
        wanted = resource_id(name)
        wanted_hash = (wanted.filename, wanted.extension, wanted.directory)
        return next(
            (entry for entry in self.entries if entry.name_hash == wanted_hash),
            None,
        )

    def read(self, entry: Ba2Entry) -> bytes:
        output = io.BytesIO()
        with self.path.open("rb") as stream:
            for chunk in entry.chunks:
                stream.seek(chunk.offset)
                stored_size = chunk.packed_size or chunk.unpacked_size
                payload = stream.read(stored_size)
                if len(payload) != stored_size:
                    raise FormatError(f"Truncated BA2 data for {entry.name}")
                if chunk.packed_size:
                    try:
                        payload = (
                            _lz4_block(payload, chunk.unpacked_size)
                            if self.compression == "lz4"
                            else zlib.decompress(payload)
                        )
                    except zlib.error as exc:
                        raise FormatError(
                            f"Unable to decompress {entry.name}: {exc}"
                        ) from exc
                    if len(payload) != chunk.unpacked_size:
                        raise FormatError(
                            f"Decompressed size mismatch for {entry.name}"
                        )
                output.write(payload)
        return output.getvalue()

    def read_named(self, name: str) -> bytes:
        entry = self.find(name)
        if entry is None:
            raise FormatError(f"{name} is not present in {self.path}")
        return self.read(entry)


_BC_BLOCK_BYTES = {
    **{value: 8 for value in (70, 71, 72, 79, 80, 81)},
    **{
        value: 16
        for value in (
            73,
            74,
            75,
            76,
            77,
            78,
            82,
            83,
            84,
            94,
            95,
            96,
            97,
            98,
            99,
        )
    },
}

_UNCOMPRESSED_BYTES = {
    28: 4,  # DXGI_FORMAT_R8G8B8A8_UNORM
}


class Ba2TextureArchive:
    """Reader and DDS exporter for Bethesda DX10 texture BA2 archives."""

    def __init__(
        self,
        path: Path,
        *,
        version: int,
        compression: str,
        entries: list[Ba2TextureEntry],
    ) -> None:
        self.path = path
        self.version = version
        self.compression = compression
        self.entries = entries

    @classmethod
    def open(cls, path: str | Path) -> "Ba2TextureArchive":
        archive_path = Path(path)
        with archive_path.open("rb") as stream:
            fixed = stream.read(24)
            if len(fixed) != 24:
                raise FormatError("Truncated BA2 header")
            magic, version, kind, count, names_offset = struct.unpack(
                "<4sI4sIQ", fixed
            )
            if magic != b"BTDX":
                raise FormatError("Not a BA2 archive")
            if version not in {1, 2, 3}:
                raise FormatError(f"Unsupported BA2 version {version}")
            if kind != b"DX10":
                raise FormatError(
                    f"Expected a DX10 texture BA2 archive, not {kind!r}"
                )
            if count > _MAX_FILES:
                raise FormatError("Unreasonable BA2 entry count")
            compression = "zlib"
            if version >= 2 and len(stream.read(8)) != 8:
                raise FormatError("Truncated BA2 v2 header")
            if version >= 3:
                marker_data = stream.read(4)
                if len(marker_data) != 4:
                    raise FormatError("Truncated BA2 v3 header")
                compression = (
                    "lz4" if struct.unpack("<I", marker_data)[0] == 3 else "zlib"
                )

            entries: list[Ba2TextureEntry] = []
            for _ in range(count):
                record = stream.read(24)
                if len(record) != 24:
                    raise FormatError("Truncated BA2 texture record")
                (
                    filename_hash,
                    extension,
                    directory_hash,
                    _unknown,
                    chunk_count,
                    chunk_header_size,
                    height,
                    width,
                    mip_count,
                    dxgi_format,
                    flags,
                ) = struct.unpack("<I4sIBBHHHBBH", record)
                if extension.rstrip(b"\0").lower() != b"dds":
                    raise FormatError("DX10 BA2 entry is not a DDS texture")
                if chunk_header_size != 24:
                    raise FormatError("Invalid DX10 BA2 chunk header size")
                chunks: list[Ba2TextureChunk] = []
                for _ in range(chunk_count):
                    chunk_data = stream.read(chunk_header_size)
                    if len(chunk_data) != chunk_header_size:
                        raise FormatError("Truncated DX10 BA2 chunk table")
                    (
                        offset,
                        packed,
                        unpacked,
                        first_mip,
                        last_mip,
                        sentinel,
                    ) = struct.unpack("<QIIHHI", chunk_data)
                    if sentinel != _SENTINEL:
                        raise FormatError("Invalid DX10 BA2 chunk sentinel")
                    stored = packed or unpacked
                    if stored > _MAX_ENTRY_SIZE or unpacked > _MAX_ENTRY_SIZE:
                        raise FormatError("BA2 texture chunk exceeds safety limit")
                    chunks.append(
                        Ba2TextureChunk(
                            offset,
                            packed,
                            unpacked,
                            first_mip,
                            last_mip,
                        )
                    )
                entries.append(
                    Ba2TextureEntry(
                        (filename_hash, int.from_bytes(extension, "little"), directory_hash),
                        "",
                        height,
                        width,
                        mip_count,
                        dxgi_format,
                        flags,
                        chunks,
                    )
                )

            if not names_offset and entries:
                raise FormatError("DX10 BA2 archive has no filename table")
            if names_offset:
                stream.seek(names_offset)
                for entry in entries:
                    length_data = stream.read(2)
                    if len(length_data) != 2:
                        raise FormatError("Truncated BA2 filename table")
                    length = struct.unpack("<H", length_data)[0]
                    encoded = stream.read(length)
                    if len(encoded) != length:
                        raise FormatError("Truncated BA2 filename")
                    entry.name = encoded.decode("utf-8", errors="replace")

        return cls(
            archive_path,
            version=version,
            compression=compression,
            entries=entries,
        )

    def _read_chunk(self, stream: io.BufferedReader, chunk: Ba2TextureChunk) -> bytes:
        stream.seek(chunk.offset)
        stored_size = chunk.packed_size or chunk.unpacked_size
        payload = stream.read(stored_size)
        if len(payload) != stored_size:
            raise FormatError("Truncated BA2 texture data")
        if not chunk.packed_size:
            return payload
        try:
            payload = (
                _lz4_block(payload, chunk.unpacked_size)
                if self.compression == "lz4"
                else zlib.decompress(payload)
            )
        except zlib.error as exc:
            raise FormatError(f"Unable to decompress BA2 texture: {exc}") from exc
        if len(payload) != chunk.unpacked_size:
            raise FormatError("Decompressed BA2 texture size mismatch")
        return payload

    @staticmethod
    def _dds_header(entry: Ba2TextureEntry) -> bytes:
        block_size = _BC_BLOCK_BYTES.get(entry.dxgi_format)
        pixel_size = _UNCOMPRESSED_BYTES.get(entry.dxgi_format)
        if block_size is None and pixel_size is None:
            raise FormatError(
                f"Unsupported DXGI texture format {entry.dxgi_format} in {entry.name}"
            )
        if block_size is not None:
            pitch_or_linear_size = (
                max(1, (entry.width + 3) // 4)
                * max(1, (entry.height + 3) // 4)
                * block_size
            )
            flags = 0x000A1007
        else:
            assert pixel_size is not None
            pitch_or_linear_size = entry.width * pixel_size
            flags = 0x0002100F
        mip_count = max(1, entry.mip_count)
        caps = 0x00001000
        if mip_count > 1:
            caps |= 0x00400008
        header = struct.pack(
            "<I6I11I",
            124,
            flags,
            entry.height,
            entry.width,
            pitch_or_linear_size,
            0,
            mip_count,
            *([0] * 11),
        )
        pixel_format = struct.pack(
            "<II4s5I", 32, 0x00000004, b"DX10", 0, 0, 0, 0, 0
        )
        caps_fields = struct.pack("<5I", caps, 0, 0, 0, 0)
        dx10 = struct.pack("<5I", entry.dxgi_format, 3, 0, 1, 0)
        return b"DDS " + header + pixel_format + caps_fields + dx10

    @staticmethod
    def _destination(output: Path, name: str) -> Path:
        normalized = name.replace("\\", "/")
        if normalized.startswith("/"):
            raise FormatError(f"Unsafe absolute BA2 texture path: {name}")
        parts = [part for part in normalized.split("/") if part not in {"", "."}]
        if not parts or any(part == ".." or ":" in part for part in parts):
            raise FormatError(f"Unsafe BA2 texture path: {name}")
        return output.joinpath(*parts)

    def extract_all(
        self,
        output: str | Path,
        *,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> list[Path]:
        output_root = Path(output)
        written: list[Path] = []
        with self.path.open("rb") as stream:
            for index, entry in enumerate(self.entries, 1):
                destination = self._destination(output_root, entry.name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                payload = b"".join(
                    self._read_chunk(stream, chunk) for chunk in entry.chunks
                )
                destination.write_bytes(self._dds_header(entry) + payload)
                written.append(destination)
                if progress:
                    progress(index, len(self.entries), entry.name)
        return written
