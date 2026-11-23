param([Parameter(Mandatory = $true)][string]$Url)

$ErrorActionPreference = 'Stop'
$atlasUri = [Uri]$Url
if ($atlasUri.Scheme -ne 'https' -or $atlasUri.UserInfo) {
    throw 'Use a public HTTPS URL.'
}
$atlasResponse = Invoke-WebRequest -Uri $atlasUri -TimeoutSec 16 -UseBasicParsing
if ($atlasResponse.Headers['Content-Type'] -notlike '*text/html*' -or $atlasResponse.RawContentLength -gt 5000000) {
    throw 'Directory response must be an HTML page under 5 MB.'
}
$atlasFinal = $atlasResponse.BaseResponse.RequestMessage.RequestUri
if (-not $atlasFinal) { $atlasFinal = $atlasResponse.BaseResponse.ResponseUri }
if (-not $atlasFinal -or $atlasFinal.Scheme -ne 'https') {
    throw 'Directory response must use HTTPS.'
}
$atlasBytes = [Text.Encoding]::UTF8.GetBytes($atlasResponse.Content)
@{url=$atlasFinal.AbsoluteUri;html=[Convert]::ToBase64String($atlasBytes)} | ConvertTo-Json -Compress
