from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bme.crc import material_crc, resource_id
from bme.paths import discover_material_paths, sanitize_material_path


class PathTests(unittest.TestCase):
    def test_sanitize_relative_and_absolute_paths(self) -> None:
        self.assertEqual(
            sanitize_material_path(r"Actors\Human\Body.mat"),
            r"Materials\Actors\Human\Body.mat",
        )
        self.assertEqual(
            sanitize_material_path(r"C:\Game\Data\Materials\Foo\Bar.mat"),
            r"Materials\Foo\Bar.mat",
        )
        self.assertEqual(
            sanitize_material_path("materials/foo/bar.mat"),
            r"materials\foo\bar.mat",
        )

    def test_text_discovery_is_case_insensitive_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "paths.txt"
            path.write_text(
                "Materials/Foo/A.mat\nmaterials\\foo\\a.MAT\nnot-an-asset.dds\n",
                encoding="utf-8",
            )
            self.assertEqual(
                discover_material_paths([path]), [r"Materials\Foo\A.mat"]
            )

    def test_nif_style_binary_strings_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.nif"
            path.write_bytes(
                b"\0noise\0Materials\\Actors\\Human\\Body.mat\0tail"
            )
            self.assertEqual(
                discover_material_paths([path]),
                [r"Materials\Actors\Human\Body.mat"],
            )


class CrcTests(unittest.TestCase):
    def test_crc_is_case_and_separator_insensitive(self) -> None:
        forward = material_crc("Materials/Foo/Test.mat")
        backward = material_crc(r"materials\foo\test.mat")
        self.assertEqual(forward, backward)
        self.assertEqual(forward, 942081269)

    def test_resource_id_components(self) -> None:
        identifier = resource_id(r"materials\foo\Test.mat")
        self.assertEqual(identifier.extension, 0x0074616D)
        self.assertEqual(str(identifier), "res:8C803A87:F93BA110:0074616D")


if __name__ == "__main__":
    unittest.main()
