<#
    EU Intel site sync-and-push (idempotent)

    Rebuild articles.json, commit any changes, push to GitHub Pages.
    Safe to run repeatedly: if nothing changed, no commit is made.

    Called by:
    - eu-daily-report agent Step 5 (primary path)
    - eu-intel/scheduler.ps1 as a safety re-run after agent completes
      (ensures agent context-out / interruption does not leave site stale)

    Usage:
        .\eu-intel-site\sync-and-push.ps1
        .\eu-intel-site\sync-and-push.ps1 -CommitMessage "Update: add 2026-05-08"
#>

param(
    [string]$CommitMessage = ""
)

$ErrorActionPreference = "Continue"
$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$SitePath = $PSScriptRoot

function Write-SyncLog {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host ("[{0}] [{1}] [SITE-SYNC] {2}" -f $ts, $Level, $Message)
}

Write-SyncLog "Starting site sync"
Push-Location $WorkspaceRoot

try {
    # Step 1: rebuild articles.json
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $buildOutput = & python eu-intel-site\build.py 2>&1
    $buildExit = $LASTEXITCODE
    if ($buildExit -ne 0) {
        Write-SyncLog "build.py failed with exit=$buildExit" "ERROR"
        Write-SyncLog ("Output: " + ($buildOutput | Out-String)) "ERROR"
        return 1
    }
    Write-SyncLog "build.py OK"

    # Step 2: check if there are actual changes to commit
    $status = & git -C $SitePath status --porcelain 2>&1
    if ([string]::IsNullOrWhiteSpace($status)) {
        Write-SyncLog "No changes to commit, site already up to date" "OK"
        return 0
    }

    Write-SyncLog ("Changes detected: " + ($status | Measure-Object -Line).Lines + " files")

    # Step 3: commit
    $today = Get-Date -Format "yyyy-MM-dd"
    $msg = if ($CommitMessage) {
        $CommitMessage
    } else {
        "Update: auto-sync $today"
    }

    & git -C $SitePath add -A 2>&1 | Out-Null
    $commitOutput = & git -C $SitePath commit -m $msg 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-SyncLog "git commit failed" "ERROR"
        Write-SyncLog ("Output: " + ($commitOutput | Out-String)) "ERROR"
        return 1
    }
    Write-SyncLog ("Committed: " + $msg)

    # Step 4: push
    $pushOutput = & git -C $SitePath push 2>&1
    $pushExit = $LASTEXITCODE
    if ($pushExit -ne 0) {
        Write-SyncLog "git push failed (exit=$pushExit)" "ERROR"
        Write-SyncLog ("Output: " + ($pushOutput | Out-String)) "ERROR"
        return 1
    }
    Write-SyncLog "Pushed to origin" "OK"
    return 0
}
catch {
    Write-SyncLog ("Unexpected error: " + $_.Exception.Message) "ERROR"
    return 1
}
finally {
    Pop-Location
}
