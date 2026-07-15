import os
import shutil
import logging
from typing import List, Dict, Tuple

try:
    import winreg
except ImportError:
    winreg = None

from ...models.ai import GPUInfoModel
from ..subprocess_helper import safe_run_command

logger = logging.getLogger("machine-profile.detectors.gpu")


class GPUDetector:
    """
    Detector for Windows host graphics adapter (GPU) information.
    """

    def _classify_adapter(self, name: str, vendor: str) -> str:
        """
        Classifies display adapter to virtual, integrated, discrete or unknown.
        """
        name_lower = name.lower()
        vendor_lower = vendor.lower()

        # Catch virtual/remote display adapters first
        if any(
            term in name_lower
            for term in [
                "remote display",
                "basic display",
                "virtual",
                "vmware",
                "citrix",
                "vbox",
                "hyper-v",
            ]
        ):
            return "virtual"

        # Explicitly supported high-confidence Intel integrated graphics patterns
        if "intel" in name_lower or "intel" in vendor_lower:
            if any(
                pat in name_lower
                for pat in [
                    "iris",
                    "uhd graphics",
                    "hd graphics",
                    "arc(tm) graphics",
                    "arc(tm) 140v",
                ]
            ):
                return "integrated"
            return "unknown"

        # Explicitly supported high-confidence AMD integrated graphics patterns
        if (
            "amd" in name_lower
            or "amd" in vendor_lower
            or "advanced micro devices" in vendor_lower
            or "ati " in name_lower
            or "radeon" in name_lower
        ):
            if name_lower in ("amd radeon graphics", "amd radeon(tm) graphics"):
                return "integrated"
            # High-confidence discrete AMD patterns
            if any(
                pat in name_lower
                for pat in ["radeon rx", "radeon pro", "firepro", "vega"]
            ):
                return "discrete"
            return "unknown"

        # NVIDIA discrete classification
        if "nvidia" in name_lower or "nvidia" in vendor_lower:
            return "discrete"

        # Do not infer type for unknown or other vendors (prefer unknown)
        return "unknown"

    def _get_gpu_info_smi(self) -> List[GPUInfoModel]:
        """
        Attempts to query NVIDIA GPUs using nvidia-smi.
        """
        gpu_list = []
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            for path in [
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            ]:
                if os.path.exists(path):
                    nvidia_smi = path
                    break

        if not nvidia_smi:
            return gpu_list

        try:
            code, stdout, stderr = safe_run_command(
                [
                    nvidia_smi,
                    "--query-gpu=name,driver_version,memory.total,memory.used,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                timeout=2.5,
            )
            if code == 0:
                for line in stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 5:
                        vram_mb = int(parts[2]) if parts[2].isdigit() else None
                        used_mb = int(parts[3]) if parts[3].isdigit() else None
                        free_mb = int(parts[4]) if parts[4].isdigit() else None

                        gpu_list.append(
                            GPUInfoModel(
                                name=parts[0],
                                vendor="NVIDIA",
                                vram_mb=vram_mb,
                                adapter_type="discrete",
                                dedicated_vram_bytes=(
                                    vram_mb * 1024 * 1024 if vram_mb else None
                                ),
                                shared_memory_bytes=None,
                                status="available",
                                source="nvidia-smi",
                                driver_version=parts[1],
                                memory_used=used_mb,
                                memory_free=free_mb,
                            )
                        )
        except Exception as e:
            logger.debug(f"nvidia-smi call failed or timed out: {e}")
        return gpu_list

    def _get_enum_device_map(self) -> Dict[str, Tuple[str, int]]:
        r"""
        Scans HKLM\SYSTEM\CurrentControlSet\Enum to associate display driver class subkeys
        with their unique PnP device instance IDs and ConfigFlags.
        """
        device_map = {}
        if winreg is None:
            return device_map

        enum_path = r"SYSTEM\CurrentControlSet\Enum"
        class_guid = "{4d36e968-e325-11ce-bfc1-08002be10318}"

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, enum_path) as enum_key:
                info = winreg.QueryInfoKey(enum_key)
                for i in range(info[0]):
                    enum_name = winreg.EnumKey(enum_key, i)
                    try:
                        with winreg.OpenKey(enum_key, enum_name) as enum_sub:
                            sub_info = winreg.QueryInfoKey(enum_sub)
                            for j in range(sub_info[0]):
                                dev_id = winreg.EnumKey(enum_sub, j)
                                try:
                                    with winreg.OpenKey(enum_sub, dev_id) as dev_key:
                                        dev_info = winreg.QueryInfoKey(dev_key)
                                        for k in range(dev_info[0]):
                                            inst_id = winreg.EnumKey(dev_key, k)
                                            try:
                                                with winreg.OpenKey(
                                                    dev_key, inst_id
                                                ) as inst_key:
                                                    cg, _ = winreg.QueryValueEx(
                                                        inst_key, "ClassGUID"
                                                    )
                                                    if cg.lower() == class_guid:
                                                        drv, _ = winreg.QueryValueEx(
                                                            inst_key, "Driver"
                                                        )
                                                        # drv is like {4d36e968-e325-11ce-bfc1-08002be10318}\0000
                                                        drv_key = drv.lower().replace(
                                                            "/", "\\"
                                                        )
                                                        try:
                                                            cf, _ = winreg.QueryValueEx(
                                                                inst_key,
                                                                "ConfigFlags",
                                                            )
                                                        except FileNotFoundError:
                                                            cf = 0

                                                        device_instance_id = f"{enum_name}\\{dev_id}\\{inst_id}"
                                                        device_map[drv_key] = (
                                                            device_instance_id,
                                                            cf,
                                                        )
                                            except Exception:
                                                pass
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Failed to scan Enum registry devices: {e}")
        return device_map

    def _get_registry_gpus(self) -> List[GPUInfoModel]:
        """
        Queries Windows registry display adapters to support Intel, AMD, and integrated GPUs.
        Deduplicates based on PnP device instance IDs and filters out inactive adapters.
        """
        gpu_list = []
        if winreg is None:
            return gpu_list

        enum_map = self._get_enum_device_map()

        try:
            path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as class_key:
                info = winreg.QueryInfoKey(class_key)
                candidates = []
                for i in range(info[0]):
                    subkey_name = winreg.EnumKey(class_key, i)
                    if not subkey_name.isdigit():
                        continue
                    try:
                        with winreg.OpenKey(class_key, subkey_name) as adapter_key:
                            try:
                                driver_desc, _ = winreg.QueryValueEx(
                                    adapter_key, "DriverDesc"
                                )
                            except FileNotFoundError:
                                continue

                            try:
                                provider_name, _ = winreg.QueryValueEx(
                                    adapter_key, "ProviderName"
                                )
                            except FileNotFoundError:
                                provider_name = "Unknown"

                            # 1. Determine active/present status
                            is_active = False
                            try:
                                with winreg.OpenKey(adapter_key, "VolatileSettings"):
                                    is_active = True
                            except FileNotFoundError:
                                pass

                            drv_path_key = f"{{4d36e968-e325-11ce-bfc1-08002be10318}}\\{subkey_name}".lower()
                            enum_device = enum_map.get(drv_path_key)

                            device_instance_id = None
                            config_flags = 0
                            if enum_device:
                                device_instance_id, config_flags = enum_device
                                # CONFIGFLAG_DEINSTALL (0x20) indicates not present / uninstalled
                                if (config_flags & 0x20) == 0:
                                    is_active = True

                            if not is_active:
                                continue

                            gpu_name = str(driver_desc)
                            gpu_vendor = str(provider_name)
                            adapter_type = self._classify_adapter(gpu_name, gpu_vendor)

                            dedicated_bytes = None
                            vram_mb = None
                            shared_bytes = None

                            identity_key = device_instance_id or drv_path_key

                            candidates.append(
                                {
                                    "identity": identity_key,
                                    "subkey_name": subkey_name,
                                    "model": GPUInfoModel(
                                        name=gpu_name,
                                        vendor=gpu_vendor,
                                        vram_mb=vram_mb,
                                        adapter_type=adapter_type,
                                        dedicated_vram_bytes=dedicated_bytes,
                                        shared_memory_bytes=shared_bytes,
                                        status="available",
                                        source="registry",
                                    ),
                                }
                            )
                    except Exception:
                        continue

                # Deduplicate candidates using their unique PnP device identity key
                seen_identities = {}
                for cand in candidates:
                    identity = cand["identity"]
                    if identity not in seen_identities:
                        seen_identities[identity] = cand
                    else:
                        existing = seen_identities[identity]
                        if cand["subkey_name"] < existing["subkey_name"]:
                            seen_identities[identity] = cand

                # Sort by subkey name to guarantee deterministic output order
                sorted_candidates = sorted(
                    seen_identities.values(), key=lambda c: c["subkey_name"]
                )
                for cand in sorted_candidates:
                    gpu_list.append(cand["model"])

        except Exception as e:
            logger.debug(f"Registry display adapters query failed: {e}")
        return gpu_list

    def detect(self) -> List[GPUInfoModel]:
        """
        Layered GPU detection: queries nvidia-smi first, falling back/supplementing with the registry.
        """
        smi_gpus = self._get_gpu_info_smi()
        reg_gpus = self._get_registry_gpus()

        if not smi_gpus:
            return reg_gpus

        # Merge registry GPUs that were not reported by nvidia-smi (e.g. integrated Intel cards)
        smi_names = {g.name.lower() for g in smi_gpus}
        for reg_gpu in reg_gpus:
            # Avoid duplicate matching by partial substring checks
            if not any(s_name in reg_gpu.name.lower() for s_name in smi_names):
                smi_gpus.append(reg_gpu)

        return smi_gpus
