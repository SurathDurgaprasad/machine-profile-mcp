import subprocess
import os
import logging
from typing import List, Tuple

logger = logging.getLogger("windows-diagnostics.services.subprocess_helper")


def safe_run_command(cmd: List[str], timeout: float = 3.0) -> Tuple[int, str, str]:
    """
    Executes a command safely on Windows.
    Prevents command window flashing, captures both stdout and stderr, enforces timeouts,
    and safely handles localized output encodings.

    Args:
        cmd (List[str]): List containing the command and its arguments.
        timeout (float): Max execution time in seconds.

    Returns:
        Tuple[int, str, str]: (returncode, stdout, stderr)
    """
    try:
        # Prevent popup window flashing on Windows
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        res = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=creation_flags,
            close_fds=True,
            text=False,  # Work with raw bytes to prevent decoding crashes
        )

        def decode_bytes(data: bytes) -> str:
            if not data:
                return ""
            # Fallback chain for localized encodings
            for enc in ["utf-8", "cp1252", "gbk", "ascii"]:
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace")

        return res.returncode, decode_bytes(res.stdout), decode_bytes(res.stderr)

    except subprocess.TimeoutExpired as e:
        logger.warning(f"Command timed out after {timeout} seconds: {' '.join(cmd)}")
        raise TimeoutError(f"Command {' '.join(cmd)} timed out.") from e

    except FileNotFoundError as e:
        logger.debug(f"Command executable not found: {cmd[0]}")
        raise FileNotFoundError(f"Command executable {cmd[0]} not found.") from e

    except Exception as e:
        logger.error(f"Unexpected error running command {' '.join(cmd)}: {e}")
        raise RuntimeError(f"Error running command {' '.join(cmd)}: {e}") from e
