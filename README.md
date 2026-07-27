![Bethesda Material Extractor icon](assets/bme-icon.png)

# Bethesda Material Extractor

**BME** discovers and exports Starfield materials and their paired textures.

---

## Overview

Bethesda Material Extractor is a lightweight Python desktop application for
working with Starfield BA2 archives.

- Discovers material paths automatically from a selected BA2 archive
- Exports material data while preserving game-relative paths
- Finds a matching `- Textures.ba2` or `- Texture.ba2` archive automatically
- Extracts paired textures as standard DDS files
- Provides both a graphical interface and command-line tools
- Requires no third-party runtime dependencies

## Quick start

> **Requirements:** Python 3.11 or newer and Windows for the desktop
> application or packaged executable.

Run BME directly from the project directory:

```powershell
.\run.ps1
```

Alternatively, install the project in editable mode and launch the package:

```powershell
python -m pip install -e .
python -m bme
```

### Desktop workflow

1. Select a `.ba2` material archive.
2. Review the material paths discovered from the archive.
3. Click **Export Materials + Textures** and choose an output directory.

For the base game, select the Materials BA2. For a Creation, select its Main
BA2. When a corresponding texture archive is present beside it, BME exports
the textures to the same destination automatically.

## Command-line interface

The optional CLI supports material-path discovery, CRC calculation, and batch
exports.

```powershell
# Show available commands
bme --help

# Calculate a material CRC
bme crc "Materials\Example\Surface.mat"

# Discover paths in an archive
bme paths "sfbgs00b - main.ba2"

# Export materials and paired textures
bme export --database "sfbgs00b - main.ba2" --output exported
```

Use `bme <command> --help` for command-specific options.

## Development

### Run the tests

```powershell
python -m unittest discover -s tests -v
```

### Build the Windows executable

Install PyInstaller:

```powershell
python -m pip install --upgrade pyinstaller
```

Build the single-file, windowed executable:

```powershell
.\build.ps1
```

The script validates the build inputs, runs the test suite, creates the EXE,
and copies the license files. Use `.\build.ps1 -SkipTests` to omit the tests
when they have already been run.

The finished distribution is written to `dist`:

| File | Purpose |
| --- | --- |
| `BME.exe` | Standalone Windows application |
| `LICENSE` | GNU GPL license text |
| `COPYRIGHT` | Copyright notice |

The `build` directory contains temporary PyInstaller files and can be removed
after a successful build.

### Automated releases

Pushes to `main` that change `src`, `assets`, or `tests` automatically build
and publish a Windows x64 GitHub Release. The release includes a ZIP containing
`BME.exe`, `LICENSE`, and `COPYRIGHT`, plus a SHA-256 checksum file. The workflow
uses the version in `pyproject.toml` for the release tag and title, so update
the version before publishing a new release. The workflow can also be started
manually from the repository's **Actions** page.

## Project layout

| Path | Description |
| --- | --- |
| `src/bme` | Application source package |
| `tests` | Unit tests |
| `assets` | Application icons |
| `bme_app.py` | PyInstaller entry point |
| `build.ps1` | Windows executable build script |
| `run.ps1` | Development launcher |

## License

Copyright (C) 2026 Wes Sitzes.

Bethesda Material Extractor is licensed under the GNU General Public License
version 3 or later (`GPL-3.0-or-later`). See [LICENSE](LICENSE).
