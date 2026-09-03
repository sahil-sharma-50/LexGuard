param(
    [switch]$Foreground,
    [switch]$Down
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

if ($Down) {
    docker compose down
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath ".env")) {
    if (-not (Test-Path -LiteralPath ".env.example")) {
        throw "Missing .env.example; cannot create the environment file."
    }
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env. Edit it with your Alpaca paper keys and OpenAI key, then rerun this command."
    exit 1
}

Write-Host "Building and starting Lexguard (postgres, mcp, api, scheduler, web)..."
if ($Foreground) {
    docker compose up --build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker Compose could not start. Is Docker Desktop running?"
        exit $LASTEXITCODE
    }
    Write-Host ""
    Write-Host "Lexguard is starting:" -ForegroundColor Green
    Write-Host "  Web UI: http://localhost:3000"
    Write-Host "  API:    http://localhost:8000"
    Write-Host "  MCP:    http://localhost:8010/mcp"
    Write-Host ""
    Write-Host "Follow logs: docker compose logs -f"
    Write-Host "Stop stack:  .\run-docker.ps1 -Down"
}
