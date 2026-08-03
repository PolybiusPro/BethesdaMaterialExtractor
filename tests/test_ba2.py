from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from bme.ba2 import Ba2Archive, Ba2TextureArchive, _lz4_block
from bme.paths import discover_material_paths


def _make_ba2(path: Path, name: str, payload: bytes, *, compressed: bool) -> None:
    encoded_name = name.encode("utf-8")
    stored = zlib.compress(payload) if compressed else payload
    header_size = 24
    record_size = 12 + 4 + 20
    data_offset = header_size + record_size
    names_offset = data_offset + len(stored)
    header = struct.pack("<4sI4sIQ", b"BTDX", 1, b"GNRL", 1, names_offset)
    hash_record = struct.pack("<III", 1, 2, 3)
    file_record = struct.pack("<BBH", 0, 1, 0x10)
    chunk = struct.pack(
        "<QIII",
        data_offset,
        len(stored) if compressed else 0,
        len(payload),
        0xBAADF00D,
    )
    names = struct.pack("<H", len(encoded_name)) + encoded_name
    path.write_bytes(header + hash_record + file_record + chunk + stored + names)


def _make_texture_ba2(
    path: Path,
    name: str,
    payload: bytes,
    *,
    compressed: bool,
    dxgi_format: int = 80,
) -> None:
    encoded_name = name.encode("utf-8")
    stored = zlib.compress(payload) if compressed else payload
    header_size = 24
    record_size = 24
    chunk_size = 24
    data_offset = header_size + record_size + chunk_size
    names_offset = data_offset + len(stored)
    header = struct.pack("<4sI4sIQ", b"BTDX", 1, b"DX10", 1, names_offset)
    record = struct.pack(
        "<I4sIBBHHHBBH",
        1,
        b"dds\0",
        2,
        0,
        1,
        chunk_size,
        4,
        4,
        1,
        dxgi_format,
        0x0800,
    )
    chunk = struct.pack(
        "<QIIHHI",
        data_offset,
        len(stored) if compressed else 0,
        len(payload),
        0,
        0,
        0xBAADF00D,
    )
    names = struct.pack("<H", len(encoded_name)) + encoded_name
    path.write_bytes(header + record + chunk + stored + names)


class Lz4Tests(unittest.TestCase):
    def test_literal_only_block(self) -> None:
        raw = b"hello"
        encoded = bytes([len(raw) << 4]) + raw
        self.assertEqual(_lz4_block(encoded, len(raw)), raw)

    def test_match_copy(self) -> None:
        # Literal "abcd", then a 4-byte match at distance four.
        self.assertEqual(_lz4_block(b"\x40abcd\x04\x00", 8), b"abcdabcd")


class Ba2Tests(unittest.TestCase):
    def test_read_uncompressed_and_find_name(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / "test.ba2"
            _make_ba2(
                archive_path,
                "meshes/example.nif",
                b"Materials\\Example\\Surface.mat\0",
                compressed=False,
            )
            archive = Ba2Archive.open(archive_path)
            entry = archive.find("meshes/example.nif")
            self.assertIsNotNone(entry)
            self.assertEqual(
                archive.read(entry),  # type: ignore[arg-type]
                b"Materials\\Example\\Surface.mat\0",
            )
            self.assertEqual(
                discover_material_paths([archive_path]),
                [r"Materials\Example\Surface.mat"],
            )

    def test_read_zlib_compressed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / "test.ba2"
            payload = b"nif payload" * 20
            _make_ba2(
                archive_path, "meshes/example.nif", payload, compressed=True
            )
            archive = Ba2Archive.open(archive_path)
            self.assertEqual(archive.read(archive.entries[0]), payload)

    def test_extract_dx10_texture_as_dds(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive_path = root / "Example - Textures.ba2"
            payload = bytes(range(8))
            _make_texture_ba2(
                archive_path,
                "textures/example.dds",
                payload,
                compressed=True,
            )

            archive = Ba2TextureArchive.open(archive_path)
            written = archive.extract_all(root / "output")

            destination = root / "output" / "textures" / "example.dds"
            self.assertEqual(written, [destination])
            data = destination.read_bytes()
            self.assertEqual(data[:4], b"DDS ")
            self.assertEqual(struct.unpack_from("<I", data, 128)[0], 80)
            self.assertEqual(data[148:], payload)

    def test_extract_uncompressed_dx10_texture_as_dds(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive_path = root / "Example - Textures.ba2"
            payload = bytes(range(64))
            _make_texture_ba2(
                archive_path,
                "textures/lut.dds",
                payload,
                compressed=True,
                dxgi_format=28,
            )

            archive = Ba2TextureArchive.open(archive_path)
            destination = archive.extract_all(root / "output")[0]
            data = destination.read_bytes()

            flags = struct.unpack_from("<I", data, 8)[0]
            self.assertTrue(flags & 0x00000008)
            self.assertFalse(flags & 0x00080000)
            self.assertEqual(struct.unpack_from("<I", data, 20)[0], 16)
            self.assertEqual(struct.unpack_from("<I", data, 128)[0], 28)
            self.assertEqual(data[148:], payload)


if __name__ == "__main__":
    unittest.main()
