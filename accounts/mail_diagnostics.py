"""Safe error summaries: never include server text, addresses or tracebacks."""

import smtplib
import ssl


def error_summary(error):
    if isinstance(error, smtplib.SMTPAuthenticationError):
        category = "authentication rejected"
    elif isinstance(error, ssl.SSLError):
        category = "TLS failure"
    elif isinstance(error, smtplib.SMTPServerDisconnected):
        category = "connection closed (credentials acceptance unconfirmed)"
    elif isinstance(
        error,
        (
            smtplib.SMTPSenderRefused,
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPDataError,
        ),
    ):
        category = "message rejected"
    elif isinstance(error, smtplib.SMTPNotSupportedError):
        category = "SMTP feature unavailable"
    elif isinstance(error, smtplib.SMTPException):
        category = "SMTP protocol failure"
    elif isinstance(error, OSError):
        category = "connection failure"
    else:
        category = "email failure"
    code = getattr(error, "smtp_code", None)
    return category + (f" (SMTP {code})" if isinstance(code, int) else "")


def send_safely(message, logger, purpose):
    try:
        if message.send() != 1:
            logger.error("%s email was not accepted by the backend.", purpose)
            return False
        return True
    except Exception as error:
        # Some backends and address validation raise non-SMTP exceptions.
        # Deliberately omit exception text and traceback, including reset tokens.
        logger.error("%s email failed: %s.", purpose, error_summary(error))
        return False
