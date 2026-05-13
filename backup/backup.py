"""
Daily PostgreSQL backup with 7-day retention.

Run as a Railway cron service: python backup.py
Stores backups in /data/backups/ (Railway volume mount).
Keeps the 7 most recent backups, deletes the rest.
"""

import os
import sys
import gzip
import shutil
import subprocess
import glob
from datetime import datetime
from urllib.parse import urlparse

BACKUP_DIR = os.environ.get('BACKUP_DIR', '/data/backups')
DATABASE_URL = os.environ.get('DATABASE_URL', '')
KEEP_BACKUPS = int(os.environ.get('KEEP_BACKUPS', '7'))

# Optional: send email notification on failure
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
NOTIFY_EMAIL = os.environ.get('BACKUP_NOTIFY_EMAIL', '')


def send_alert(subject, message):
    """Send email alert via Resend if configured."""
    if not RESEND_API_KEY or not NOTIFY_EMAIL:
        return
    try:
        import json
        from urllib.request import Request, urlopen
        payload = json.dumps({
            'from': os.environ.get('MAIL_FROM', 'Pharmabox24 <onboarding@resend.dev>'),
            'to': [NOTIFY_EMAIL],
            'subject': f'Pharmabox24 Backup: {subject}',
            'html': f'<p>{message}</p>'
        }).encode()
        req = Request(
            'https://api.resend.com/emails',
            data=payload,
            headers={
                'Authorization': f'Bearer {RESEND_API_KEY}',
                'Content-Type': 'application/json'
            },
            method='POST'
        )
        urlopen(req, timeout=10)
    except Exception as e:
        print(f'Failed to send alert email: {e}')


def _libpq_env_from_url(db_url):
    """Convert a postgresql:// URL into libpq env vars so pg_dump never sees the
    password on the command line or in a shell-interpreted string."""
    parsed = urlparse(db_url)
    if parsed.scheme not in ('postgres', 'postgresql'):
        raise ValueError(f'Unsupported DATABASE_URL scheme: {parsed.scheme!r}')
    env = os.environ.copy()
    if parsed.hostname:
        env['PGHOST'] = parsed.hostname
    if parsed.port:
        env['PGPORT'] = str(parsed.port)
    if parsed.username:
        env['PGUSER'] = parsed.username
    if parsed.password:
        env['PGPASSWORD'] = parsed.password
    if parsed.path and len(parsed.path) > 1:
        env['PGDATABASE'] = parsed.path.lstrip('/')
    return env


def run_backup():
    if not DATABASE_URL:
        print('ERROR: DATABASE_URL not set')
        send_alert('FAILED', 'DATABASE_URL environment variable is not set.')
        sys.exit(1)

    # Fix Railway's postgres:// URL
    db_url = DATABASE_URL
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    try:
        env = _libpq_env_from_url(db_url)
    except ValueError as ve:
        print(f'ERROR: {ve}')
        send_alert('FAILED', str(ve))
        sys.exit(1)

    # Create backup directory
    os.makedirs(BACKUP_DIR, exist_ok=True)

    # Generate filename with timestamp
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f'pharmabox24_{timestamp}.sql.gz'
    filepath = os.path.join(BACKUP_DIR, filename)

    print(f'Starting backup: {filename}')
    print(f'Backup directory: {BACKUP_DIR}')

    # Stream pg_dump through gzip in pure Python — no shell, no command injection.
    proc = None
    try:
        with gzip.open(filepath, 'wb') as gz_out:
            proc = subprocess.Popen(
                ['pg_dump', '--no-password', '--format=plain'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            shutil.copyfileobj(proc.stdout, gz_out)
            try:
                _, stderr = proc.communicate(timeout=300)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise

        if proc.returncode != 0:
            error_msg = (stderr or b'').decode('utf-8', errors='replace').strip()
            print(f'ERROR: pg_dump failed (rc={proc.returncode}): {error_msg}')
            send_alert('FAILED', f'pg_dump failed (rc={proc.returncode}): {error_msg}')
            if os.path.exists(filepath):
                os.remove(filepath)
            sys.exit(1)

        if not os.path.exists(filepath):
            print('ERROR: Backup file was not created')
            send_alert('FAILED', 'Backup file was not created.')
            sys.exit(1)

        file_size = os.path.getsize(filepath)
        if file_size < 100:
            print(f'ERROR: Backup file suspiciously small ({file_size} bytes)')
            send_alert('FAILED', f'Backup file is only {file_size} bytes — likely empty or corrupt.')
            os.remove(filepath)
            sys.exit(1)

        size_kb = file_size / 1024
        print(f'Backup complete: {filename} ({size_kb:.1f} KB)')

    except subprocess.TimeoutExpired:
        print('ERROR: pg_dump timed out after 5 minutes')
        send_alert('FAILED', 'pg_dump timed out after 5 minutes.')
        if os.path.exists(filepath):
            os.remove(filepath)
        sys.exit(1)
    except FileNotFoundError:
        # pg_dump binary missing on the host
        print('ERROR: pg_dump binary not found on PATH')
        send_alert('FAILED', 'pg_dump binary not found on PATH — install postgresql-client.')
        if os.path.exists(filepath):
            os.remove(filepath)
        sys.exit(1)
    except Exception as e:
        print(f'ERROR: Unexpected error: {e}')
        send_alert('FAILED', f'Unexpected error: {e}')
        if proc and proc.poll() is None:
            proc.kill()
        if os.path.exists(filepath):
            # Don't keep a half-written backup hanging around.
            try:
                if os.path.getsize(filepath) == 0:
                    os.remove(filepath)
            except OSError:
                pass
        sys.exit(1)

    # Rotate old backups — keep only the most recent N
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, 'pharmabox24_*.sql.gz')))
    if len(backups) > KEEP_BACKUPS:
        to_delete = backups[:len(backups) - KEEP_BACKUPS]
        for old_file in to_delete:
            os.remove(old_file)
            print(f'Deleted old backup: {os.path.basename(old_file)}')

    # List remaining backups
    remaining = sorted(glob.glob(os.path.join(BACKUP_DIR, 'pharmabox24_*.sql.gz')))
    print(f'\nBackups on disk ({len(remaining)}/{KEEP_BACKUPS}):')
    for f in remaining:
        size = os.path.getsize(f) / 1024
        print(f'  {os.path.basename(f)} ({size:.1f} KB)')

    print('\nBackup job complete.')


if __name__ == '__main__':
    run_backup()
