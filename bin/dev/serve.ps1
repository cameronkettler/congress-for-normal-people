param(
    [ValidateSet("up", "down", "restart", "status", "logs")]
    [string] $Command = "up",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Rest
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $Root

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found. Install/start Docker Desktop, then reopen PowerShell so docker is on PATH."
    }

    if (($Command -eq "up" -or $Command -eq "restart") -and -not (Test-Path -LiteralPath ".env")) {
        throw "Missing .env. Copy .env.example to .env before starting the stack."
    }

    switch ($Command) {
        "up" {
            docker compose up --build -d
            docker compose ps
        }
        "down" {
            docker compose down
        }
        "restart" {
            docker compose down
            docker compose up --build -d
            docker compose ps
        }
        "status" {
            docker compose ps
        }
        "logs" {
            docker compose logs -f @Rest
        }
    }
}
finally {
    Pop-Location
}
