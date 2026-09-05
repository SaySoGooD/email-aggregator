class MailException(Exception):
    """Base exception for mail errors."""


class MailConnectionError(MailException):
    """Raised when a connection to the IMAP/SMTP server fails."""


class MailAuthError(MailException):
    """Raised when the server rejects the account credentials."""


class MailFetchError(MailException):
    """Raised when messages cannot be fetched (bad folder, protocol error)."""


class MailSendError(MailException):
    """Raised when a message cannot be sent."""


class AccountNotFoundError(MailException):
    """Raised when an account name does not exist in the store."""


class AccountAlreadyExistsError(MailException):
    """Raised when adding an account whose name is already taken."""


class OAuthError(MailException):
    """Raised when an OAuth2 device-code flow or token refresh fails."""
