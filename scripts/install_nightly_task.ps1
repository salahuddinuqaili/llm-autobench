<#
.SYNOPSIS
  (Re)register the llm-autobench nightly scheduled task onto pythonw + nightly.py.

.DESCRIPTION
  Durable installer so the nightly task cannot silently regress onto python.exe
  or a uv-managed interpreter that lacks the project venv (PyYAML).

  Target (repo-relative; no secrets in the task XML):
    Name:    llm-autobench nightly (salahuddin)
    Run:     <repo>\.venv\Scripts\pythonw.exe
             pythonw, not python — a console host on the task would flash, and
             closing it kills the run. See scripts/procutil.py.
    Args:    <repo>\scripts\nightly.py
    Start in:<repo>
    When:    daily 21:00 local
    Logon:   InteractiveToken (run only when the user is logged on)
    Run as:  the user who invokes this script
    Secrets: none. NVIDIA_API_KEY is resolved at runtime by the pipeline
             (typically %LOCALAPPDATA%\llm-autobench\.env). Never embed keys.

  Idempotent: if Command, Arguments, daily-21:00 trigger, interactive logon,
  and Enabled already match, this is a no-op (exit 0). WorkingDirectory is
  set on create/update; an empty Start-In on an otherwise-correct task is
  tolerated because nightly.py locates the repo from __file__.

  Pass -Force to rewrite even when the core fields already match.
  Pass -DryRun to print the verdict without calling Register-ScheduledTask.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install_nightly_task.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "llm-autobench nightly (salahuddin)",
    [switch]$Force,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    if (-not $PSScriptRoot) {
        throw "PSScriptRoot is empty; run this file, do not pipe it."
    }
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-NormalizedPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    $trimmed = $Path.Trim().Trim('"')
    try {
        return [System.IO.Path]::GetFullPath($trimmed)
    } catch {
        return $trimmed
    }
}

function Get-CurrentUserSid {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
}

function Test-RunsAsCurrentUser([string]$UserId) {
    if ([string]::IsNullOrWhiteSpace($UserId)) { return $false }
    $sid = Get-CurrentUserSid
    $name = $env:USERNAME
    if ($UserId -eq $sid) { return $true }
    if ($UserId -eq $name) { return $true }
    if ($UserId -like "*\$name") { return $true }
    return $false
}

function Get-TriggerHourMinute($Trigger) {
    $raw = [string]$Trigger.StartBoundary
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    # StartBoundary looks like 2026-09-08T21:00:00+02:00 or 2026-09-08T21:00:00
    $tIndex = $raw.IndexOf("T")
    if ($tIndex -lt 0) { return $null }
    $timePart = $raw.Substring($tIndex + 1)
    foreach ($sep in @("+", "Z", "-")) {
        # timezone offset after HH:MM:SS — only split offset, not the date
        if ($sep -eq "-" -and $timePart.Length -ge 9) {
            $maybe = $timePart.Substring(8, 1)
            if ($maybe -eq "-") {
                $timePart = $timePart.Substring(0, 8)
                break
            }
        }
        $cut = $timePart.IndexOf($sep)
        if ($cut -gt 0) {
            $timePart = $timePart.Substring(0, $cut)
            break
        }
    }
    $bits = $timePart.Split(":")
    if ($bits.Count -lt 2) { return $null }
    return @{ Hour = [int]$bits[0]; Minute = [int]$bits[1] }
}

function Test-IsDailyTrigger($Trigger) {
    $cls = $Trigger.CimClass.CimClassName
    if ($cls -notmatch "Daily") { return $false }
    $interval = 1
    try { $interval = [int]$Trigger.DaysInterval } catch { $interval = 1 }
    return $interval -eq 1
}

function Get-Desired {
    $repo = Get-RepoRoot
    $pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
    $nightly = Join-Path $repo "scripts\nightly.py"
    return [pscustomobject]@{
        Repo     = $repo
        Pythonw  = $pythonw
        Nightly  = $nightly
        Description = "Nightly llm-autobench: pythonw + scripts/nightly.py. No secrets in this task; NVIDIA_API_KEY is read at runtime."
    }
}

