[CmdletBinding()]
param(
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRoot = Join-Path $scriptRoot "src"
$entryPoint = Join-Path $scriptRoot "bme_app.py"
$iconIco = Join-Path $scriptRoot "assets\bme-app.ico"
$iconPng = Join-Path $scriptRoot "assets\bme-icon.png"
$distPath = Join-Path $scriptRoot "dist"
$workPath = Join-Path $scriptRoot "build\pyinstaller"
$specPath = Join-Path $scriptRoot "build"
$exePath = Join-Path $distPath "BME.exe"

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw "Python was not found on PATH. Install Python 3.11 or newer."
}
$pythonExe = $pythonCommand.Source

foreach ($requiredPath in @($sourceRoot, $entryPoint, $iconIco, $iconPng)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required build input was not found: $requiredPath"
    }
}

function Invoke-Python {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    & $pythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

Push-Location $scriptRoot
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = if ($previousPythonPath) {
        "$sourceRoot;$previousPythonPath"
    }
    else {
        $sourceRoot
    }

    & $pythonExe -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed. Run: python -m pip install --upgrade pyinstaller"
    }

    if (-not $SkipTests) {
        Write-Host "Running tests..."
        Invoke-Python -Arguments @(
            "-m", "unittest", "discover", "-s", "tests", "-v"
        )
    }

    if (Test-Path -LiteralPath $exePath) {
        try {
            $stream = [System.IO.File]::Open(
                $exePath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
            $stream.Dispose()
        }
        catch {
            throw "BME.exe is in use. Close the running application and try again."
        }
    }

    Write-Host "Building BME.exe..."
    Invoke-Python -Arguments @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "BME",
        "--icon", $iconIco,
        "--add-data", "$iconPng;assets",
        "--paths", $sourceRoot,
        "--distpath", $distPath,
        "--workpath", $workPath,
        "--specpath", $specPath,
        $entryPoint
    )

    Copy-Item -LiteralPath (Join-Path $scriptRoot "LICENSE") `
        -Destination (Join-Path $distPath "LICENSE") -Force
    Copy-Item -LiteralPath (Join-Path $scriptRoot "COPYRIGHT") `
        -Destination (Join-Path $distPath "COPYRIGHT") -Force

    Write-Host "Build complete: $exePath" -ForegroundColor Green
}
finally {
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $previousPythonPath
    }
    Pop-Location
}
