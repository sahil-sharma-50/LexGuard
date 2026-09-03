$ErrorActionPreference = 'Stop'
$verificationExitCode = 0
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$CommandArguments
    )

    Write-Host "`n> $Command $($CommandArguments -join ' ')"
    & $Command @CommandArguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and $script:verificationExitCode -eq 0) {
        $script:verificationExitCode = $exitCode
    }
}

# Keep each verification run's pytest files inside a fresh, resolved directory
# in the checkout. A unique run directory avoids reusing ACL-locked leftovers
# such as .tmp\pytest\pytest-of-sahil from an earlier managed run.
$pytestTempParent = Join-Path $workspaceRoot '.tmp\pytest-runs'
New-Item -ItemType Directory -Force -Path $pytestTempParent | Out-Null
$pytestTempRoot = Join-Path $pytestTempParent ("run-{0}" -f ([Guid]::NewGuid().ToString('N')))
New-Item -ItemType Directory -Path $pytestTempRoot | Out-Null
$pytestTempRoot = (Resolve-Path -LiteralPath $pytestTempRoot).Path
$env:TMP = $pytestTempRoot
$env:TEMP = $pytestTempRoot
$env:TMPDIR = $pytestTempRoot

Push-Location (Join-Path $workspaceRoot 'agent')
try {
    Invoke-NativeChecked python -m ruff check .
    Invoke-NativeChecked python -m mypy src
    Invoke-NativeChecked python -m pytest
}
finally {
    Pop-Location
}

Push-Location (Join-Path $workspaceRoot 'web')
try {
    # On Windows pnpm is commonly exposed as pnpm.ps1, which can be blocked by
    # execution policy. Prefer the executable shim while retaining a node-only
    # fallback for clean environments.
    $pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $pnpm) {
        $pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
    }
    if ($null -ne $pnpm) {
        $pnpmCommand = $pnpm.Source
        Invoke-NativeChecked $pnpmCommand run verify:fonts
        Invoke-NativeChecked $pnpmCommand lint
        Invoke-NativeChecked $pnpmCommand test --run
        Invoke-NativeChecked $pnpmCommand build
    }
    else {
        $node = Get-Command node -ErrorAction Stop
        $nodeCommand = $node.Source
        $localCommands = @(
            @('scripts/verify-fonts.mjs'),
            @('node_modules/typescript/bin/tsc', '--noEmit'),
            @('node_modules/vitest/vitest.mjs', 'run', '--passWithNoTests'),
            @('node_modules/next/dist/bin/next', 'build')
        )
        foreach ($localCommand in $localCommands) {
            $entrypointPath = Join-Path (Get-Location) $localCommand[0]
            if (-not (Test-Path -LiteralPath $entrypointPath -PathType Leaf)) {
                throw "Web dependencies are missing; expected $entrypointPath"
            }
            $nodeArguments = @($localCommand[0])
            if ($localCommand.Length -gt 1) {
                $nodeArguments += $localCommand[1..($localCommand.Length - 1)]
            }
            Invoke-NativeChecked $nodeCommand @nodeArguments
        }
    }
}
finally {
    Pop-Location
}

# Scan tracked and untracked source/docs. Keep local .env variants, generated
# directories, and binary content out of the signal while covering common
# cloud/package/token formats and long credential assignments.
$secretPattern = 'AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{20,}|npm_[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_-]?key|secret[_-]?key|access[_-]?token|private[_-]?key|password)\s*[:=]\s*["'']?[A-Za-z0-9+/=_-]{24,}'
$secretPathspecs = @(
    'agent/src/**', 'agent/tests/**', 'web/src/**', 'web/tests/**',
    'docs/**', 'scripts/**', 'README.md'
)
$secretFiles = @(git -C $workspaceRoot -c core.excludesFile= ls-files --cached --others --exclude-standard -- $secretPathspecs 2>$null | Where-Object {
    $_ -and $_ -notmatch '(^|[\\/])\.env(?:\.|$)' -and $_ -match '\.(py|pyi|ts|tsx|js|jsx|json|md|ps1|toml|yaml|yml|txt)$'
})
$secretHits = @()
if ($secretFiles.Count -gt 0) {
    $absoluteSecretFiles = @($secretFiles | ForEach-Object { Join-Path $workspaceRoot $_ })
    $secretHits = @(Select-String -LiteralPath $absoluteSecretFiles -Pattern $secretPattern -AllMatches -ErrorAction SilentlyContinue)
}
if ($secretHits.Count -gt 0) {
    Write-Error "Potential secret material found in tracked files:`n$($secretHits -join "`n")"
    if ($verificationExitCode -eq 0) { $verificationExitCode = 1 }
}

if ($verificationExitCode -ne 0) {
    exit $verificationExitCode
}

Write-Host "`nVerification completed successfully."
