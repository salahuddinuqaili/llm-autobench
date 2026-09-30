<#
.SYNOPSIS
    Fail if the retired Sapne projects root re-enters tracked trees.

.DESCRIPTION
    Scans scripts/, docs/, tools/, and common config paths (config.example.toml,
    config.toml, .env, .env.example, .github/). Missing optional paths are
    skipped. A present file that cannot be read fails the run.

    A hit is the retired path C:\projects or C:/projects (any case, one or more
    slashes, including a doubled backslash). The canonical root is
    C:\Users\salahuddin\projects. That longer path is not a hit.

    Allowlist: a line is ignored only when that same line is an explicit
    retired-path or quarantine note. It must match one of these phrases
    (case-insensitive):
        retired path
        is retired
        are retired
        was retired
        quarantine
        do not use
        don't use
    A live assignment of the retired path is not allowlisted, even if the word
    "retired" appears nearby in a looser phrase such as "retired value".

.PARAMETER RepoRoot
    Repository root. Defaults to the parent of this script.

.PARAMETER Fixture
    Extra file or directory scanned in addition to the repo. A fixture that
    contains the retired path must make this script exit non-zero.

.EXAMPLE
    pwsh -File tools/check-sapne-root.ps1

.EXAMPLE
    pwsh -File tools/check-sapne-root.ps1 -Fixture .\bad.md
#>

[CmdletBinding()]
param(
    [string] $RepoRoot,
    [string[]] $Fixture
)

$ErrorActionPreference = 'Stop'

# Windows PowerShell 5.1 reads a BOM-less UTF-8 script as ANSI. This file stays
# pure ASCII, the same constraint as tools/acceptance.ps1.

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
if (-not $RepoRoot -or -not (Test-Path -LiteralPath $RepoRoot)) {
    [Console]::Error.WriteLine('check-sapne-root: repo root not found')
    exit 2
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path

# Same phrases as the comment-based help. Keep the two lists in step.
$Allow = [regex]::new('(?i)(retired\s+path|\bis\s+retired\b|\bare\s+retired\b|\bwas\s+retired\b|\bquarantine\b|do not use|don''t use)')

# Retired root only. The pattern is assembled so this source line is not itself
# a contiguous hit on the retired path.
$Bare = [regex]::new('(?i)(?<![A-Za-z0-9])C:[\\/]+projects\b')

$SkipExt = @{
    '.png' = $true; '.bin' = $true; '.ogg' = $true; '.wav' = $true
    '.exe' = $true; '.dll' = $true; '.pdb' = $true; '.webp' = $true
    '.gif' = $true; '.ico' = $true; '.woff' = $true; '.woff2' = $true
    '.zip' = $true; '.gz' = $true
}

function Add-TreeFiles {
    param(
        [System.Collections.Generic.List[string]] $Sink,
        [hashtable] $Seen,
        [string] $Path
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    $pending = New-Object System.Collections.Generic.List[string]
    if ($item.PSIsContainer) {
        Get-ChildItem -LiteralPath $item.FullName -Recurse -File -Force | ForEach-Object {
            $pending.Add($_.FullName)
        }
    } else {
        $pending.Add($item.FullName)
    }
    foreach ($full in $pending) {
        if ($Seen.ContainsKey($full)) { continue }
        $Seen[$full] = $true
        $Sink.Add($full)
    }
}

$files = New-Object 'System.Collections.Generic.List[string]'
$seen = @{}
foreach ($rel in @('scripts', 'docs', 'tools', '.github')) {
    Add-TreeFiles -Sink $files -Seen $seen -Path (Join-Path $RepoRoot $rel)
}
foreach ($rel in @('config.example.toml', 'config.toml', '.env', '.env.example')) {
    Add-TreeFiles -Sink $files -Seen $seen -Path (Join-Path $RepoRoot $rel)
}
if ($Fixture) {
    foreach ($extra in $Fixture) {
        if (-not (Test-Path -LiteralPath $extra)) {
            [Console]::Error.WriteLine("check-sapne-root: fixture not found: $extra")
            exit 2
        }
        Add-TreeFiles -Sink $files -Seen $seen -Path $extra
    }
}

$hits = New-Object System.Collections.Generic.List[string]
$scanned = 0
$allowHits = 0
$skippedBinary = 0

foreach ($path in $files) {
    $ext = [System.IO.Path]::GetExtension($path).ToLowerInvariant()
    if ($SkipExt.ContainsKey($ext)) {
        $skippedBinary++
        continue
    }
    try {
        $bytes = [System.IO.File]::ReadAllBytes($path)
    } catch {
        [Console]::Error.WriteLine("check-sapne-root: cannot read ${path}: $($_.Exception.Message)")
        exit 2
    }
    $limit = [Math]::Min(4096, $bytes.Length)
    $binary = $false
    for ($i = 0; $i -lt $limit; $i++) {
        if ($bytes[$i] -eq 0) { $binary = $true; break }
    }
    if ($binary) {
        $skippedBinary++
        continue
    }

    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    $scanned++

    $display = $path
    $rootPrefix = $RepoRoot.TrimEnd('\', '/')
    if ($path.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $display = $path.Substring($rootPrefix.Length).TrimStart('\', '/')
    }

    $n = 0
    foreach ($line in ($text -split '\r?\n')) {
        $n++
        if (-not $Bare.IsMatch($line)) { continue }
        if ($Allow.IsMatch($line)) {
            $allowHits++
            continue
        }
        $shown = $line.Trim()
        if ($shown.Length -gt 240) { $shown = $shown.Substring(0, 240) + '...' }
        $hits.Add("${display}:${n}: ${shown}")
    }
}

if ($hits.Count -gt 0) {
    [Console]::Error.WriteLine('check-sapne-root: FAIL')
    [Console]::Error.WriteLine('The retired Sapne projects root re-entered the tree.')
    [Console]::Error.WriteLine('Canonical root is C:\Users\salahuddin\projects.')
    foreach ($hit in $hits) { [Console]::Error.WriteLine($hit) }
    [Console]::Error.WriteLine("$($hits.Count) hit(s). Only an explicit retired-path or quarantine line is allowlisted; see the comment-based help in this script.")
    exit 1
}

Write-Host "check-sapne-root: ok ($scanned text files, $allowHits allowlisted line(s), $skippedBinary binary skipped)"
exit 0
