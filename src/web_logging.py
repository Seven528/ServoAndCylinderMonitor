"""Shared instance of the project's existing Logger for the Web application."""
from functools import lru_cache
from pathlib import Path
import re
import traceback

from src.logger import Logger


@lru_cache(maxsize=1)
def get_logger():
    return Logger(str(Path(__file__).resolve().parents[1] / 'data' / 'output'))


def log_failure(module, error, context='', secrets=()):
    # Logger appends tracebacks itself. Supply a sanitized exception explicitly so
    # its sys.exc_info fallback cannot append an unsanitized remote exception.
    stack = ''.join(traceback.format_tb(error.__traceback__)) if error.__traceback__ else ''
    message = f'{context} | {type(error).__name__}: {str(error)[:1000]}'
    if stack:
        message += '\nTraceback (most recent call last):\n' + stack
    for secret in secrets:
        if secret:
            message = message.replace(str(secret), '[redacted]')
    message = re.sub(r'(?i)(password|x-clickhouse-key|token)(\s*[=:]\s*)[^\s,;]+', r'\1\2[redacted]', message)
    # A fresh exception has no active traceback, avoiding Logger's sys.exc_info
    # fallback. The sanitized original stack is already included in its message.
    get_logger().write_log('ERROR', module, RuntimeError(message))
