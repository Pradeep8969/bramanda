"""Environment-only SMTP configuration; no credentials in validation errors."""
import os
import re

from django.core.exceptions import ImproperlyConfigured


def load_local_env(path, environ=None):
    """Load simple KEY=value lines locally, without expansion or shell execution.

    Existing process variables win. Quoted
    values are supported; inline comments and multiline values are not.
    """
    env = os.environ if environ is None else environ
    if not path.is_file():
        return
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ImproperlyConfigured(f'Invalid .env syntax at line {number}.')
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ImproperlyConfigured(f'Invalid .env quoting at line {number}.')
            value = value[1:-1]
        env.setdefault(key, value)


def smtp_config(env):
    def boolean(key, default):
        value = env.get(key, str(default)).strip().lower()
        if value not in ('true', '1', 'yes', 'false', '0', 'no'):
            raise ImproperlyConfigured(f'{key} must be True or False.')
        return value in ('true', '1', 'yes')

    try:
        port = int(env.get('EMAIL_PORT', '465'))
        timeout = int(env.get('EMAIL_TIMEOUT', '10'))
    except ValueError:
        raise ImproperlyConfigured('EMAIL_PORT and EMAIL_TIMEOUT must be integers.') from None
    if not 1 <= port <= 65535 or timeout <= 0:
        raise ImproperlyConfigured('EMAIL_PORT must be valid and EMAIL_TIMEOUT positive.')
    ssl = boolean('EMAIL_USE_SSL', port == 465)
    tls = boolean('EMAIL_USE_TLS', port == 587)
    if ssl and tls:
        raise ImproperlyConfigured('EMAIL_USE_SSL and EMAIL_USE_TLS cannot both be True.')
    if (port == 465 and (not ssl or tls)) or (port == 587 and (ssl or not tls)):
        raise ImproperlyConfigured('Port 465 requires SSL only; port 587 requires STARTTLS only.')
    host = env.get('EMAIL_HOST', 'smtp.gmail.com').strip()
    if host.lower() == 'smtp.gmail.com' and not (ssl or tls):
        raise ImproperlyConfigured('Gmail SMTP requires encrypted transport.')
    password = env.get('EMAIL_HOST_PASSWORD', '')
    # Google displays App Passwords in space-separated groups.
    if host.lower() == 'smtp.gmail.com':
        password = password.replace(' ', '')
    return dict(host=host, port=port, username=env.get('EMAIL_HOST_USER', '').strip(),
                password=password, use_ssl=ssl, use_tls=tls, timeout=timeout)
