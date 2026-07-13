import logging
import os
import pathlib
import shutil
import time
import winreg
from typing import List, Tuple
import httpx

from ..models.ai import AIEnvStatusModel, GPUInfoModel, OllamaModelInfoModel
from ..models.metadata import CollectionMetadataModel, WarningItem
from .subprocess_helper import safe_run_command

logger = logging.getLogger("windows-diagnostics.services.ai")

# Eager main-thread imports for heavy C-extensions to prevent GIL-lock worker thread deadlocks
try:
    import torch
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False
except Exception:
    _HAS_TORCH = False

try:
    import onnxruntime
    _HAS_ONNX = True
except ImportError:
    _HAS_ONNX = False
except Exception:
    _HAS_ONNX = False

class AIService:
    """
    Service for querying GPU information, Ollama models, virtual envs, and ML frameworks.
    """

    def _get_gpu_info_smi(self) -> List[GPUInfoModel]:
        """
        Attempts to query NVIDIA GPUs using nvidia-smi.
        """
        gpu_list = []
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            for path in [
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
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
                    "--format=csv,noheader,nounits"
                ],
                timeout=2.5
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
                                status="available",
                                source="nvidia-smi",
                                driver_version=parts[1],
                                memory_used=used_mb,
                                memory_free=free_mb
                            )
                        )
        except Exception as e:
            logger.debug(f"nvidia-smi call failed or timed out: {e}")
        return gpu_list

    def _get_registry_gpus(self) -> List[GPUInfoModel]:
        """
        Queries Windows registry display adapters to support Intel, AMD, and integrated GPUs.
        """
        gpu_list = []
        try:
            path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as class_key:
                info = winreg.QueryInfoKey(class_key)
                for i in range(info[0]):
                    subkey_name = winreg.EnumKey(class_key, i)
                    if not subkey_name.isdigit():
                        continue
                    try:
                        with winreg.OpenKey(class_key, subkey_name) as adapter_key:
                            try:
                                driver_desc, _ = winreg.QueryValueEx(adapter_key, "DriverDesc")
                            except FileNotFoundError:
                                continue

                            try:
                                provider_name, _ = winreg.QueryValueEx(adapter_key, "ProviderName")
                            except FileNotFoundError:
                                provider_name = "Unknown"

                            vram_mb = None
                            try:
                                vram_bytes, _ = winreg.QueryValueEx(adapter_key, "HardwareInformation.MemorySize")
                                if isinstance(vram_bytes, bytes):
                                    vram_val = int.from_bytes(vram_bytes, byteorder="little")
                                else:
                                    vram_val = int(vram_bytes)
                                vram_mb = vram_val // (1024 * 1024)
                            except FileNotFoundError:
                                pass

                            gpu_list.append(
                                GPUInfoModel(
                                    name=str(driver_desc),
                                    vendor=str(provider_name),
                                    vram_mb=vram_mb,
                                    status="available",
                                    source="registry"
                                )
                            )
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"Registry display adapters query failed: {e}")
        return gpu_list

    def _get_gpu_info(self) -> List[GPUInfoModel]:
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

    def _get_ollama_details(self) -> Tuple[bool, bool, List[OllamaModelInfoModel]]:
        """
        Detects if Ollama is installed and queries running status + models.
        Returns:
            Tuple[installed, running, list_of_models]
        """
        installed = shutil.which("ollama") is not None
        if not installed:
            user_ollama = os.path.expandvars(r"%LocalAppData%\Programs\Ollama\ollama.exe")
            if os.path.exists(user_ollama):
                installed = True

        running = False
        models = []

        try:
            # Query local API with a tight 1.5s timeout
            response = httpx.get("http://localhost:11434/api/tags", timeout=1.5)
            if response.status_code == 200:
                running = True
                data = response.json()
                for m in data.get("models", []):
                    details = m.get("details", {})
                    models.append(
                        OllamaModelInfoModel(
                            name=m.get("name", "unknown"),
                            size=m.get("size", 0),
                            family=details.get("family"),
                            format=details.get("format")
                        )
                    )
        except Exception:
            # Catch timeouts, connection refused, or HTTP failures safely
            pass

        return installed, running, models

    def _detect_virtual_envs(self) -> List[str]:
        """
        Scans workspace directory recursively to identify python virtual environments.
        Matches paths containing pyvenv.cfg.
        """
        venv_paths = []
        try:
            root_dir = pathlib.Path.cwd()
            for path in root_dir.glob("**/pyvenv.cfg"):
                skip_dirs = {".git", "node_modules", "AppData", "Local", "Temp", "Library"}
                if any(part in skip_dirs for part in path.parts):
                    continue

                venv_dir = path.parent
                try:
                    rel_path = venv_dir.relative_to(root_dir)
                    venv_paths.append(str(rel_path))
                except ValueError:
                    venv_paths.append(str(venv_dir))
        except Exception as e:
            logger.warning(f"Error scanning virtual environments: {e}")

        return sorted(venv_paths)

    def get_ai_environment(self) -> AIEnvStatusModel:
        """
        Compiles the AI status metadata.
        """
        start_time = time.perf_counter()
        warnings = []
        status = "ok"

        # GPU
        try:
            gpu_info = self._get_gpu_info()
            if not gpu_info:
                gpu_info = [
                    GPUInfoModel(
                        name="No dedicated GPU detected",
                        status="unavailable",
                        source="registry"
                    )
                ]
        except Exception as e:
            logger.error(f"Error checking GPU information: {e}")
            gpu_info = [
                GPUInfoModel(
                    name="GPU check failed",
                    status="error",
                    source="system-api"
                )
            ]
            warnings.append(WarningItem(component="gpu", code="GPU_CHECK_FAILED", message=f"GPU query failed: {str(e)}"))
            status = "partial"

        # Ollama
        try:
            ollama_installed, ollama_running, ollama_models = self._get_ollama_details()
        except Exception as e:
            ollama_installed, ollama_running, ollama_models = False, False, []
            warnings.append(WarningItem(component="ollama", code="OLLAMA_CHECK_FAILED", message=f"Ollama query failed: {str(e)}"))
            status = "partial"

        # PyTorch Check
        pytorch_installed = False
        pytorch_version = None
        pytorch_cuda = None
        if _HAS_TORCH:
            try:
                import torch
                pytorch_installed = True
                pytorch_version = str(torch.__version__)
                pytorch_cuda = torch.cuda.is_available()
            except Exception as e:
                logger.debug(f"Pytorch check failed: {e}")
                warnings.append(WarningItem(component="pytorch", code="PYTORCH_CHECK_FAILED", message=f"PyTorch check failed: {str(e)}"))
                status = "partial"

        # ONNX Runtime Check
        onnxruntime_installed = False
        onnxruntime_version = None
        onnxruntime_gpu = None
        if _HAS_ONNX:
            try:
                import onnxruntime
                onnxruntime_installed = True
                onnxruntime_version = str(onnxruntime.__version__)
                providers = onnxruntime.get_available_providers()
                onnxruntime_gpu = "CUDAExecutionProvider" in providers or "DmlExecutionProvider" in providers
            except Exception as e:
                logger.debug(f"ONNX Runtime check failed: {e}")
                warnings.append(WarningItem(component="onnxruntime", code="ONNXRUNTIME_CHECK_FAILED", message=f"ONNX Runtime check failed: {str(e)}"))
                status = "partial"

        # Virtual Envs
        try:
            virtual_envs = self._detect_virtual_envs()
        except Exception as e:
            virtual_envs = []
            warnings.append(WarningItem(component="virtualenv", code="VIRTUALENV_CHECK_FAILED", message=f"Virtualenv scanning failed: {str(e)}"))
            status = "partial"

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        metadata = CollectionMetadataModel(
            timestamp=time.time(),
            duration_ms=round(duration_ms, 2),
            status=status,
            warnings=warnings
        )

        return AIEnvStatusModel(
            gpu=gpu_info,
            ollama_installed=ollama_installed,
            ollama_running=ollama_running,
            ollama_models=ollama_models,
            pytorch_installed=pytorch_installed,
            pytorch_version=pytorch_version,
            pytorch_cuda_available=pytorch_cuda,
            onnxruntime_installed=onnxruntime_installed,
            onnxruntime_version=onnxruntime_version,
            onnxruntime_gpu_available=onnxruntime_gpu,
            python_virtual_environments=virtual_envs,
            collection_metadata=metadata
        )
