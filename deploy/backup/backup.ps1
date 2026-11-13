#requires -Version 5.1
<#
.SYNOPSIS
    Creates a consistent RollCall AI backup (SQLite and/or PostgreSQL).

.DESCRIPTION
    * SQLite: uses `sqlite3 .backup` when available (safe with WAL), otherwise
      copies the database file.
    * PostgreSQL/Supabase: runs `pg_dump` against DATABASE_URL_SYNC when set.
    * Writes a SHA-256 checksum beside every archive and prunes archives older
      than -RetentionDays.
    * Encrypts every archive with 7-Zip (AES-256) using
      BACKUP_ENCRYPTION_PASSWORD. An unencrypted backup is never written.

.EXAMPLE
    pwsh ./deploy/backup/backup.ps1

.EXAMPLE
    pwsh ./deploy/backup/backup.ps1 -BackupDir D:\rollcall-backups -RetentionDays 60
#>
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$BackupDir = "",
    [int]$RetentionDays = 30,
    [string]$EncryptionPassword = $env:BACKUP_ENCRYPTION_PASSWORD
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($EncryptionPassword)) {
    throw "BACKUP_ENCRYPTION_PASSWORD is required. Refusing to write an unencrypted backup."
}

$sevenZip = Get-Command 7z -ErrorAction SilentlyContinue
if (-not $sevenZip) {
    throw "7z (7-Zip) is required to create encrypted backups. Install it and re-run."
}

if ([string]::IsNullOrWhiteSpace($BackupDir)) {
    $BackupDir = Join-Path $RepoRoot "backups"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$created = @()

function Write-Checksum([string]$Path) {
    $hash = Get-FileHash -Path $Path -Algorithm SHA256
    "$($hash.Hash)  $([System.IO.Path]::GetFileName($Path))" |
        Set-Content -Path "$Path.sha256" -Encoding ascii
}

function Compress-Encrypted([string]$Source, [string]$Destination) {
    # -mhe=on encrypts the archive headers (file names) as well as the data.
    & $sevenZip.Source a -t7z -mhe=on "-p$EncryptionPassword" $Destination $Source | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "7z failed to create encrypted archive '$Destination' (exit code $LASTEXITCODE)."
    }
}

# --- SQLite ---------------------------------------------------------------
$dbPath = Join-Path $RepoRoot "data\attendance.db"
if (Test-Path $dbPath) {
    $snapshot = Join-Path $BackupDir "attendance_$stamp.db"
    $sqlite = Get-Command sqlite3 -ErrorAction SilentlyContinue
    if ($sqlite) {
        & sqlite3 $dbPath ".backup '$snapshot'"
        if ($LASTEXITCODE -ne 0) { throw "sqlite3 .backup failed with exit code $LASTEXITCODE" }
    }
    else {
        Copy-Item -Path $dbPath -Destination $snapshot -Force
        Write-Warning "sqlite3 was not found; performed a plain file copy. Install sqlite3 for WAL-safe backups."
    }

    $zip = "$snapshot.7z"
    Compress-Encrypted -Source $snapshot -Destination $zip
    Remove-Item -Path $snapshot -Force
    Write-Checksum $zip
    $created += $zip
}
else {
    Write-Warning "SQLite database not found at $dbPath; skipping SQLite backup."
}

# --- PostgreSQL / Supabase ------------------------------------------------
$pgUrl = $env:DATABASE_URL_SYNC
if (-not [string]::IsNullOrWhiteSpace($pgUrl)) {
    $pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
    if (-not $pgDump) {
        Write-Warning "DATABASE_URL_SYNC is set but pg_dump is not on PATH; skipping PostgreSQL backup."
    }
    else {
        $dump = Join-Path $BackupDir "postgres_$stamp.sql"
        & pg_dump --no-owner --no-privileges --format=plain --file=$dump $pgUrl
        if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
        $zip = "$dump.7z"
        Compress-Encrypted -Source $dump -Destination $zip
        Remove-Item -Path $dump -Force
        Write-Checksum $zip
        $created += $zip
    }
}

# --- Retention ------------------------------------------------------------
$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem -Path $BackupDir -File |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    Remove-Item -Force

if ($created.Count -eq 0) {
    Write-Warning "No backup was created. Check the database configuration."
    exit 1
}

Write-Host "Backup complete:"
$created | ForEach-Object { Write-Host "  $_" }
Write-Host "Retention: $RetentionDays day(s)"
