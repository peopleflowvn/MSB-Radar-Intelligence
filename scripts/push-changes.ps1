<#
.SYNOPSIS
    Review, commit, and push the current changes in this repo.

.DESCRIPTION
    Reusable version of the "commit + push" workflow: shows what changed,
    lets you pick exactly which files go into the commit (so unrelated
    work-in-progress never rides along by accident), blocks obvious secret
    files, writes the commit, and pushes to the current branch's remote.

    Safe by default:
      - Never stages everything blindly. Without -All or -Files you get an
        interactive checklist of changed/untracked files.
      - Refuses to stage files that look like secrets (.env, *.pem, keys,
        anything with "secret"/"credential" in the name) unless -Force.
      - Never uses --no-verify, --force, or any history-rewriting flag.
      - Aborts (does not push) if the remote branch has commits you don't
        have locally yet, so you never silently overwrite someone else's
        push -- run "git pull" first in that case.

.PARAMETER Message
    Commit message. If omitted you'll be prompted for one.

.PARAMETER Files
    Explicit list of paths (relative to repo root) to stage. Skips the
    interactive checklist.

.PARAMETER All
    Stage every changed/untracked file (still runs the secret-file check).
    Use when you know the whole working tree belongs in this commit.

.PARAMETER RunTests
    Run the Django test suite (product_core/server) before committing.
    Aborts the whole run if tests fail.

.PARAMETER NoPush
    Commit only; don't push. Useful to review the commit before sending it.

.PARAMETER DryRun
    Show what would be staged/committed/pushed without doing any of it.

.PARAMETER Force
    Allow staging files that matched the secret-file heuristic. Use only
    when you've actually checked the file's contents yourself.

.EXAMPLE
    .\scripts\push-changes.ps1
    Interactive: pick files, get prompted for a message, push.

.EXAMPLE
    .\scripts\push-changes.ps1 -All -Message "Fix knowledge base routing" -RunTests
    Stage everything, run tests first, commit, push.

.EXAMPLE
    .\scripts\push-changes.ps1 -Files product_core/server/ai/conversation.py -Message "..." -NoPush
    Stage one file, commit, but don't push yet.
#>
[CmdletBinding()]
param(
    [string]$Message,
    [string[]]$Files,
    [switch]$All,
    [switch]$RunTests,
    [switch]$NoPush,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Write-Warn($text) { Write-Host "!! $text" -ForegroundColor Yellow }
function Write-Err($text)  { Write-Host "xx $text" -ForegroundColor Red }
function Fail($text) { Write-Err $text; exit 1 }

# --- Locate repo root -------------------------------------------------------
try {
    $repoRoot = (git rev-parse --show-toplevel 2>$null)
} catch { $repoRoot = $null }
if (-not $repoRoot) { Fail "Not inside a git repository." }
Set-Location $repoRoot

# --- Sanity: no rebase/merge in progress ------------------------------------
$gitDir = git rev-parse --git-dir
foreach ($marker in @("MERGE_HEAD", "rebase-merge", "rebase-apply")) {
    if (Test-Path (Join-Path $gitDir $marker)) {
        Fail "A $marker is in progress. Resolve that first (this script won't touch it)."
    }
}

# --- Show current state ------------------------------------------------------
Write-Step "Current branch and status"
$branch = git rev-parse --abbrev-ref HEAD
Write-Host "Branch: $branch"
git status -s | ForEach-Object { Write-Host $_ }

$porcelain = git status --porcelain=v1
if (-not $porcelain) {
    Write-Host "`nNothing changed -- working tree is clean. Nothing to do." -ForegroundColor Green
    exit 0
}

# --- Check remote is not ahead (avoid clobbering someone else's push) -------
$upstream = git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
if ($LASTEXITCODE -eq 0 -and $upstream) {
    git fetch --quiet $($upstream.Split('/')[0]) 2>$null
    $behind = git rev-list --count "HEAD..$upstream" 2>$null
    if ($behind -and [int]$behind -gt 0) {
        Fail "Local $branch is $behind commit(s) behind $upstream. Run 'git pull' first, then re-run this script."
    }
}

# --- Build the candidate file list ------------------------------------------
$changedLines = $porcelain -split "`n" | Where-Object { $_ -ne "" }
$candidates = @()
foreach ($line in $changedLines) {
    $path = $line.Substring(3).Trim()
    if ($path -match '^"(.*)"$') { $path = $Matches[1] }
    if ($path -match ' -> ') { $path = ($path -split ' -> ')[1] }
    $candidates += $path
}
$candidates = $candidates | Select-Object -Unique

$selected = @()
if ($Files) {
    $selected = $Files
} elseif ($All) {
    $selected = $candidates
} else {
    Write-Step "Pick files to include in this commit"
    for ($i = 0; $i -lt $candidates.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f ($i + 1), $candidates[$i])
    }
    Write-Host "`nEnter numbers to include (e.g. 1,3,4), 'all', or blank to cancel:"
    $answer = Read-Host "Files"
    if (-not $answer) { Write-Warn "Cancelled -- nothing staged."; exit 0 }
    if ($answer.Trim().ToLower() -eq "all") {
        $selected = $candidates
    } else {
        $indices = $answer -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^\d+$' }
        foreach ($idx in $indices) {
            $n = [int]$idx
            if ($n -ge 1 -and $n -le $candidates.Count) { $selected += $candidates[$n - 1] }
        }
    }
}
if (-not $selected -or $selected.Count -eq 0) { Fail "No valid files selected." }

