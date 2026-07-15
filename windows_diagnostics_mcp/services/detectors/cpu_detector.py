import logging
import platform
import psutil

try:
    from winreg import HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx
except ImportError:
    HKEY_LOCAL_MACHINE = None
    OpenKey = None
    QueryValueEx = None

from ...models.system import CPUInfoModel, CapabilityStatusModel

logger = logging.getLogger("machine-profile.detectors.cpu")


class CPUDetector:
    """
    Detector for Windows host CPU characteristics.
    """

    def _detect_capabilities(self, architecture: str) -> tuple:
        arch_lower = architecture.lower()
        is_x86_x64 = any(
            x in arch_lower for x in ["amd64", "x86", "intel", "i386", "i686"]
        )

        if not is_x86_x64:
            not_app = CapabilityStatusModel(
                supported=None,
                status="unknown",
                source="none",
                detail="AVX features are not queried on non-x86/x64 architectures.",
            )
            return not_app, not_app, not_app

        if platform.system().lower() != "windows":
            unknown_status = CapabilityStatusModel(
                supported=None,
                status="unknown",
                source="none",
                detail="Feature detection only supported on Windows platforms.",
            )
            return unknown_status, unknown_status, unknown_status

        # Windows x86/x64: Use IsProcessorFeaturePresent
        try:
            import ctypes

            if (
                hasattr(ctypes, "windll")
                and hasattr(ctypes.windll, "kernel32")
                and hasattr(ctypes.windll.kernel32, "IsProcessorFeaturePresent")
            ):
                is_present = ctypes.windll.kernel32.IsProcessorFeaturePresent
                # Query constants (checks OS-visible capability from IsProcessorFeaturePresent, not direct CPUID):
                # PF_AVX_INSTRUCTIONS_AVAILABLE = 39
                # PF_AVX2_INSTRUCTIONS_AVAILABLE = 40
                # PF_AVX512F_INSTRUCTIONS_AVAILABLE = 41 (AVX-512 Foundation)
                avx = is_present(39) != 0
                avx2 = is_present(40) != 0
                avx512f = is_present(41) != 0

                return (
                    CapabilityStatusModel(
                        supported=avx,
                        status="available" if avx else "unavailable",
                        source="ctypes-probe",
                        detail="OS-visible AVX instruction support reported by Windows API.",
                    ),
                    CapabilityStatusModel(
                        supported=avx2,
                        status="available" if avx2 else "unavailable",
                        source="ctypes-probe",
                        detail="OS-visible AVX2 instruction support reported by Windows API.",
                    ),
                    CapabilityStatusModel(
                        supported=avx512f,
                        status="available" if avx512f else "unavailable",
                        source="ctypes-probe",
                        detail="OS-visible AVX512F instruction support reported by Windows API.",
                    ),
                )
            else:
                unknown_status = CapabilityStatusModel(
                    supported=None,
                    status="unknown",
                    source="none",
                    detail="Win32 IsProcessorFeaturePresent API is unavailable.",
                )
                return unknown_status, unknown_status, unknown_status
        except Exception:
            err_status = CapabilityStatusModel(
                supported=None,
                status="error",
                source="none",
                detail="Failed to query processor feature present.",
            )
            return err_status, err_status, err_status

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

        avx, avx2, avx512f = self._detect_capabilities(architecture)

        return CPUInfoModel(
            model=model,
            vendor=vendor,
            architecture=architecture,
            physical_cores=physical_cores,
            logical_processors=logical_processors,
            max_frequency_mhz=max_freq,
            avx_support=avx,
            avx2_support=avx2,
            avx512f_support=avx512f,
            status=status,
        )
