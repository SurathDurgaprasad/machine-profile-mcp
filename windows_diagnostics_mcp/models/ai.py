from pydantic import BaseModel
from typing import List, Optional
from .metadata import CollectionMetadataModel

class GPUInfoModel(BaseModel):
    name: str
    vendor: Optional[str] = None
    vram_mb: Optional[int] = None
    status: str  # "available", "unavailable", "unsupported", "error"
    source: str  # "nvidia-smi", "registry", "system-api", "command", "other"
    driver_version: Optional[str] = None
    memory_used: Optional[int] = None   # in MB
    memory_free: Optional[int] = None   # in MB

class OllamaModelInfoModel(BaseModel):
    name: str
    size: int
    family: Optional[str] = None
    format: Optional[str] = None

class AIEnvStatusModel(BaseModel):
    gpu: List[GPUInfoModel]
    ollama_installed: bool
    ollama_running: bool
    ollama_models: List[OllamaModelInfoModel]
    pytorch_installed: bool
    pytorch_version: Optional[str] = None
    pytorch_cuda_available: Optional[bool] = None
    onnxruntime_installed: bool
    onnxruntime_version: Optional[str] = None
    onnxruntime_gpu_available: Optional[bool] = None
    python_virtual_environments: List[str]
    collection_metadata: CollectionMetadataModel
