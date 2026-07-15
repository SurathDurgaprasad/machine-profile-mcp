from pydantic import BaseModel, Field
from typing import Optional, Literal
from .metadata import CollectionMetadataModel


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
