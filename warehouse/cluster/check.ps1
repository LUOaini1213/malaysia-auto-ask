param([string]$Distribution = 'Ubuntu-24.04')
$ErrorActionPreference = 'Stop'
$scriptPath = (Join-Path $PSScriptRoot 'check.sh').Replace('\','/')
$linuxPath = (& wsl.exe -d $Distribution -- wslpath -a $scriptPath).Trim()
if ($LASTEXITCODE -ne 0) { throw 'wslpath failed' }
& wsl.exe -d $Distribution -- bash $linuxPath
if ($LASTEXITCODE -ne 0) { throw 'Cluster acceptance failed' }
