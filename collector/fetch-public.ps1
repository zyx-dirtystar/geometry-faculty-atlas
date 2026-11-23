param([Parameter(Mandatory = $true)][string]$Url, [ValidateSet('text/html','application/json')][string]$MediaType = 'text/html')

$ErrorActionPreference = 'Stop'
$atlasUri = [Uri]$Url
if ($atlasUri.Scheme -ne 'https' -or $atlasUri.UserInfo) {
    throw 'Use a public HTTPS URL.'
}
$atlasResponse = Invoke-WebRequest -Uri $atlasUri -Headers @{'Accept' = $MediaType} -TimeoutSec 16 -UseBasicParsing
if ($atlasResponse.Headers['Content-Type'] -notlike "*$MediaType*" -or $atlasResponse.RawContentLength -gt 5000000) {
    throw 'Directory response must match the expected public content type and fit under 5 MB.'
}
$atlasFinal = $atlasResponse.BaseResponse.RequestMessage.RequestUri
if (-not $atlasFinal) { $atlasFinal = $atlasResponse.BaseResponse.ResponseUri }
if (-not $atlasFinal -or $atlasFinal.Scheme -ne 'https') {
    throw 'Directory response must use HTTPS.'
}
$atlasBytes = $atlasResponse.Content
if ($atlasBytes -isnot [byte[]]) { $atlasBytes = [Text.Encoding]::UTF8.GetBytes($atlasResponse.Content) }
@{url=$atlasFinal.AbsoluteUri;html=[Convert]::ToBase64String($atlasBytes)} | ConvertTo-Json -Compress
