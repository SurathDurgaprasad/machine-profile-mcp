import os
import re
import shutil
import time
import sys
import logging
from typing import List

from ..models.developer import DevEnvStatusModel, ToolInfoModel
from ..models.metadata import CollectionMetadataModel, WarningItem
from .subprocess_helper import safe_run_command

logger = logging.getLogger("windows-diagnostics.services.developer")


class DeveloperService:
    """
    Service for detecting common developer tools, their installation paths, and versions.
    """

    def _find_vscode(self) -> ToolInfoModel:
        """
        VS Code on Windows is often not in PATH but installed in standard locations.
        Queries both PATH and typical installation directories.
        """
        executable = shutil.which("code") or shutil.which("code.cmd")

        if not executable:
            # Check standard User install
            user_path = os.path.expandvars(
                r"%LocalAppData%\Programs\Microsoft VS Code\bin\code.cmd"
            )
            if os.path.exists(user_path):
                executable = user_path
            else:
                # Check System install
                sys_path = os.path.expandvars(
                    r"%ProgramFiles%\Microsoft VS Code\bin\code.cmd"
                )
                if os.path.exists(sys_path):
                    executable = sys_path

        if not executable:
            return ToolInfoModel(installed=False, status="not_detected")

        try:
            _, stdout, stderr = safe_run_command([executable, "--version"], timeout=2.0)
            output = stdout + "\n" + stderr
            lines = [line.strip() for line in output.split("\n") if line.strip()]
            version = lines[0] if lines else "Installed (Version unknown)"
            return ToolInfoModel(
                installed=True, status="installed", version=version, path=executable
            )
        except FileNotFoundError:
            return ToolInfoModel(installed=False, status="not_detected")
        except TimeoutError:
            return ToolInfoModel(
                installed=True,
                status="unavailable",
                path=executable,
                error_message="VS Code version check timed out.",
            )
        except Exception as e:
            return ToolInfoModel(
                installed=True, status="error", path=executable, error_message=str(e)
            )

    def _check_tool(
        self,
        cmd_name: str,
        version_args: List[str],
        version_regex: str,
        strip_chars: str = "",
    ) -> ToolInfoModel:
        """
        Helper to check standard CLI tools by running a version check command.
        """
        path = shutil.which(cmd_name)
        if not path:
            return ToolInfoModel(installed=False, status="not_detected")

        try:
            _, stdout, stderr = safe_run_command([path] + version_args, timeout=2.0)
            output = stdout + "\n" + stderr
            match = re.search(version_regex, output, re.IGNORECASE)
            if match:
                version = match.group(1).strip(strip_chars)
                return ToolInfoModel(
                    installed=True, status="installed", version=version, path=path
                )

            # Fallback if command runs but regex doesn't match
            fallback_version = output.strip().split("\n")[0]
            fallback_version = (
                fallback_version[:40] if fallback_version else "Installed"
            )
            return ToolInfoModel(
                installed=True, status="installed", version=fallback_version, path=path
            )
        except FileNotFoundError:
            return ToolInfoModel(installed=False, status="not_detected")
        except TimeoutError:
            return ToolInfoModel(
                installed=True,
                status="unavailable",
                path=path,
                error_message="Version check command timed out.",
            )
        except Exception as e:
            return ToolInfoModel(
                installed=True, status="error", path=path, error_message=str(e)
            )

    def get_developer_environment(self) -> DevEnvStatusModel:
        """
        Queries versions and paths of developer tools.
        """
        start_time = time.perf_counter()
        warnings = []
        status = "ok"

        # Python (current interpreter)
        try:
            python_path = sys.executable if hasattr(sys, "executable") else "python"
            python_version = ".".join(map(str, sys.version_info[:3]))
            python_info = ToolInfoModel(
                installed=True,
                status="installed",
                version=python_version,
                path=python_path,
            )
        except Exception as e:
            python_info = ToolInfoModel(
                installed=False, status="error", error_message=str(e)
            )
            warnings.append(
                WarningItem(
                    component="developer",
                    code="PYTHON_QUERY_FAILED",
                    message=f"Failed to query Python info: {e}",
                )
            )
            status = "partial"

        # Git
        git_info = self._check_tool(
            cmd_name="git",
            version_args=["--version"],
            version_regex=r"git version\s+([0-9a-zA-Z.-]+)",
        )

        # Node.js
        node_info = self._check_tool(
            cmd_name="node",
            version_args=["--version"],
            version_regex=r"v?([0-9.]+)",
            strip_chars="v",
        )

        # Docker
        docker_info = self._check_tool(
            cmd_name="docker",
            version_args=["--version"],
            version_regex=r"Docker version\s+([0-9a-zA-Z.-]+)",
        )

        # Java
        java_info = self._check_tool(
            cmd_name="java",
            version_args=["-version"],
            version_regex=r"(?:java|openjdk) version\s+\"([0-9a-zA-Z._-]+)\"",
        )

        # VS Code
        vscode_info = self._find_vscode()

        # Collect warning alerts if any tool has an error or unavailable status
        for tool_name, tool_data in [
            ("git", git_info),
            ("node", node_info),
            ("docker", docker_info),
            ("java", java_info),
            ("vscode", vscode_info),
        ]:
            if tool_data.status in ("error", "unavailable"):
                warnings.append(
                    WarningItem(
                        component="developer",
                        code=f"{tool_name.upper()}_CHECK_FAILED",
                        message=f"Checking {tool_name} returned status {tool_data.status}: {tool_data.error_message or 'No details'}",
                    )
                )
                status = "partial"

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        metadata = CollectionMetadataModel(
            timestamp=time.time(),
            duration_ms=round(duration_ms, 2),
            status=status,
            warnings=warnings,
        )

        return DevEnvStatusModel(
            python=python_info,
            git=git_info,
            node=node_info,
            docker=docker_info,
            java=java_info,
            vscode=vscode_info,
            collection_metadata=metadata,
        )
