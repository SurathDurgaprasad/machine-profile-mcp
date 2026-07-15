from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Literal, Dict, Any


class WorkloadFitRequestModel(BaseModel):
    parameter_count_billions: float = Field(
        ..., gt=0.0, description="Model parameter count in billions"
    )
    quantization: Literal[
        "fp32",
        "fp16",
        "bf16",
        "int8",
        "q8",
        "q6",
        "q5",
        "q4",
        "custom",
    ] = Field(..., description="Nominal quantization type")
    bits_per_parameter: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=32.0,
        description="Bits per parameter (required only for custom quantization)",
    )
    context_length: Optional[int] = Field(
        default=None,
        ge=512,
        le=131072,
        description="Informational target context length",
    )
    target_backend: Literal["auto", "gpu", "cpu"] = Field(
        default="auto", description="Target execution backend selection"
    )
    safety_margin_percent: Optional[float] = Field(
        default=20.0,
        ge=0.0,
        le=100.0,
        description="Safety reserve margin percentage",
    )

    @model_validator(mode="after")
    def validate_quantization_bits(self) -> "WorkloadFitRequestModel":
        if self.quantization == "custom":
            if self.bits_per_parameter is None:
                raise ValueError(
                    "bits_per_parameter is required when quantization is 'custom'."
                )
        else:
            if self.bits_per_parameter is not None:
                raise ValueError(
                    f"bits_per_parameter must not be supplied when using predefined quantization '{self.quantization}'."
                )
        return self


class WorkloadMemoryEstimateModel(BaseModel):
    nominal_bits_per_parameter: float = Field(
        ..., description="Resolved nominal bits per parameter"
    )
    raw_weight_bytes: int = Field(
        ..., description="Estimated raw model weight size in bytes"
    )
    runtime_overhead_bytes: int = Field(
        ..., description="Estimated runtime execution overhead in bytes"
    )
    safety_margin_bytes: int = Field(
        ..., description="Estimated safety margin size in bytes"
    )
    estimated_required_bytes: int = Field(
        ..., description="Estimated required memory footprint (raw + overhead)"
    )
    estimated_required_with_margin_bytes: int = Field(
        ..., description="Estimated memory footprint with safety margin"
    )
    assumptions: Dict[str, Any] = Field(
        ..., description="Machine-readable estimation assumptions"
    )


class WorkloadMemoryEvidenceModel(BaseModel):
    evidence_type: Literal[
        "observed_free_memory",
        "total_capacity_only",
        "observed_available_system_memory",
        "unavailable",
    ] = Field(..., description="Source class of memory data")
    available_memory_bytes: Optional[int] = Field(
        default=None,
        description="Usable available memory bytes for the fit decision",
    )
    total_capacity_bytes: Optional[int] = Field(
        default=None, description="Reported hardware limit in bytes"
    )
    source: str = Field(..., description="Underlying telemetry source description")


class WorkloadTargetAssessmentModel(BaseModel):
    backend: Literal["gpu", "cpu"] = Field(..., description="Target execution backend")
    device_name: Optional[str] = Field(
        default=None, description="Physical hardware identifier"
    )
    memory_evidence: WorkloadMemoryEvidenceModel = Field(
        ..., description="Telemetry evidence details"
    )
    current_fit_status: Literal["fits", "marginal", "does_not_fit", "unknown"] = Field(
        ..., description="Assessment using currently available memory"
    )
    capacity_fit_status: Optional[Literal["fits", "marginal", "does_not_fit"]] = Field(
        default=None,
        description="Advisory assessment using total device capacity",
    )
    explanation: str = Field(..., description="Human-readable assessment explanation")


class WorkloadFitResponseModel(BaseModel):
    request: WorkloadFitRequestModel = Field(..., description="Assessment inputs")
    estimate: WorkloadMemoryEstimateModel = Field(
        ..., description="Calculated model footprint estimate"
    )
    gpu_assessments: List[WorkloadTargetAssessmentModel] = Field(
        default_factory=list, description="Independent GPU fit outcomes"
    )
    cpu_assessment: Optional[WorkloadTargetAssessmentModel] = Field(
        default=None, description="Independent CPU fit outcome"
    )
    selected_target: Optional[WorkloadTargetAssessmentModel] = Field(
        default=None, description="Final recommended target"
    )
    overall_fit_status: Literal["fits", "marginal", "does_not_fit", "unknown"] = Field(
        ..., description="Consolidated fit status outcome"
    )
    selection_reason: str = Field(
        ..., description="Detailed explanation of the target selection decision"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Non-blocking warning item logs"
    )
