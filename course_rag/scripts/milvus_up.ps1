param(
    [string]$MilvusUri = "http://localhost:19530",
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeDir = Join-Path $RepoRoot "course_rag\deploy\milvus"
$ComposeFile = Join-Path $ComposeDir "docker-compose.yml"

function Assert-DockerDaemon {
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker info *> $null
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($ExitCode -ne 0) {
        throw "Docker daemon is not available. Start Docker Desktop, wait until it is running, then rerun this script."
    }
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

function Wait-Port {
    param(
        [string]$Uri,
        [int]$Timeout
    )

    $Parsed = [System.Uri]$Uri
    $HostName = $Parsed.Host
    $Port = $Parsed.Port
    $Deadline = (Get-Date).AddSeconds($Timeout)

    while ((Get-Date) -lt $Deadline) {
        $Client = New-Object System.Net.Sockets.TcpClient
        try {
            $Async = $Client.BeginConnect($HostName, $Port, $null, $null)
            if ($Async.AsyncWaitHandle.WaitOne(1000, $false)) {
                $Client.EndConnect($Async)
                Write-Host "Milvus port is reachable: $HostName`:$Port"
                return
            }
        }
        catch {
        }
        finally {
            $Client.Close()
        }
        Start-Sleep -Seconds 2
    }

    throw "Milvus port did not become reachable within $Timeout seconds: $Uri"
}

if (-not (Test-Path $ComposeFile)) {
    throw "Compose file not found: $ComposeFile"
}

Assert-DockerDaemon

Push-Location $ComposeDir
try {
    Invoke-NativeCommand -FilePath "docker" -Arguments @("compose", "-f", $ComposeFile, "up", "-d")

    Wait-Port -Uri $MilvusUri -Timeout $TimeoutSeconds
    Invoke-NativeCommand -FilePath "docker" -Arguments @("compose", "-f", $ComposeFile, "ps")
}
finally {
    Pop-Location
}
