from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bme.cli import main


class CliTests(unittest.TestCase):
    def test_crc_command(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["crc", r"Materials\Foo\Test.mat"])
        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue().strip(), "942081269")

    def test_paths_command(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "paths.txt"
            path.write_text("Materials/Foo/Test.mat\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["paths", str(path)])
            self.assertEqual(status, 0)
            self.assertEqual(output.getvalue().strip(), r"Materials\Foo\Test.mat")

    def test_export_main_archive_needs_no_redundant_input(self) -> None:
        output = io.StringIO()
        with mock.patch(
            "bme.cli.export_from_inputs", return_value=[Path("texture.dds")]
        ) as export, contextlib.redirect_stdout(output):
            status = main(
                [
                    "export",
                    "--database",
                    "Creation - Main.ba2",
                    "--output",
                    "exported",
                ]
            )

        self.assertEqual(status, 0)
        export.assert_called_once()
        self.assertEqual(export.call_args.args[:3], ("Creation - Main.ba2", "exported", []))


if __name__ == "__main__":
    unittest.main()
