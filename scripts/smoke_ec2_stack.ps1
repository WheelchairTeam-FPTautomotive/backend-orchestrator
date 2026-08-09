# Smoke checks for locked one-EC2 stack (A5).
param(
  [string]$BaseUrl = "http://127.0.0.1"
)
$ErrorActionPreference = "Stop"
$BaseUrl = $BaseUrl.TrimEnd("/")

Write-Host "== Gateway health =="
Invoke-RestMethod -Uri "$BaseUrl`:8000/api/v1/health" | ConvertTo-Json -Compress

Write-Host "== Core health =="
Invoke-RestMethod -Uri "$BaseUrl`:8001/api/v1/health" | ConvertTo-Json -Compress

Write-Host "== VieNeu TCP 8022 =="
$hostOnly = $BaseUrl -replace '^https?://', ''
try {
  $tcp = Test-NetConnection -ComputerName $hostOnly -Port 8022 -WarningAction SilentlyContinue
  if ($tcp.TcpTestSucceeded) { Write-Host "8022 open" } else { Write-Host "8022 CLOSED (start vieneu.service)" }
} catch {
  Write-Host "VieNeu probe soft-fail: $_"
}

Write-Host "== Terraform validate =="
Push-Location (Join-Path $PSScriptRoot "..\terraform")
try {
  terraform validate
  Write-Host "Confirm enable_ecs=false enable_aoss=false in tfvars"
} finally {
  Pop-Location
}

Write-Host "Smoke complete."
