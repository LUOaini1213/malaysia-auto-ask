param([string]$Distribution = 'Ubuntu-24.04')
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'start.sh'
$linuxPath = (& wsl.exe -d $Distribution -- wslpath -a $scriptPath.Replace('\','/')).Trim()
if ($LASTEXITCODE -ne 0) { throw 'wslpath failed' }
& wsl.exe -d $Distribution -- bash $linuxPath
if ($LASTEXITCODE -ne 0) { throw 'Cluster start failed' }
$containerStartedAt = (& wsl.exe -d $Distribution -- docker inspect --format '{{.State.StartedAt}}' malaysia-warehouse-cluster).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect project container start time' }
$containerGeneration = 'docker-start:' + $containerStartedAt
$artifactDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'artifacts/cluster'
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
$pidFile = Join-Path $artifactDir 'wsl-keepalive.json'
$keepAlive = $null
if (Test-Path -LiteralPath $pidFile) {
    try {
        $old = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        $candidate = Get-Process -Id $old.pid -ErrorAction Stop
        $expectedStart = ([datetime]$old.startUtc).ToUniversalTime()
        if (($candidate.ProcessName -eq 'wsl') -and ($candidate.StartTime.ToUniversalTime().Ticks -eq $expectedStart.Ticks) -and ([string]$old.containerGeneration -eq $containerGeneration)) { $keepAlive = $candidate }
    } catch { $keepAlive = $null }
}
if ($null -eq $keepAlive) {
    $keepAlive = Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d', $Distribution, '--', 'docker', 'wait', 'malaysia-warehouse-cluster') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $artifactDir 'wsl-keepalive.stdout.log') -RedirectStandardError (Join-Path $artifactDir 'wsl-keepalive.stderr.log')
    @{ pid=$keepAlive.Id; startUtc=$keepAlive.StartTime.ToUniversalTime().ToString('o'); container='malaysia-warehouse-cluster'; containerGeneration=$containerGeneration; purpose='Keep WSL alive until this project container stops' } | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
}
Write-Output ('WSL keepalive PID ' + $keepAlive.Id + '; exits automatically when this project container stops.')
