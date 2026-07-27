"""Command-line interface for the Python implementation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .crc import material_crc
from .errors import BmeError
from .paths import discover_material_paths, sanitize_material_path
from .service import export_from_inputs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bme",
        description="Bethesda Material Extractor",
    )
    subparsers = parser.add_subparsers(dest="command")

    crc = subparsers.add_parser("crc", help="calculate a material ID")
    crc.add_argument("path", help="game-relative .mat path")

    paths = subparsers.add_parser(
        "paths", help="discover material paths in assets"
    )
    paths.add_argument("inputs", nargs="+", help="files or directories")

    export = subparsers.add_parser(
        "export", help="export materials and a paired texture BA2"
    )
    export.add_argument(
        "--database",
        "-d",
        required=True,
        help="materialsbeta.cdb, materials BA2, or Creation Main BA2",
    )
    export.add_argument("--output", "-o", required=True, help="output directory")
    export.add_argument(
        "--material",
        "-m",
        action="append",
        default=[],
        help="explicit material path; repeat for multiple paths",
    )
    export.add_argument(
        "inputs",
        nargs="*",
        help="NIF, text, plugin, BA2, .mat, or directory inputs",
    )

    subparsers.add_parser("gui", help="open the desktop application")
    return parser


def _progress(value: int, maximum: int, label: str) -> None:
    print(f"[{value}/{maximum}] {label}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command in {None, "gui"}:
        from .gui import run

        run()
        return 0
    try:
        if arguments.command == "crc":
            path = sanitize_material_path(arguments.path.strip())
            print(material_crc(path))
            return 0
        if arguments.command == "paths":
            for path in discover_material_paths(arguments.inputs):
                print(path)
            return 0
        if arguments.command == "export":
            written = export_from_inputs(
                arguments.database,
                arguments.output,
                arguments.inputs,
                explicit_materials=arguments.material,
                progress=_progress,
            )
            for path in written:
                print(path)
            if not written:
                print("No materials or paired textures were found.", file=sys.stderr)
                return 1
            return 0
    except (OSError, BmeError, ValueError) as exc:
        print(f"bme: {exc}", file=sys.stderr)
        return 1
    return 0
