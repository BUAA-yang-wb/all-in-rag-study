param()

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeDir = Join-Path $RepoRoot "course_rag\deploy\milvus"
$ComposeFile = Join-Path $ComposeDir "docker-compose.yml"

if (-not (Test-Path $ComposeFile)) {
    throw "Compose file not found: $ComposeFile"
}

function Invoke-NativeCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $ExitCode."
    }
}

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & docker info *> $null
    $DockerInfoExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
if ($DockerInfoExitCode -ne 0) {
    throw "Docker daemon is not available. Start Docker Desktop if you need to stop running Milvus containers."
}

Push-Location $ComposeDir
try {
    Invoke-NativeCommand -FilePath "docker" -Arguments @("compose", "-f", $ComposeFile, "down")
}
finally {
    Pop-Location
}
