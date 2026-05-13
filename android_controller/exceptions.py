"""Exception hierarchy for android_controller."""


class AndroidControllerError(Exception):
    """Base class for all android_controller errors."""


class ConfigError(AndroidControllerError):
    """Raised when the config is malformed or missing required fields."""


class CommandError(AndroidControllerError):
    """Raised when an underlying shell command fails."""

    def __init__(self, cmd, returncode, stdout, stderr):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        msg = (
            f"Command failed (rc={returncode}): {cmd}\n"
            f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
        )
        super().__init__(msg)


class ElementNotFoundError(AndroidControllerError):
    """Raised when a UI element lookup turns up empty."""


class TimeoutError(AndroidControllerError):
    """Raised when an operation times out (e.g. waiting for a UI element)."""
