param(
  [int]$Scale = 20
)

$ErrorActionPreference = "Stop"
$compose = Join-Path $PSScriptRoot "..\docker-compose.yml"
docker compose -f $compose exec -T postgres pgbench -i -s $Scale -U cockpit cockpit
