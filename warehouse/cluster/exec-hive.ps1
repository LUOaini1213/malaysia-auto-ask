param([Parameter(Mandatory=$true)][string]$SqlPath, [string]$Distribution = 'Ubuntu-24.04')
$ErrorActionPreference = 'Stop'
$warehouseRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$fullPath = (Resolve-Path -LiteralPath $SqlPath).Path
if (-not $fullPath.StartsWith($warehouseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'SQL must be inside this project warehouse directory' }
$relative = $fullPath.Substring($warehouseRoot.Length + 1).Replace('\','/')
$scriptPath = (Join-Path $PSScriptRoot 'exec-hive.sh').Replace('\','/')
$linuxPath = (& wsl.exe -d $Distribution -- wslpath -a $scriptPath).Trim()
if ($LASTEXITCODE -ne 0) { throw 'wslpath failed' }
& wsl.exe -d $Distribution -- bash $linuxPath ('/warehouse/' + $relative)
if ($LASTEXITCODE -ne 0) { throw 'Hive query failed' }
