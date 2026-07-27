$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRoot = Join-Path $scriptRoot "src"
$previousPythonPath = $env:PYTHONPATH
Push-Location $scriptRoot
try {
    $env:PYTHONPATH = if ($previousPythonPath) {
        "$sourceRoot;$previousPythonPath"
    }
    else {
        $sourceRoot
    }
    python -m bme @args
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