function Get-Mismatch($Task, $Desired) {
    $reasons = New-Object System.Collections.Generic.List[string]
    if ($null -eq $Task) {
        $reasons.Add("task does not exist")
        return $reasons
    }
    if ($Task.State -eq "Disabled") {
        $reasons.Add("task is Disabled")
    }
    $action = @($Task.Actions)[0]
    if ($null -eq $action) {
        $reasons.Add("no Exec action")
        return $reasons
    }
    $cmd = Get-NormalizedPath $action.Execute
    $arg = Get-NormalizedPath $action.Arguments
    $wantCmd = Get-NormalizedPath $Desired.Pythonw
    $wantArg = Get-NormalizedPath $Desired.Nightly
    if ($cmd -ne $wantCmd) {
        $reasons.Add("Command is '$($action.Execute)' (want pythonw $wantCmd)")
    }
    if ($arg -ne $wantArg) {
        $reasons.Add("Arguments is '$($action.Arguments)' (want $wantArg)")
    }
    $wd = Get-NormalizedPath $action.WorkingDirectory
    # Empty Start-In is tolerated: nightly.py resolves REPO from __file__.
    # -Force rewrites it. A *wrong* WorkingDirectory is a mismatch.
    if ($wd -and ($wd -ne (Get-NormalizedPath $Desired.Repo))) {
        $reasons.Add("WorkingDirectory is '$($action.WorkingDirectory)' (want $($Desired.Repo))")
    }
    $trigger = @($Task.Triggers)[0]
    if ($null -eq $trigger) {
        $reasons.Add("no trigger")
    } else {
        if (-not (Test-IsDailyTrigger $trigger)) {
            $reasons.Add("trigger is not daily (class $($trigger.CimClass.CimClassName))")
        }
        $hm = Get-TriggerHourMinute $trigger
        if ($null -eq $hm -or $hm.Hour -ne 21 -or $hm.Minute -ne 0) {
            $reasons.Add("trigger time is '$($trigger.StartBoundary)' (want 21:00)")
        }
    }
    $logon = [string]$Task.Principal.LogonType
    if ($logon -notmatch "Interactive") {
        $reasons.Add("LogonType is '$logon' (want InteractiveToken)")
    }
    if (-not (Test-RunsAsCurrentUser $Task.Principal.UserId)) {
        $reasons.Add("UserId is '$($Task.Principal.UserId)' (want current user $($env:USERNAME))")
    }
    return $reasons
}

function Register-NightlyTask($Desired) {
    $action = New-ScheduledTaskAction `
        -Execute $Desired.Pythonw `
        -Argument $Desired.Nightly `
        -WorkingDirectory $Desired.Repo
    $trigger = New-ScheduledTaskTrigger -Daily -At "21:00"
    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries:$false `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -DontStopOnIdleEnd
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description $Desired.Description `
        -Force | Out-Null
}

Import-Module ScheduledTasks -ErrorAction Stop

$desired = Get-Desired

if (-not (Test-Path -LiteralPath $desired.Pythonw)) {
    throw "pythonw not found: $($desired.Pythonw)  (create the project venv first)"
}
if (-not (Test-Path -LiteralPath $desired.Nightly)) {
    throw "nightly.py not found: $($desired.Nightly)"
}

Write-Host "repo:    $($desired.Repo)"
Write-Host "pythonw: $($desired.Pythonw)"
Write-Host "script:  $($desired.Nightly)"
Write-Host "task:    $TaskName"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$reasons = @(Get-Mismatch $existing $desired)

if (-not $Force -and $reasons.Count -eq 0) {
    Write-Host "already correct - skipping Register-ScheduledTask (pass -Force to rewrite, including WorkingDirectory)."
    exit 0
}

if ($reasons.Count -gt 0) {
    Write-Host "mismatch:"
    foreach ($r in $reasons) { Write-Host "  - $r" }
} else {
    Write-Host "-Force: rewriting an already-correct task."
}

if ($DryRun) {
    Write-Host "DryRun: not calling Register-ScheduledTask."
    exit 0
}

Register-NightlyTask $desired

$after = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$afterReasons = @(Get-Mismatch $after $desired)
if ($afterReasons.Count -gt 0) {
    Write-Host "ERROR: task still mismatches after register:"
    foreach ($r in $afterReasons) { Write-Host "  - $r" }
    exit 1
}

$act = @($after.Actions)[0]
Write-Host "registered:"
Write-Host "  Command:          $($act.Execute)"
Write-Host "  Arguments:        $($act.Arguments)"
Write-Host "  WorkingDirectory: $($act.WorkingDirectory)"
Write-Host "  LogonType:        $($after.Principal.LogonType)"
Write-Host "  UserId:           $($after.Principal.UserId)"
Write-Host "  State:            $($after.State)"
exit 0
