<#
    EU Intel site sync-and-push (idempotent)

    Rebuild articles.json, commit any changes, pull --rebase, push to GitHub Pages.
    Safe to run repeatedly: if nothing changed, no commit is made and it EXITS 0.

    Called by:
    - eu-daily-report agent Step 5 (primary path)
    - eu-intel/scheduler-cc.ps1 as a safety re-run after agent completes
      (ensures agent context-out / interruption does not leave site stale)

    Exit codes（呼叫端請看 $LASTEXITCODE，不要看 stdout）:
        0 = 網站已是最新（不論這次有沒有 commit）
        1 = 真的失敗

    2026-09-04 修正（一次假警報的完整病灶，改動前請先讀）:
    - `return N` 改 `exit N`。script scope 的 return 只把值丟進 output stream，
      不設 exit code，呼叫端 `$LASTEXITCODE` 讀到的是腳本內最後一個原生程式的
      exit code，跟本腳本的判斷完全脫鉤。
    - `git status --porcelain 2>&1` 拆開 stdout/stderr。原本 git 只要吐任何一行
      warning（例如 autocrlf 的 "LF will be replaced by CRLF"）就會被當成「有變更」。
    - 「沒東西可 commit」不再算失敗。git commit 在空 commit 時 exit 1，而這正是
      idempotent 保險重跑最常見的正常結局。改成 add 之後看 `git diff --cached --quiet`。
    - `git add` 的 exit code 不再被 Out-Null 吞掉（會漏報真失敗）。
    - 所有訊息同時寫進 $LogFile。原本全用 Write-Host（information stream），
      scheduled task 是 -WindowStyle Hidden 又沒重導向，證據 100% 消失。
    - push 前補 pull --rebase（CLAUDE.md 的 git 規則），且一定排在 commit 之後，
      否則工作樹有未 stage 變更時 pull --rebase 會直接失敗。

    Usage:
        .\eu-intel-site\sync-and-push.ps1
        .\eu-intel-site\sync-and-push.ps1 -CommitMessage "Update: add 2026-05-08"
        .\eu-intel-site\sync-and-push.ps1 -LogFile "C:\path\to\site-sync.log"
#>

param(
    [string]$CommitMessage = "",
    [string]$LogFile = ""
)

$ErrorActionPreference = "Continue"
$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$SitePath = $PSScriptRoot

if (-not $LogFile) {
    $logDir = Join-Path $WorkspaceRoot "eu-intel\scheduler-logs"
    if (-not (Test-Path $logDir)) { $logDir = $WorkspaceRoot }
    $LogFile = Join-Path $logDir ("site-sync-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
}

function Write-SyncLog {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[{0}] [{1}] [SITE-SYNC] {2}" -f $ts, $Level, $Message
    Write-Host $line
    if ($LogFile) {
        try {
            # UTF-8 無 BOM（CLAUDE.md 寫檔規則），不用 Out-File -Encoding utf8
            $sw = New-Object System.IO.StreamWriter($LogFile, $true, (New-Object System.Text.UTF8Encoding($false)))
            $sw.WriteLine($line)
            $sw.Close()
        } catch { }
    }
}

Write-SyncLog "Starting site sync (log: $LogFile)"
Push-Location $WorkspaceRoot

try {
    # ── Step 1: rebuild articles.json ──
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $buildOutput = & python eu-intel-site\build.py 2>&1
    $buildExit = $LASTEXITCODE
    if ($buildExit -ne 0) {
        Write-SyncLog "build.py failed with exit=$buildExit" "ERROR"
        Write-SyncLog ("Output: " + ($buildOutput | Out-String)) "ERROR"
        exit 1
    }
    Write-SyncLog "build.py OK"

    # ── Step 2: 有沒有真的變更 ──
    # stdout / stderr 一定要分開：git 的 warning 走 stderr，不是變更訊號。
    # 2>&1 之後 stderr 會變成 ErrorRecord 物件，用型別就能把兩條流分開。
    $statusRaw = & git -C $SitePath status --porcelain 2>&1
    $statusErr = @($statusRaw | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] })
    $status    = @($statusRaw | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] })
    if ($statusErr.Count -gt 0) {
        Write-SyncLog ("git status stderr（僅記錄，不當變更訊號）: " + (($statusErr | Out-String).Trim())) "WARN"
    }

    $changedLines = @($status | Where-Object { $_ -and $_.ToString().Trim() })
    if ($changedLines.Count -eq 0) {
        Write-SyncLog "No changes to commit, site already up to date" "OK"
        exit 0
    }
    Write-SyncLog ("Changes detected: " + $changedLines.Count + " files")

    # ── Step 3: stage ──
    $addOutput = & git -C $SitePath add -A 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-SyncLog "git add failed" "ERROR"
        Write-SyncLog ("Output: " + ($addOutput | Out-String)) "ERROR"
        exit 1
    }

    # stage 完之後才是真相：EOL 正規化 / 已被 add 過的檔可能 stage 後根本沒差異。
    # 這種情況 git commit 會 exit 1（"nothing to commit"），但它是正常結局不是失敗。
    & git -C $SitePath diff --cached --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-SyncLog "工作樹有雜訊但 stage 後無實質差異（多為 EOL 正規化），視為已是最新" "OK"
        exit 0
    }

    # ── Step 4: commit ──
    $today = Get-Date -Format "yyyy-MM-dd"
    $msg = if ($CommitMessage) { $CommitMessage } else { "Update: auto-sync $today" }

    $commitOutput = & git -C $SitePath commit -m $msg 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-SyncLog "git commit failed" "ERROR"
        Write-SyncLog ("Output: " + ($commitOutput | Out-String)) "ERROR"
        exit 1
    }
    Write-SyncLog ("Committed: " + $msg)

    # ── Step 5: pull --rebase 再 push（CLAUDE.md: push 前先 pull）──
    # 必須排在 commit 之後：工作樹有未 stage 變更時 pull --rebase 會直接 error。
    $pullOutput = & git -C $SitePath pull --rebase 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-SyncLog "git pull --rebase failed（本地 commit 已保留，未 push）" "ERROR"
        Write-SyncLog ("Output: " + ($pullOutput | Out-String)) "ERROR"
        exit 1
    }

    $pushOutput = & git -C $SitePath push 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-SyncLog "git push failed" "ERROR"
        Write-SyncLog ("Output: " + ($pushOutput | Out-String)) "ERROR"
        exit 1
    }
    Write-SyncLog "Pushed to origin" "OK"
    exit 0
}
catch {
    Write-SyncLog ("Unexpected error: " + $_.Exception.Message) "ERROR"
    exit 1
}
finally {
    Pop-Location
}