# --- Secret-file guard -------------------------------------------------------
$secretPattern = '(^|[\\/])\.env($|[\\/.])|\.pem$|\.key$|id_rsa|credentials|secret'
$suspicious = $selected | Where-Object { $_ -imatch $secretPattern }
if ($suspicious -and -not $Force) {
    Write-Err "These look like they might hold secrets -- refusing to stage them:"
    $suspicious | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Fail "Re-run with -Force if you've checked the contents and they're really safe to commit."
}

Write-Step "Files to stage"
$selected | ForEach-Object { Write-Host "  $_" }

if ($DryRun) {
    Write-Warn "Dry run -- stopping before 'git add'."
    exit 0
}

git add -- $selected
if ($LASTEXITCODE -ne 0) { Fail "git add failed." }

Write-Step "Staged diff"
git diff --cached --stat

# --- Optional test gate -------------------------------------------------------
if ($RunTests) {
    Write-Step "Running Django test suite (product_core/server)"
    Push-Location (Join-Path $repoRoot "product_core/server")
    try {
        python manage.py test
        if ($LASTEXITCODE -ne 0) {
            Pop-Location
            Fail "Tests failed -- not committing. Fix the failures and re-run."
        }
    } finally {
        if ((Get-Location).Path -eq (Join-Path $repoRoot "product_core/server")) { Pop-Location }
    }
    Write-Host "Tests passed." -ForegroundColor Green
}

# --- Commit message -----------------------------------------------------------
if (-not $Message) {
    Write-Host "`nEnter commit message (single line):"
    $Message = Read-Host "Message"
}
if (-not $Message) { Fail "Empty commit message -- aborting (changes remain staged)." }

$msgFile = New-TemporaryFile
try {
    Set-Content -Path $msgFile -Value $Message -Encoding utf8 -NoNewline
    git commit -F $msgFile
    if ($LASTEXITCODE -ne 0) { Fail "git commit failed (see output above) -- changes remain staged." }
} finally {
    Remove-Item $msgFile -ErrorAction SilentlyContinue
}

Write-Step "Committed"
git log -1 --stat

# --- Push -----------------------------------------------------------------
if ($NoPush) {
    Write-Warn "NoPush set -- commit created locally, not pushed."
    exit 0
}

Write-Step "Pushing $branch"
if ($upstream) {
    git push
} else {
    git push -u origin $branch
}
if ($LASTEXITCODE -ne 0) { Fail "git push failed -- commit is still local, fix the issue and push manually." }

Write-Host "`nDone." -ForegroundColor Green
