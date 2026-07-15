from pydantic import BaseModel, Field
from typing import Optional, Literal
from .metadata import CollectionMetadataModel


class CapabilityStatusModel(BaseModel):
    supported: Optional[bool] = Field(
        default=None,
        description="True if supported, False if not supported, None if unknown/could not be determined",
    )
    status: Literal["available", "unavailable", "unknown", "error"] = Field(
        default="unknown",
        description="Small vocabulary of support status: available, unavailable, unknown, error",
    )
    source: Optional[str] = Field(
        default=None, description="Probing method or source used"
    )
    detail: Optional[str] = Field(
        default=None, description="Additional technical detail or error message if any"
    )


class CPUInfoModel(BaseModel):
    model: str = Field(
        ..., description="Exact marketing CPU name (e.g. Intel Core i7-10700K)"
    )
    vendor: str = Field(
        ..., description="CPU vendor identifier (e.g. GenuineIntel, AuthenticAMD)"
    )
    architecture: str = Field(
        ..., description="Instruction set architecture (e.g. AMD64, ARM64)"
    )
    physical_cores: Optional[int] = Field(
        default=None, description="Number of physical hardware cores"
    )
    logical_processors: Optional[int] = Field(
        default=None, description="Number of logical processor threads"
    )
    max_frequency_mhz: Optional[int] = Field(
        default=None, description="Maximum CPU frequency in MHz"
    )
    avx_support: CapabilityStatusModel = Field(
        default_factory=lambda: CapabilityStatusModel(
            supported=None, status="unknown", source="none"
        )
    )
    avx2_support: CapabilityStatusModel = Field(
        default_factory=lambda: CapabilityStatusModel(
            supported=None, status="unknown", source="none"
        )
    )
    avx512f_support: CapabilityStatusModel = Field(
        default_factory=lambda: CapabilityStatusModel(
            supported=None, status="unknown", source="none"
        )
    )
    status: Literal["available", "partial", "error"] = Field(
        ..., description="Capability status"
    )


class SystemSummaryModel(BaseModel):
    edition: str
    version: str
    build_number: str
    architecture: str
    hostname: str
    username: str
    uptime_seconds: float
    uptime_formatted: str
    collection_metadata: CollectionMetadataModel
    cpu: Optional[CPUInfoModel] = Field(
        default=None, description="Detailed CPU capability profiling"
    )
