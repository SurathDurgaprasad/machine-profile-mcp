import logging
import os
import pathlib
import shutil
import time
from typing import List, Tuple
import httpx

from ..models.ai import (
    AIEnvStatusModel,
    GPUInfoModel,
    OllamaModelInfoModel,
    LocalModelInventoryModel,
    DockerStatusModel,
)
from ..models.metadata import CollectionMetadataModel, WarningItem
from .detectors.gpu_detector import GPUDetector
from .detectors.ollama_detector import OllamaDetector
from .detectors.lmstudio_detector import LMStudioDetector
from .detectors.docker_detector import DockerDetector
from .utils import sanitize_user_path

logger = logging.getLogger("windows-diagnostics.services.ai")

# Eager main-thread imports for heavy C-extensions to prevent GIL-lock worker thread deadlocks
try:
    import torch  # noqa: F401

    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False
except Exception:
    _HAS_TORCH = False

try:
    import onnxruntime  # noqa: F401

    _HAS_ONNX = True
except ImportError:
    _HAS_ONNX = False
except Exception:
    _HAS_ONNX = False


class AIService:
    """
    Service for querying GPU information, Ollama models, virtual envs, and ML frameworks.
    """

    def __init__(self):
        self._gpu_detector = GPUDetector()
        self._ollama_detector = OllamaDetector()
        self._lmstudio_detector = LMStudioDetector()
        self._docker_detector = DockerDetector()

    def _get_ollama_details(self) -> Tuple[bool, bool, List[OllamaModelInfoModel]]:
        """
        Detects if Ollama is installed and queries running status + models.
        Returns:
            Tuple[installed, running, list_of_models]
        """
        installed = shutil.which("ollama") is not None
        if not installed:
            user_ollama = os.path.expandvars(
                r"%LocalAppData%\Programs\Ollama\ollama.exe"
            )
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
                            format=details.get("format"),
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
                skip_dirs = {
                    ".git",
                    "node_modules",
                    "AppData",
                    "Local",
                    "Temp",
                    "Library",
                }
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
            gpu_info = self._gpu_detector.detect()
            if not gpu_info:
                gpu_info = [
                    GPUInfoModel(
                        name="No dedicated GPU detected",
                        status="unavailable",
                        source="registry",
                    )
                ]
        except Exception as e:
            logger.error(f"Error checking GPU information: {e}")
            gpu_info = [
                GPUInfoModel(
                    name="GPU check failed", status="error", source="system-api"
                )
            ]
            warnings.append(
                WarningItem(
                    component="gpu",
                    code="GPU_CHECK_FAILED",
                    message=f"GPU query failed: {str(e)}",
                )
            )
            status = "partial"

        # Ollama
        try:
            ollama_installed, ollama_running, ollama_models = self._get_ollama_details()
        except Exception as e:
            ollama_installed, ollama_running, ollama_models = False, False, []
            warnings.append(
                WarningItem(
                    component="ollama",
                    code="OLLAMA_CHECK_FAILED",
                    message=f"Ollama query failed: {str(e)}",
                )
            )
            status = "partial"

        # PyTorch Check
        pytorch_installed = False
        pytorch_version = None
        pytorch_cuda = None
        if _HAS_TORCH:
            try:
                pytorch_installed = True
                pytorch_version = str(torch.__version__)
                pytorch_cuda = torch.cuda.is_available()
            except Exception as e:
                logger.debug(f"Pytorch check failed: {e}")
                warnings.append(
                    WarningItem(
                        component="pytorch",
                        code="PYTORCH_CHECK_FAILED",
                        message=f"PyTorch check failed: {str(e)}",
                    )
                )
                status = "partial"

        # ONNX Runtime Check
        onnxruntime_installed = False
        onnxruntime_version = None
        onnxruntime_gpu = None
        if _HAS_ONNX:
            try:
                onnxruntime_installed = True
                onnxruntime_version = str(onnxruntime.__version__)
                providers = onnxruntime.get_available_providers()
                onnxruntime_gpu = (
                    "CUDAExecutionProvider" in providers
                    or "DmlExecutionProvider" in providers
                )
            except Exception as e:
                logger.debug(f"ONNX Runtime check failed: {e}")
                warnings.append(
                    WarningItem(
                        component="onnxruntime",
                        code="ONNXRUNTIME_CHECK_FAILED",
                        message=f"ONNX Runtime check failed: {str(e)}",
                    )
                )
                status = "partial"

        # Virtual Envs
        try:
            virtual_envs = self._detect_virtual_envs()
        except Exception as e:
            virtual_envs = []
            warnings.append(
                WarningItem(
                    component="virtualenv",
                    code="VIRTUALENV_CHECK_FAILED",
                    message=f"Virtualenv scanning failed: {str(e)}",
                )
            )
            status = "partial"

        # Local Models Inventory
        try:
            ollama_inv = self._ollama_detector.detect()
            if ollama_inv.warnings:
                for w in ollama_inv.warnings:
                    warnings.append(
                        WarningItem(
                            component="local_models",
                            code="OLLAMA_DISCOVERY_WARNING",
                            message=w,
                        )
                    )
                status = "partial"
        except Exception as e:
            ollama_inv = LocalModelInventoryModel(
                models=[],
                inventory_complete=False,
                truncated=False,
                warnings=[f"Failed to scan Ollama models: {str(e)}"],
            )
            warnings.append(
                WarningItem(
                    component="local_models",
                    code="OLLAMA_DISCOVERY_FAILED",
                    message=f"Ollama models scan failed: {str(e)}",
                )
            )
            status = "partial"

        try:
            lmstudio_inv = self._lmstudio_detector.detect()
            if lmstudio_inv.warnings:
                for w in lmstudio_inv.warnings:
                    warnings.append(
                        WarningItem(
                            component="local_models",
                            code="LMSTUDIO_DISCOVERY_WARNING",
                            message=w,
                        )
                    )
                status = "partial"
        except Exception as e:
            lmstudio_inv = LocalModelInventoryModel(
                models=[],
                inventory_complete=False,
                truncated=False,
                warnings=[f"Failed to scan LM Studio models: {str(e)}"],
            )
            warnings.append(
                WarningItem(
                    component="local_models",
                    code="LMSTUDIO_DISCOVERY_FAILED",
                    message=f"LM Studio scan failed: {str(e)}",
                )
            )
            status = "partial"

        local_models = LocalModelInventoryModel(
            models=ollama_inv.models + lmstudio_inv.models,
            inventory_complete=ollama_inv.inventory_complete
            and lmstudio_inv.inventory_complete,
            truncated=ollama_inv.truncated or lmstudio_inv.truncated,
            warnings=ollama_inv.warnings + lmstudio_inv.warnings,
        )

        try:
            docker_status = self._docker_detector.detect()
        except Exception as e:
            docker_status = DockerStatusModel(
                status="unknown", version=None, ai_containers=[]
            )
            warnings.append(
                WarningItem(
                    component="docker",
                    code="DOCKER_DISCOVERY_FAILED",
                    message=f"Docker discovery failed: {str(e)}",
                )
            )
            status = "partial"

        # Centralized path/warning sanitization at the data boundary
        virtual_envs = [sanitize_user_path(v) for v in virtual_envs]

        for m in local_models.models:
            if m.path:
                m.path = sanitize_user_path(m.path)
        local_models.warnings = [sanitize_user_path(w) for w in local_models.warnings]

        for w in warnings:
            if w.message:
                w.message = sanitize_user_path(w.message)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        metadata = CollectionMetadataModel(
            timestamp=time.time(),
            duration_ms=round(duration_ms, 2),
            status=status,
            warnings=warnings,
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
            collection_metadata=metadata,
            local_models=local_models,
            docker=docker_status,
        )
