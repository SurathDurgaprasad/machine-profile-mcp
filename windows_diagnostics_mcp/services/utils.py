import getpass
import os
import re
from typing import Optional


def sanitize_user_path(path: Optional[str]) -> Optional[str]:
    """
    Sanitizes username references in Windows paths.
    If the environment variable MACHINE_PROFILE_ANONYMIZE is 'true',
    this function replaces occurrences of the username under Users directory
    with 'LocalUser'.
    """
    if path is None:
        return None

    # Opt-in check for anonymization
    anonymize = os.environ.get("MACHINE_PROFILE_ANONYMIZE") == "true"
    if not anonymize:
        return path

    try:
        username = getpass.getuser()
    except Exception:
        username = os.environ.get("USERNAME", "")

    if not username:
        return path

    # Case-insensitive replacement of Users/username pattern
    escaped_user = re.escape(username)
    pattern = re.compile(
        r"([\\/]Users[\\/])" + escaped_user + r"([\\/]|$)", re.IGNORECASE
    )

    return pattern.sub(r"\1LocalUser\2", path)
