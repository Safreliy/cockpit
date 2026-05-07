param(
  [int]$Clients = 24,
  [int]$Jobs = 4,
  [int]$Seconds = 180,
  [string]$Mode = "mixed"
)

$ErrorActionPreference = "Stop"
$compose = Join-Path $PSScriptRoot "..\docker-compose.yml"

if ($Mode -eq "readonly") {
  docker compose -f $compose exec -T postgres pgbench -S -c $Clients -j $Jobs -T $Seconds -P 10 -U cockpit cockpit
} else {
  docker compose -f $compose exec -T postgres pgbench -c $Clients -j $Jobs -T $Seconds -P 10 -U cockpit cockpit
}
