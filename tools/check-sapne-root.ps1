<#
.SYNOPSIS
    Fail if the retired Sapne projects root re-enters tracked trees.

.DESCRIPTION
    Scans scripts/, docs/, tools/, and common config paths (config.example.toml,
    config.toml, .env, .env.example, .github/). Missing optional paths are
    skipped. A present file that cannot be read fails the run.

    The retired root is NOT written in this file. Pass it with -RetiredRoot or
    the SAPNE_RETIRED_ROOT environment variable (CI sets it). If neither is set
    the script fails (exit 2): an unconfigured check never passes silently.

    A hit is the retired root in any case, with one or more slashes or
    backslashes between its parts (so a doubled backslash also matches), and
    not preceded or followed by a letter or digit. A longer path that merely
    ends in the same folder name is not a hit.

    Line allowlist: a line is ignored only when that same line is an explicit
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

    File allowlist: if tools/sapne-root-allow.txt exists, every repo-relative
    path it lists is skipped. One path per line; '#' starts a comment; blank
    lines are ignored. Paths are normalised to forward slashes and matched
    exactly (case-sensitive, no globs). A missing allow file changes nothing.
    An allow file that exists but cannot be read fails the run (exit 2).

.PARAMETER RepoRoot
    Repository root. Defaults to the parent of this script.

.PARAMETER RetiredRoot
    The retired projects root to search for. Overrides SAPNE_RETIRED_ROOT.

.PARAMETER Fixture
    Extra file or directory scanned in addition to the repo. A fixture that
    contains the retired path must make this script exit non-zero.

.EXAMPLE
    pwsh -File tools/check-sapne-root.ps1 -RetiredRoot '<retired root>'

.EXAMPLE
    $env:SAPNE_RETIRED_ROOT = '<retired root>'; pwsh -File tools/check-sapne-root.ps1 -Fixture ./bad.md
#>

[CmdletBinding()]
param(
    [string] $RepoRoot,
    [string] $RetiredRoot,
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

if (-not $RetiredRoot) { $RetiredRoot = $env:SAPNE_RETIRED_ROOT }
$parts = @()
if ($RetiredRoot) { $parts = @($RetiredRoot.Trim() -split '[\\/]+' | Where-Object { $_ -ne '' }) }
if ($parts.Count -eq 0) {
    [Console]::Error.WriteLine('check-sapne-root: FAIL (not configured)')
    [Console]::Error.WriteLine('Set -RetiredRoot or SAPNE_RETIRED_ROOT to the retired projects root.')
    exit 2
}

# Same phrases as the comment-based help. Keep the two lists in step.
$Allow = [regex]::new('(?i)(retired\s+path|\bis\s+retired\b|\bare\s+retired\b|\bwas\s+retired\b|\bquarantine\b|do not use|don''t use)')

# Retired root, built from the configured value: parts joined by 1+ slashes.
$escaped = $parts | ForEach-Object { [regex]::Escape($_) }
$Bare = [regex]::new('(?i)(?<![A-Za-z0-9])' + ($escaped -join '[\\/]+') + '(?![A-Za-z0-9])')

# Optional file allowlist: repo-relative paths, forward slashes, exact match.
$AllowFiles = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$allowPath = Join-Path (Join-Path $RepoRoot 'tools') 'sapne-root-allow.txt'
if (Test-Path -LiteralPath $allowPath) {
    try {
        $allowLines = [System.IO.File]::ReadAllLines($allowPath)
    } catch {
        [Console]::Error.WriteLine("check-sapne-root: cannot read allow file: $($_.Exception.Message)")
        exit 2
    }
    foreach ($raw in $allowLines) {
        $entry = ($raw -replace '#.*$', '').Trim()
        if ($entry -eq '') { continue }
        $entry = ($entry -replace '\\', '/') -replace '^\./', ''
        [void] $AllowFiles.Add($entry)
    }
}

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
$skippedAllowed = 0
$rootPrefix = $RepoRoot.TrimEnd('\', '/')

foreach ($path in $files) {
    $display = $path
    $inRepo = $path.StartsWith($rootPrefix + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
    if ($inRepo) {
        $display = $path.Substring($rootPrefix.Length).TrimStart('\', '/')
    }
    $display = $display -replace '\\', '/'
    if ($inRepo -and $AllowFiles.Contains($display)) {
        $skippedAllowed++
        continue
    }

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
    [Console]::Error.WriteLine('The retired Sapne projects root re-entered the tree. Use the canonical root instead.')
    foreach ($hit in $hits) { [Console]::Error.WriteLine($hit) }
    [Console]::Error.WriteLine("$($hits.Count) hit(s). Only an explicit retired-path or quarantine line, or a file listed in tools/sapne-root-allow.txt, is allowlisted; see the comment-based help in this script.")
    exit 1
}

Write-Host "check-sapne-root: ok ($scanned text files, $allowHits allowlisted line(s), $skippedAllowed allowlisted file(s), $skippedBinary binary skipped)"
exit 0
