import logging
import platform
import psutil

try:
    from winreg import HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx
except ImportError:
    HKEY_LOCAL_MACHINE = None
    OpenKey = None
    QueryValueEx = None

from ...models.system import CPUInfoModel

logger = logging.getLogger("machine-profile.detectors.cpu")


class CPUDetector:
    """
    Detector for Windows host CPU characteristics.
    """

    def detect(self) -> CPUInfoModel:
        model = "Unknown"
        vendor = "Unknown"
        architecture = platform.machine() or "Unknown"
        physical_cores = None
        logical_processors = None
        max_freq = None
        status = "available"

        # Try to resolve core counts from psutil
        try:
            physical_cores = psutil.cpu_count(logical=False)
            logical_processors = psutil.cpu_count(logical=True)
        except Exception as e:
            logger.warning(f"Failed to read CPU core counts via psutil: {e}")
            status = "partial"

        # Try to read dynamic core frequency
        try:
            freq_info = psutil.cpu_freq()
            if freq_info:
                max_freq = int(freq_info.max) if freq_info.max else None
        except Exception:
            pass

        # Try to query Windows registry for detailed model / vendor info
        if (
            HKEY_LOCAL_MACHINE is not None
            and OpenKey is not None
            and QueryValueEx is not None
        ):
            try:
                with OpenKey(
                    HKEY_LOCAL_MACHINE,
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                ) as key:
                    try:
                        m, _ = QueryValueEx(key, "ProcessorNameString")
                        if m:
                            model = str(m).strip()
                    except FileNotFoundError:
                        pass

                    try:
                        v, _ = QueryValueEx(key, "VendorIdentifier")
                        if v:
                            vendor = str(v).strip()
                    except FileNotFoundError:
                        pass

                    try:
                        hz, _ = QueryValueEx(key, "~MHz")
                        if hz and not max_freq:
                            max_freq = int(hz)
                    except FileNotFoundError:
                        pass
            except Exception as e:
                logger.warning(f"Error querying CPU details from registry: {e}")
                status = "partial"

        # Fallbacks if registry failed or was missing values
        if model == "Unknown":
            proc = platform.processor()
            if proc:
                model = proc
            else:
                model = "Unknown CPU"
                status = "partial"

        if vendor == "Unknown":
            model_lower = model.lower()
            if "intel" in model_lower or "genuineintel" in model_lower:
                vendor = "GenuineIntel"
            elif "amd" in model_lower or "authenticamd" in model_lower:
                vendor = "AuthenticAMD"
            else:
                vendor = "Unknown"

        # Overall error checking
        if model == "Unknown CPU" and vendor == "Unknown" and physical_cores is None:
            status = "error"

        return CPUInfoModel(
            model=model,
            vendor=vendor,
            architecture=architecture,
            physical_cores=physical_cores,
            logical_processors=logical_processors,
            max_frequency_mhz=max_freq,
            status=status,
        )
