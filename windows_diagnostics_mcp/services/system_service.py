import getpass
import logging
import platform
import socket
import time
import winreg
from typing import Tuple
import psutil

from ..models.system import SystemSummaryModel
from ..models.metadata import CollectionMetadataModel

logger = logging.getLogger("windows-diagnostics.services.system")

class SystemService:
    """
    Service for querying high-level Windows system metadata and uptime.
    """

    def _get_windows_details(self) -> Tuple[str, str, str]:
        """
        Query the Windows Registry for exact Windows Edition, Version, and Build Number.
        Returns:
            Tuple[str, str, str]: (Edition/Product Name, Display Version, Build Number)
        """
        product_name = platform.system()
        display_version = "Unknown"
        build_number = platform.version()

        # Fallback build extraction from platform.version() (e.g., '10.0.22631')
        parts = build_number.split('.')
        if len(parts) >= 3:
            build_number = parts[2]

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
            ) as key:
                try:
                    product, _ = winreg.QueryValueEx(key, "ProductName")
                    if product:
                        product_name = str(product)
                except FileNotFoundError:
                    pass

                try:
                    display_ver, _ = winreg.QueryValueEx(key, "DisplayVersion")
                    if display_ver:
                        display_version = str(display_ver)
                except FileNotFoundError:
                    # Fallback to older release ID registry if DisplayVersion is missing
                    try:
                        release_id, _ = winreg.QueryValueEx(key, "ReleaseId")
                        if release_id:
                            display_version = str(release_id)
                    except FileNotFoundError:
                        pass

                try:
                    build, _ = winreg.QueryValueEx(key, "CurrentBuild")
                    if build:
                        build_number = str(build)
                except FileNotFoundError:
                    pass
        except Exception as e:
            logger.warning(f"Error reading registry for Windows version details: {e}")

        # Resolve Windows 10 vs 11 compatibility registry quirk.
        # Windows 11 registry "ProductName" remains hardcoded as "Windows 10" for legacy app compat.
        # Build numbers >= 22000 indicate Windows 11.
        if product_name.startswith("Windows 10"):
            try:
                clean_build = build_number.split('.')[-1]
                if clean_build.isdigit() and int(clean_build) >= 22000:
                    product_name = product_name.replace("Windows 10", "Windows 11", 1)
            except Exception:
                pass

        return product_name, display_version, build_number

    def _format_uptime(self, seconds: float) -> str:
        """
        Format uptime in seconds to a human-readable string.
        """
        days, rem = divmod(int(seconds), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds_int = divmod(rem, 60)

        parts = []
        if days > 0:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

        if not parts:
            return "Just booted"

        return ", ".join(parts)

    def get_system_summary(self) -> SystemSummaryModel:
        """
        Gathers system information and returns the SystemSummaryModel.
        """
        start_time = time.perf_counter()
        warnings = []
        status = "ok"

        try:
            product_name, display_version, build_number = self._get_windows_details()
            if display_version == "Unknown":
                status = "partial"
                warnings.append(
                    WarningItem(
                        component="system",
                        code="REGISTRY_VERSION_UNAVAILABLE",
                        message="Failed to query Windows version/build from registry."
                    )
                )
        except Exception as e:
            product_name, display_version, build_number = platform.system(), "Unknown", platform.version()
            status = "partial"
            logger.warning(f"Failed to gather Windows details: {e}")

        # Compute system uptime
        try:
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            uptime_formatted = self._format_uptime(uptime_seconds)
        except Exception as e:
            uptime_seconds = 0.0
            uptime_formatted = "Unknown"
            status = "partial"
            logger.warning(f"Failed to calculate system uptime: {e}")

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        metadata = CollectionMetadataModel(
            timestamp=time.time(),
            duration_ms=round(duration_ms, 2),
            status=status,
            warnings=warnings
        )

        try:
            username = getpass.getuser()
        except Exception:
            username = "Unknown"

        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "Unknown"

        return SystemSummaryModel(
            edition=product_name,
            version=display_version,
            build_number=build_number,
            architecture=platform.machine(),
            hostname=hostname,
            username=username,
            uptime_seconds=uptime_seconds,
            uptime_formatted=uptime_formatted,
            collection_metadata=metadata
        )
