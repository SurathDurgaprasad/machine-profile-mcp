from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from .metadata import CollectionMetadataModel
from .system import CapabilityStatusModel


class GPUInfoModel(BaseModel):
    name: str
    vendor: Optional[str] = None
    vram_mb: Optional[int] = None
    adapter_type: str = "unknown"  # "integrated" | "discrete" | "virtual" | "unknown"
    dedicated_vram_bytes: Optional[int] = None
    shared_memory_bytes: Optional[int] = None
    status: str  # "available", "unavailable", "unsupported", "error"
    source: str  # "nvidia-smi", "registry", "system-api", "command", "other"
    driver_version: Optional[str] = None
    memory_used: Optional[int] = None  # in MB
    memory_free: Optional[int] = None  # in MB


class OllamaModelInfoModel(BaseModel):
    name: str
    size: int
    family: Optional[str] = None
    format: Optional[str] = None


class LocalModelItem(BaseModel):
    name: str = Field(..., description="Standard model name identifier")
    provider: Literal["ollama", "lm-studio", "other"] = Field(
        ..., description="Local AI engine runtime provider"
    )
    format: Literal["gguf", "ollama-manifest", "unknown"] = Field(
        ..., description="File formatting type"
    )
    path: Optional[str] = Field(
        default=None, description="Sanitized relative model filepath"
    )
    size_bytes: Optional[int] = Field(
        default=None, description="Logical referenced model size in bytes"
    )
    quantization: Optional[str] = Field(
        default=None, description="Quantization format (inferred unless verified)"
    )
    detection_source: Literal["http-api", "filesystem-scan"] = Field(
        ..., description="Method used to detect model"
    )
    metadata_source: Literal["manifest-json", "filename-parse"] = Field(
        ..., description="Source of model metadata"
    )
    confidence: Literal["authoritative", "inferred"] = Field(
        ..., description="Reliability score of metadata"
    )


class DockerContainerInfo(BaseModel):
    name: str = Field(..., description="Container name")
    image: str = Field(..., description="Container image tag")
    status: str = Field(..., description="Runtime status description")


class DockerStatusModel(BaseModel):
    status: Literal[
        "not_installed",
        "daemon_running",
        "daemon_unavailable",
        "timeout",
        "permission_or_context_error",
        "unknown",
    ] = Field(..., description="Detailed Docker daemon execution status")
    version: Optional[str] = Field(default=None, description="Docker CLI version")
    ai_containers: List[DockerContainerInfo] = Field(
        default_factory=list, description="Running AI-related container details"
    )


class LocalModelInventoryModel(BaseModel):
    models: List[LocalModelItem] = Field(
        default_factory=list, description="Discovered local models list"
    )
    inventory_complete: bool = Field(
        default=True,
        description="False if directory scanning hit safety limits or errored",
    )
    truncated: bool = Field(
        default=False, description="True if scanning hit max file or depth limits"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Encountered warning strings during traversal"
    )


class AcceleratorRuntimeEvidenceModel(BaseModel):
    cuda_driver_library_present: CapabilityStatusModel = Field(
        default_factory=lambda: CapabilityStatusModel(
            supported=None, status="unknown", source="none", detail=None
        ),
        description="Passive check of CUDA Driver API library presence (nvcuda.dll)",
    )
    d3d12_runtime_library_present: CapabilityStatusModel = Field(
        default_factory=lambda: CapabilityStatusModel(
            supported=None, status="unknown", source="none", detail=None
        ),
        description="Passive check of D3D12 runtime library presence (d3d12.dll)",
    )
    system_directml_library_present: CapabilityStatusModel = Field(
        default_factory=lambda: CapabilityStatusModel(
            supported=None, status="unknown", source="none", detail=None
        ),
        description="Passive check of system-provided DirectML library presence (directml.dll)",
    )


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
    local_models: LocalModelInventoryModel = Field(
        default_factory=LocalModelInventoryModel,
        description="Offline and active local model inventory",
    )
    docker: Optional[DockerStatusModel] = Field(
        default=None, description="Docker daemon and containerized AI status"
    )
    accelerator_evidence: AcceleratorRuntimeEvidenceModel = Field(
        default_factory=AcceleratorRuntimeEvidenceModel,
        description="Environment-level passive accelerator runtime evidence",
    )
