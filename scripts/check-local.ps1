[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$EnvFile = ".env"
)

# Read-only local preflight. Never prints environment variable values or credentials.
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $projectRoot
try {
    $failed = $false
    Write-Host "Lenny Growth Assistant local preflight" -ForegroundColor Cyan

    $pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        Write-Host "ERROR: Python '$Python' was not found. Activate the project virtual environment or pass -Python with its interpreter path." -ForegroundColor Red
        exit 1
    }
    $pythonVersion = & $Python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: The selected Python interpreter could not run." -ForegroundColor Red
        exit 1
    }
    Write-Host "OK: $pythonVersion" -ForegroundColor Green

    $modules = @(
        @{ Name = "fastapi"; Package = "fastapi" },
        @{ Name = "uvicorn"; Package = "uvicorn" },
        @{ Name = "pydantic_settings"; Package = "pydantic-settings" },
        @{ Name = "sqlalchemy"; Package = "sqlalchemy" },
        @{ Name = "psycopg"; Package = "psycopg[binary]" },
        @{ Name = "alembic"; Package = "alembic" },
        @{ Name = "chromadb"; Package = "chromadb" },
        @{ Name = "claude_agent_sdk"; Package = "claude-agent-sdk" }
    )
    $moduleCheck = "import importlib.util,json; print(json.dumps({" + (($modules | ForEach-Object { "'$($_.Name)': bool(importlib.util.find_spec('$($_.Name)'))" }) -join ",") + "}))"
    $moduleOutput = & $Python -c $moduleCheck 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Could not inspect required backend packages." -ForegroundColor Red
        exit 1
    }
    $moduleState = $moduleOutput | ConvertFrom-Json
    foreach ($dependency in $modules) {
        if ($moduleState.($dependency.Name)) {
            Write-Host "OK: Python package $($dependency.Package)" -ForegroundColor Green
        } else {
            Write-Host "ERROR: Missing Python package $($dependency.Package)" -ForegroundColor Red
            $failed = $true
        }
    }
    if (@($modules | Where-Object { -not $moduleState.($_.Name) }).Count -gt 0) {
        Write-Host "Install backend packages from the project root: python -m pip install -r backend/requirements.txt" -ForegroundColor Yellow
    }

    $ollamaBaseUrl = "http://localhost:11434"
    $llmModel = "llama3:latest"
    $embeddingModel = "nomic-embed-text"
    if (Test-Path -LiteralPath $EnvFile) {
        foreach ($line in Get-Content -LiteralPath $EnvFile) {
            if ($line -match '^\s*(OLLAMA_BASE_URL|OLLAMA_MODEL|OLLAMA_EMBEDDING_MODEL)\s*=\s*(.*?)\s*$') {
                $name = $Matches[1]
                $value = $Matches[2].Trim('"', "'")
                if ($name -eq "OLLAMA_BASE_URL" -and $value) { $ollamaBaseUrl = $value.TrimEnd('/') }
                if ($name -eq "OLLAMA_MODEL" -and $value) { $llmModel = $value }
                if ($name -eq "OLLAMA_EMBEDDING_MODEL" -and $value) { $embeddingModel = $value }
            }
        }
    } elseif (Test-Path -LiteralPath ".env.example") {
        Write-Host "WARNING: .env is absent; checking default Ollama model names." -ForegroundColor Yellow
    }

    try {
        $tags = Invoke-RestMethod -Uri "$ollamaBaseUrl/api/tags" -TimeoutSec 5
        $installedModels = @($tags.models | ForEach-Object { $_.name })
        foreach ($model in @($llmModel, $embeddingModel)) {
            if ($installedModels -contains $model) {
                Write-Host "OK: Configured Ollama model '$model' is installed" -ForegroundColor Green
            } else {
                $modelBase = ($model -split ':')[0]
                $installedMatch = $installedModels | Where-Object { ($_ -split ':')[0] -eq $modelBase } | Select-Object -First 1
                if ($installedMatch) {
                    Write-Host "ERROR: Configured Ollama tag '$model' is missing; found '$installedMatch' for the same model name." -ForegroundColor Red
                } else {
                    Write-Host "ERROR: Ollama model '$model' is missing. Run: ollama pull $model" -ForegroundColor Red
                }
                $failed = $true
            }
        }
    } catch {
        Write-Host "ERROR: Ollama is unreachable at the configured endpoint. Start Ollama and check OLLAMA_BASE_URL in .env." -ForegroundColor Red
        $failed = $true
    }

    $databaseUrl = $null
    if (Test-Path -LiteralPath $EnvFile) {
        foreach ($line in Get-Content -LiteralPath $EnvFile) {
            if ($line -match '^\s*DATABASE_URL\s*=\s*(.*?)\s*$') { $databaseUrl = $Matches[1].Trim('"', "'") }
        }
    }
    if (-not $databaseUrl) {
        # Application defaults are safe placeholders; avoid showing any URL.
        if ($Python) {
            $databaseConfigured = (& $Python -c "from app.core.config import get_settings; print(get_settings().effective_database_url)" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $databaseConfigured) { $databaseUrl = $databaseConfigured }
        }
    }
    if (-not $databaseUrl) {
        Write-Host "ERROR: DATABASE_URL is not configured in .env; the value is hidden." -ForegroundColor Red
        $failed = $true
    } else {
        try {
            $dbUri = [System.Uri]$databaseUrl
            if ($dbUri.Scheme -notin @("postgresql", "postgresql+psycopg", "postgres")) { throw "Not a PostgreSQL URL" }
            $dbHost = $dbUri.Host
            $dbPort = if ($dbUri.Port -gt 0) { $dbUri.Port } else { 5432 }
            if (-not $dbHost) { throw "Missing database host" }
            $tcp = Test-NetConnection -ComputerName $dbHost -Port $dbPort -WarningAction SilentlyContinue
            if ($tcp.TcpTestSucceeded) {
                Write-Host "OK: PostgreSQL TCP endpoint $dbHost`:$dbPort is reachable (credentials not checked)" -ForegroundColor Green
            } else {
                Write-Host "ERROR: PostgreSQL TCP endpoint $dbHost`:$dbPort is unreachable. Start PostgreSQL and check DATABASE_URL host/port." -ForegroundColor Red
                $failed = $true
            }
        } catch {
            Write-Host "ERROR: DATABASE_URL is not a parseable PostgreSQL URL; the value is hidden." -ForegroundColor Red
            $failed = $true
        }
    }

    if ($failed) {
        Write-Host "Preflight failed. Fix the reported items and rerun scripts\check-local.ps1." -ForegroundColor Red
        exit 1
    }
    Write-Host "Preflight passed. PostgreSQL credentials and application-level access still require migration/API verification." -ForegroundColor Green
    exit 0
} finally {
    Pop-Location
}
