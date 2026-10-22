[CmdletBinding()]
param(
    [ValidateSet('Offline', 'Check', 'Live')]
    [string]$Mode = 'Offline',
    [switch]$Check,
    [switch]$Live,
    [switch]$Group,
    [switch]$Delivery,
    [switch]$Reset,
    [switch]$RunTests
)

$ErrorActionPreference = 'Stop'

if ($Check -and $Live) {
    throw 'Choose one of -Check or -Live.'
}
if ($Check) { $Mode = 'Check' }
if ($Live) { $Mode = 'Live' }
if ($Reset -and $Mode -eq 'Check') {
    throw '-Reset cannot be combined with -Check.'
}
if ($RunTests -and $Mode -ne 'Offline') {
    throw '-RunTests is available only in Offline mode.'
}

$testRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $testRoot '..')).Path
$runtimeRoot = [IO.Path]::GetFullPath((Join-Path $testRoot 'runtime'))
$configPath = Join-Path $repoRoot 'config/config.yaml'
$seedPath = Join-Path $testRoot 'seed_phase5.py'

if ([IO.Path]::GetFileName($testRoot) -ne 'test') {
    throw 'The sandbox must remain in a directory named test.'
}
if (-not $runtimeRoot.StartsWith($testRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unsafe runtime path.'
}
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw 'Repository config/config.yaml is missing.'
}
if (-not (Test-Path -LiteralPath $seedPath -PathType Leaf)) {
    throw 'test/seed_phase5.py is missing.'
}

$pythonCommand = Get-Command python -ErrorAction Stop
$pythonPath = $pythonCommand.Path
$dbPath = Join-Path $runtimeRoot 'intelligence.db'
$savedLocation = (Get-Location).Path
$environmentNames = @(
    'PYTHONPATH',
    'INTELLIGENCE_DB_PATH',
    'INTELLIGENCE_ENABLED',
    'INTELLIGENCE_ASSISTANT_ENABLED',
    'LARK_ENABLED',
    'LARK_ALLOWED_CHAT_TYPES',
    'LARK_DELIVERY_ENABLED'
)
$savedEnvironment = @{}
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Set-TestEnvironment([string]$name, [string]$value) {
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
}

function Require-Environment([string[]]$names) {
    $missing = @()
    foreach ($name in $names) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if ([string]::IsNullOrWhiteSpace($value)) { $missing += $name }
    }
    if ($missing.Count -gt 0) {
        throw ('Missing required environment variables: ' + ($missing -join ', ') + '. Values are not printed.')
    }
}

function Assert-SafeRuntimeDirectory {
    if (Test-Path -LiteralPath $runtimeRoot) {
        $item = Get-Item -LiteralPath $runtimeRoot -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Refusing a reparse-point runtime directory.'
        }
        $resolved = (Resolve-Path -LiteralPath $runtimeRoot).Path
        if ($resolved -ne $runtimeRoot) { throw 'Runtime path resolution changed unexpectedly.' }
    }
}

try {
    Set-Location -LiteralPath $repoRoot
    $oldPythonPath = $savedEnvironment['PYTHONPATH']
    if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
        Set-TestEnvironment 'PYTHONPATH' $repoRoot
    } else {
        Set-TestEnvironment 'PYTHONPATH' ($repoRoot + ';' + $oldPythonPath)
    }

    if ($Reset) {
        if ($Mode -eq 'Live') { throw 'Use -Reset only before an Offline build.' }
        Assert-SafeRuntimeDirectory
        if (Test-Path -LiteralPath $runtimeRoot) {
            Remove-Item -LiteralPath $runtimeRoot -Recurse -Force
        }
    }

    if ($Mode -eq 'Check') {
        Set-TestEnvironment 'INTELLIGENCE_DB_PATH' $dbPath
        & $pythonPath -B -m trendradar.integrations.lark --config $configPath --check
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        exit 0
    }

    Assert-SafeRuntimeDirectory
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    Set-TestEnvironment 'INTELLIGENCE_DB_PATH' $dbPath
    Set-TestEnvironment 'INTELLIGENCE_ENABLED' 'true'
    Set-TestEnvironment 'INTELLIGENCE_ASSISTANT_ENABLED' 'true'

    if (Test-Path -LiteralPath $dbPath -PathType Leaf) {
        & $pythonPath -B $seedPath --db $dbPath --verify
    } else {
        & $pythonPath -B $seedPath --db $dbPath
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    if ($Mode -eq 'Offline') {
        Set-TestEnvironment 'LARK_ENABLED' 'false'
        Set-TestEnvironment 'LARK_DELIVERY_ENABLED' 'false'
        Set-TestEnvironment 'GEMINI_ENABLED' 'false'
        & $pythonPath -B -m trendradar.integrations.lark --config $configPath --check
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if ($RunTests) {
            & $pythonPath -B -m pytest tests/integrations/feishu tests/ai/test_media.py -q
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        Write-Host 'Phase 5 offline sandbox is ready. No provider was contacted.'
        exit 0
    }

    Require-Environment @('LARK_APP_ID', 'LARK_APP_SECRET', 'GEMINI_API_KEY', 'LARK_IDENTITY_FIELDS')
    Set-TestEnvironment 'LARK_ENABLED' 'true'
    Set-TestEnvironment 'GEMINI_ENABLED' 'true'
    Set-TestEnvironment 'LARK_ALLOWED_CHAT_TYPES' $(if ($Group) { 'p2p,group' } else { 'p2p' })
    if ($Group) { Require-Environment @('LARK_BOT_ID') }
    if ($Delivery) {
        Require-Environment @('LARK_DELIVERY_TARGET')
        Set-TestEnvironment 'LARK_DELIVERY_ENABLED' 'true'
    } else {
        Set-TestEnvironment 'LARK_DELIVERY_ENABLED' 'false'
    }

    & $pythonPath -B -m trendradar.integrations.lark --config $configPath --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host 'Starting the isolated Phase 5 runner. Press Ctrl+C to stop.'
    & $pythonPath -B -m trendradar.integrations.lark --config $configPath
    exit $LASTEXITCODE
} finally {
    Set-Location -LiteralPath $savedLocation
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
