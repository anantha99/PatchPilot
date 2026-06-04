param(
    [ValidateSet("test", "smoke", "live-eval", "shell")]
    [string] $Target = "test",

    [switch] $NoDocker
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$TempRoot = Join-Path $RepoRoot "tmp"
$PytestTemp = Join-Path $TempRoot "pytest"

New-Item -ItemType Directory -Force -Path $TempRoot, $PytestTemp | Out-Null

$env:TMP = $TempRoot
$env:TEMP = $TempRoot
$env:TMPDIR = $TempRoot
$env:PYTEST_DEBUG_TEMPROOT = $PytestTemp

function Test-DockerAvailable {
    if ($NoDocker) {
        return $false
    }

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        return $false
    }

    & docker compose version *> $null
    return $LASTEXITCODE -eq 0
}

if (Test-DockerAvailable) {
    switch ($Target) {
        "test" { & docker compose run --rm xarc-test }
        "smoke" { & docker compose run --rm xarc-smoke }
        "live-eval" { & docker compose run --rm xarc-live-eval }
        "shell" { & docker compose run --rm xarc-shell }
    }
    exit $LASTEXITCODE
}

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Docker is unavailable and local Python was not found at $Python. Install Docker Desktop or create the local .venv first."
}

switch ($Target) {
    "test" {
        & $Python -m pytest -q
    }
    "smoke" {
        & $Python -m patchpilot.cli eval --suite smoke --repo fixtures\buggy-python-repo --model-provider fake
    }
    "live-eval" {
        & $Python -m patchpilot.cli eval --suite smoke --repo fixtures\buggy-python-repo --live-eval
    }
    "shell" {
        & $Python
    }
}

exit $LASTEXITCODE
