[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [string]$Spaces,

    [string]$PythonExe = "python",

    [string]$AppRoot,

    [int]$PauseSeconds = 75
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $AppRoot) {
    $scriptRoot = Split-Path -Parent $PSCommandPath
    $AppRoot = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
}

$spaceList = $Spaces -split "[,\s]+" | Where-Object { $_ }

Push-Location $AppRoot
try {
    for ($index = 0; $index -lt $spaceList.Count; $index++) {
        $space = $spaceList[$index]
        $commandLine = "$PythonExe -m app.cli sync --space $space"

        if ($PSCmdlet.ShouldProcess($space, $commandLine)) {
            Write-Host "[scheduler] sync start: $space"
            & $PythonExe -m app.cli sync --space $space
            if ($LASTEXITCODE -ne 0) {
                throw "sync failed for space '$space' with exit code $LASTEXITCODE"
            }
            Write-Host "[scheduler] sync done: $space"
        }

        if ($index -lt ($spaceList.Count - 1)) {
            Write-Host "[scheduler] waiting $PauseSeconds seconds before next space"
            Start-Sleep -Seconds $PauseSeconds
        }
    }
}
finally {
    Pop-Location
}
