from typing import Optional
from mcp.server.fastmcp import FastMCP
from ..services.workload_service import WorkloadService
from ..models.workload import WorkloadFitRequestModel, WorkloadFitResponseModel


def register_workload_tools(mcp: FastMCP, workload_service: WorkloadService):
    """
    Registers the assess_workload_fit tool on FastMCP.
    """

    @mcp.tool(
        name="assess_workload_fit",
        description="Calculate estimated model memory footprint and evaluate target deployment viability (fits, marginal, does_not_fit) on available CPU and GPU hardware backends.",
    )
    def assess_workload_fit(
        parameter_count_billions: float,
        quantization: str,
        bits_per_parameter: Optional[float] = None,
        context_length: Optional[int] = None,
        target_backend: str = "auto",
        safety_margin_percent: Optional[float] = 20.0,
    ) -> WorkloadFitResponseModel:
        request = WorkloadFitRequestModel(
            parameter_count_billions=parameter_count_billions,
            quantization=quantization,
            bits_per_parameter=bits_per_parameter,
            context_length=context_length,
            target_backend=target_backend,
            safety_margin_percent=safety_margin_percent,
        )
        return workload_service.assess_workload(request)
