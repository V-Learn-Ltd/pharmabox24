import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


def _is_development():
    """Detect non-production environment."""
    return os.environ.get('FLASK_ENV') == 'development' or os.environ.get('PHARMABOX_ENV') == 'development'


class Config:
    # SECRET_KEY — refuse to boot without one in production.
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(64))"
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY or len(SECRET_KEY) < 32:
        if _is_development():
            SECRET_KEY = 'dev-only-key-not-for-production-use-never'
        else:
            raise RuntimeError(
                'SECRET_KEY env var must be set to at least 32 characters in production. '
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )

    # Railway uses DATABASE_URL with postgres:// but SQLAlchemy needs postgresql://
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = database_url or \
        'sqlite:///' + os.path.join(basedir, 'pharmacy.db')

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
    }

    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload (WSGI-level)
    UPLOAD_MAX_ROWS = 100_000              # Per-sheet row cap to bound parser memory
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Session cookie security — hard default to Secure in any non-dev environment.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = not _is_development()
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = not _is_development()

    # Email via Resend (https://resend.com)
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
    MAIL_FROM = os.environ.get('MAIL_FROM') or 'Pharmabox24 <onboarding@resend.dev>'

    # Site URL for email links
    SITE_URL = os.environ.get('SITE_URL', '')

    # Display timezone for "today / yesterday" semantics
    DISPLAY_TIMEZONE = os.environ.get('DISPLAY_TIMEZONE', 'Europe/Dublin')

    # Trusted proxy depth — Railway sits in front of the app
    TRUSTED_PROXY_COUNT = int(os.environ.get('TRUSTED_PROXY_COUNT', '1'))
