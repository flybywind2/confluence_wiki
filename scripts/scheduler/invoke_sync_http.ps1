[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$AdminToken,

    [Parameter(Mandatory = $true)]
    [string]$Spaces,

    [int]$PauseSeconds = 75
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$trimmedBaseUrl = $BaseUrl.TrimEnd("/")
$spaceList = $Spaces -split "[,\s]+" | Where-Object { $_ }
$headers = @{
    "X-Admin-Token" = $AdminToken
    "Content-Type"  = "application/json"
}

for ($index = 0; $index -lt $spaceList.Count; $index++) {
    $space = $spaceList[$index]
    $uri = "$trimmedBaseUrl/admin/sync"
    $body = @{ space = $space } | ConvertTo-Json -Compress

    if ($PSCmdlet.ShouldProcess($space, "POST $uri")) {
        Write-Host "[scheduler] http sync start: $space"
        $response = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $body
        Write-Host "[scheduler] http sync done: $space -> mode=$($response.mode) pages=$($response.processed_pages)"
    }

    if ($index -lt ($spaceList.Count - 1)) {
        Write-Host "[scheduler] waiting $PauseSeconds seconds before next space"
        Start-Sleep -Seconds $PauseSeconds
    }
}
