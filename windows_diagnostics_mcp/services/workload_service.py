import math
import logging
from typing import List, Optional
import psutil

from ..models.workload import (
    WorkloadFitRequestModel,
    WorkloadMemoryEstimateModel,
    WorkloadMemoryEvidenceModel,
    WorkloadTargetAssessmentModel,
    WorkloadFitResponseModel,
)
from ..services.detectors.gpu_detector import GPUDetector

logger = logging.getLogger("machine-profile.services.workload")

MIN_RUNTIME_OVERHEAD_BYTES = 1_073_741_824
RUNTIME_OVERHEAD_PERCENT = 0.20
CONSERVATIVE_HOST_RESERVE_BYTES = 2_000_000_000

NOMINAL_BITS_MAPPING = {
    "fp32": 32.0,
    "fp16": 16.0,
    "bf16": 16.0,
    "int8": 8.0,
    "q8": 8.0,
    "q6": 6.0,
    "q5": 5.0,
    "q4": 4.0,
}


class WorkloadService:
    """
    Service for calculating AI workload footprint memory estimates and assessing
    hardware fit for local model deployment.
    """

    def __init__(self, gpu_detector: Optional[GPUDetector] = None):
        self._gpu_detector = gpu_detector or GPUDetector()

    def assess_workload(
        self, request: WorkloadFitRequestModel
    ) -> WorkloadFitResponseModel:
        warnings = []

        # 1. Resolve nominal bits per parameter
        if request.quantization == "custom":
            # bits_per_parameter is validated as not None and in [1.0, 32.0]
            nominal_bits_per_parameter = request.bits_per_parameter
        else:
            nominal_bits_per_parameter = NOMINAL_BITS_MAPPING[request.quantization]

        # 2. Add warning if context_length is supplied
        if request.context_length is not None:
            warnings.append(
                "Context length is not included in the deterministic memory estimate because "
                "model architecture and KV-cache configuration are unknown."
            )

        # 3. Calculate model weight and overhead footprint with ceil rounding
        raw_weight_bytes = math.ceil(
            request.parameter_count_billions
            * 1_000_000_000
            * nominal_bits_per_parameter
            / 8
        )

        runtime_overhead_bytes = math.ceil(
            max(
                MIN_RUNTIME_OVERHEAD_BYTES,
                raw_weight_bytes * RUNTIME_OVERHEAD_PERCENT,
            )
        )

        estimated_required_bytes = raw_weight_bytes + runtime_overhead_bytes

        safety_margin_percent = (
            request.safety_margin_percent
            if request.safety_margin_percent is not None
            else 20.0
        )
        safety_margin_bytes = math.ceil(
            estimated_required_bytes * safety_margin_percent / 100
        )

        estimated_required_with_margin_bytes = (
            estimated_required_bytes + safety_margin_bytes
        )

        assumptions = {
            "nominal_bits_per_parameter": nominal_bits_per_parameter,
            "idealized_quantization": True,
            "idealized_quantization_details": (
                "Nominal bits-per-parameter mappings are idealized and do not account for block metadata, "
                "mixed-precision, scale/zero-point parameters, alignment offsets, or framework-specific storage overhead."
            ),
            "heuristic_runtime_overhead": True,
            "heuristic_runtime_overhead_details": (
                f"Runtime overhead is estimated as a conservative baseline using a minimum threshold of {MIN_RUNTIME_OVERHEAD_BYTES} bytes "
                f"and {int(RUNTIME_OVERHEAD_PERCENT * 100)}% of raw model weights."
            ),
            "kv_cache_modeled": False,
            "activation_memory_modeled": False,
            "allocator_fragmentation_modeled": False,
            "inference_engine_overhead_modeled": False,
            "multi_gpu_parallelism_modeled": False,
            "conservative_host_reserve_bytes": CONSERVATIVE_HOST_RESERVE_BYTES,
        }

        estimate = WorkloadMemoryEstimateModel(
            nominal_bits_per_parameter=nominal_bits_per_parameter,
            raw_weight_bytes=raw_weight_bytes,
            runtime_overhead_bytes=runtime_overhead_bytes,
            safety_margin_bytes=safety_margin_bytes,
            estimated_required_bytes=estimated_required_bytes,
            estimated_required_with_margin_bytes=estimated_required_with_margin_bytes,
            assumptions=assumptions,
        )

        gpu_assessments: List[WorkloadTargetAssessmentModel] = []
        cpu_assessment: Optional[WorkloadTargetAssessmentModel] = None

        # 4. Assess GPU Targets if target_backend is "gpu" or "auto"
        if request.target_backend in ("gpu", "auto"):
            try:
                gpus = self._gpu_detector.detect()
                for gpu in gpus:
                    # Case A: observed free VRAM
                    if gpu.source == "nvidia-smi" and gpu.memory_free is not None:
                        free_bytes = gpu.memory_free * 1024 * 1024
                        total_bytes = gpu.dedicated_vram_bytes or (
                            gpu.vram_mb * 1024 * 1024 if gpu.vram_mb else None
                        )

                        evidence = WorkloadMemoryEvidenceModel(
                            evidence_type="observed_free_memory",
                            available_memory_bytes=free_bytes,
                            total_capacity_bytes=total_bytes,
                            source=gpu.source,
                        )

                        # Determine fit status
                        if estimated_required_with_margin_bytes <= free_bytes:
                            current_fit = "fits"
                            explanation = (
                                f"Workload fits within the GPU's available free VRAM ({gpu.memory_free} MB) "
                                f"with the requested {safety_margin_percent}% safety margin."
                            )
                        elif estimated_required_bytes <= free_bytes:
                            current_fit = "marginal"
                            explanation = (
                                f"Workload fits within the GPU's available free VRAM ({gpu.memory_free} MB) "
                                f"but falls within the requested {safety_margin_percent}% safety margin buffer."
                            )
                        else:
                            current_fit = "does_not_fit"
                            explanation = f"Workload does not fit within the GPU's available free VRAM ({gpu.memory_free} MB)."

                        capacity_fit = None
                        if total_bytes is not None:
                            if estimated_required_with_margin_bytes <= total_bytes:
                                capacity_fit = "fits"
                            elif estimated_required_bytes <= total_bytes:
                                capacity_fit = "marginal"
                            else:
                                capacity_fit = "does_not_fit"

                        gpu_assessments.append(
                            WorkloadTargetAssessmentModel(
                                backend="gpu",
                                device_name=gpu.name,
                                memory_evidence=evidence,
                                current_fit_status=current_fit,
                                capacity_fit_status=capacity_fit,
                                explanation=explanation,
                            )
                        )

                    # Case B: total capacity only
                    elif (
                        gpu.dedicated_vram_bytes is not None or gpu.vram_mb is not None
                    ):
                        total_bytes = gpu.dedicated_vram_bytes or (
                            gpu.vram_mb * 1024 * 1024 if gpu.vram_mb else None
                        )

                        evidence = WorkloadMemoryEvidenceModel(
                            evidence_type="total_capacity_only",
                            available_memory_bytes=None,
                            total_capacity_bytes=total_bytes,
                            source=gpu.source,
                        )

                        capacity_fit = None
                        if total_bytes is not None:
                            if estimated_required_with_margin_bytes <= total_bytes:
                                capacity_fit = "fits"
                            elif estimated_required_bytes <= total_bytes:
                                capacity_fit = "marginal"
                            else:
                                capacity_fit = "does_not_fit"

                        explanation = (
                            f"GPU free memory could not be dynamically monitored. Total dedicated capacity is "
                            f"{total_bytes // (1024*1024)} MB (Capacity fit status: '{capacity_fit}')."
                        )

                        gpu_assessments.append(
                            WorkloadTargetAssessmentModel(
                                backend="gpu",
                                device_name=gpu.name,
                                memory_evidence=evidence,
                                current_fit_status="unknown",
                                capacity_fit_status=capacity_fit,
                                explanation=explanation,
                            )
                        )

                    # Case C: no memory evidence
                    else:
                        evidence = WorkloadMemoryEvidenceModel(
                            evidence_type="unavailable",
                            available_memory_bytes=None,
                            total_capacity_bytes=None,
                            source=gpu.source,
                        )

                        gpu_assessments.append(
                            WorkloadTargetAssessmentModel(
                                backend="gpu",
                                device_name=gpu.name,
                                memory_evidence=evidence,
                                current_fit_status="unknown",
                                capacity_fit_status=None,
                                explanation="GPU memory telemetry is completely unavailable.",
                            )
                        )
            except Exception as e:
                logger.error(f"Error querying GPU list during workload assessment: {e}")
                # Fallback empty GPU assessments list is preserved

        # 5. Assess CPU Target if target_backend is "cpu" or "auto"
        if request.target_backend in ("cpu", "auto"):
            try:
                mem = psutil.virtual_memory()
                available_ram = mem.available
                total_ram = mem.total

                usable_ram = max(0, available_ram - CONSERVATIVE_HOST_RESERVE_BYTES)

                evidence = WorkloadMemoryEvidenceModel(
                    evidence_type="observed_available_system_memory",
                    available_memory_bytes=usable_ram,
                    total_capacity_bytes=total_ram,
                    source="psutil",
                )

                if estimated_required_with_margin_bytes <= usable_ram:
                    current_fit = "fits"
                    explanation = (
                        f"Workload fits within the host's usable system RAM ({usable_ram // (1024*1024)} MB available "
                        f"after preserving a {CONSERVATIVE_HOST_RESERVE_BYTES // (1024*1024)} MB host reserve) "
                        f"with the requested {safety_margin_percent}% safety margin."
                    )
                elif estimated_required_bytes <= usable_ram:
                    current_fit = "marginal"
                    explanation = (
                        f"Workload fits within the host's usable system RAM ({usable_ram // (1024*1024)} MB available) "
                        f"but falls within the requested {safety_margin_percent}% safety margin buffer."
                    )
                else:
                    current_fit = "does_not_fit"
                    explanation = f"Workload does not fit within host usable system RAM ({usable_ram // (1024*1024)} MB available)."

                cpu_assessment = WorkloadTargetAssessmentModel(
                    backend="cpu",
                    device_name="System CPU",
                    memory_evidence=evidence,
                    current_fit_status=current_fit,
                    capacity_fit_status=None,
                    explanation=explanation,
                )
            except Exception as e:
                logger.error(
                    f"Error querying CPU system memory during workload assessment: {e}"
                )
                evidence = WorkloadMemoryEvidenceModel(
                    evidence_type="unavailable",
                    available_memory_bytes=None,
                    total_capacity_bytes=None,
                    source="psutil",
                )
                cpu_assessment = WorkloadTargetAssessmentModel(
                    backend="cpu",
                    device_name="System CPU",
                    memory_evidence=evidence,
                    current_fit_status="unknown",
                    capacity_fit_status=None,
                    explanation=f"Failed to query system memory metrics: {e}",
                )

        # 6. Target Selection and consolidated outcomes
        selected_target = None
        overall_fit_status = "unknown"
        selection_reason = ""

        # EXPLICIT CPU MODE
        if request.target_backend == "cpu":
            if cpu_assessment:
                if cpu_assessment.current_fit_status in ("fits", "marginal"):
                    selected_target = cpu_assessment
                    overall_fit_status = cpu_assessment.current_fit_status
                    selection_reason = f"Explicit CPU backend target selected. CPU assessment status: '{overall_fit_status}'."
                elif cpu_assessment.current_fit_status == "does_not_fit":
                    selected_target = None
                    overall_fit_status = "does_not_fit"
                    selection_reason = (
                        "Explicit CPU backend target requested but CPU does not fit."
                    )
                else:
                    selected_target = None
                    overall_fit_status = "unknown"
                    selection_reason = "Explicit CPU backend target requested but CPU availability is unknown."

        # EXPLICIT GPU MODE
        elif request.target_backend == "gpu":
            if not gpu_assessments:
                selected_target = None
                overall_fit_status = "unknown"
                selection_reason = (
                    "Explicit GPU backend target requested but no GPU was discovered."
                )
            else:
                # Build eligible GPU candidates
                eligible_gpu_candidates = []
                for idx, assess in enumerate(gpu_assessments):
                    if assess.current_fit_status in ("fits", "marginal"):
                        fit_pri = 2 if assess.current_fit_status == "fits" else 1
                        headroom = (
                            assess.memory_evidence.available_memory_bytes or 0
                        ) - estimated_required_with_margin_bytes
                        eligible_gpu_candidates.append(
                            {
                                "assessment": assess,
                                "fit_priority": fit_pri,
                                "headroom": headroom,
                                "index": idx,
                            }
                        )

                if eligible_gpu_candidates:
                    # Sort by fit priority desc, headroom desc, and index desc (smaller index wins via reverse sorting)
                    eligible_gpu_candidates.sort(
                        key=lambda x: (x["fit_priority"], x["headroom"], -x["index"]),
                        reverse=True,
                    )
                    best_cand = eligible_gpu_candidates[0]
                    selected_target = best_cand["assessment"]
                    overall_fit_status = selected_target.current_fit_status
                    selection_reason = f"Selected GPU '{selected_target.device_name}' based on best fit status and VRAM headroom."
                else:
                    selected_target = None
                    # If all GPUs are does_not_fit and none is unknown
                    all_does_not_fit = all(
                        a.current_fit_status == "does_not_fit" for a in gpu_assessments
                    )
                    if all_does_not_fit:
                        overall_fit_status = "does_not_fit"
                        selection_reason = "All discovered GPUs do not fit the estimated workload requirement."
                    else:
                        overall_fit_status = "unknown"
                        selection_reason = "Could not determine GPU fit because one or more GPUs have unknown current VRAM availability."

        # AUTO TARGET SELECTION
        else:
            # Build eligible candidates from both GPU and CPU assessments
            viable_candidates = []

            # Add GPU assessments (index starts at 0)
            for idx, assess in enumerate(gpu_assessments):
                if assess.current_fit_status in ("fits", "marginal"):
                    fit_pri = 2 if assess.current_fit_status == "fits" else 1
                    headroom = (
                        assess.memory_evidence.available_memory_bytes or 0
                    ) - estimated_required_with_margin_bytes
                    viable_candidates.append(
                        {
                            "assessment": assess,
                            "fit_priority": fit_pri,
                            "headroom": headroom,
                            "index": idx,
                        }
                    )

            # Add CPU assessment (index = len(gpu_assessments))
            cpu_idx = len(gpu_assessments)
            if cpu_assessment and cpu_assessment.current_fit_status in (
                "fits",
                "marginal",
            ):
                fit_pri = 2 if cpu_assessment.current_fit_status == "fits" else 1
                headroom = (
                    cpu_assessment.memory_evidence.available_memory_bytes or 0
                ) - estimated_required_with_margin_bytes
                viable_candidates.append(
                    {
                        "assessment": cpu_assessment,
                        "fit_priority": fit_pri,
                        "headroom": headroom,
                        "index": cpu_idx,
                    }
                )

            if viable_candidates:
                # Rank candidates
                viable_candidates.sort(
                    key=lambda x: (x["fit_priority"], x["headroom"], -x["index"]),
                    reverse=True,
                )
                best_cand = viable_candidates[0]
                selected_target = best_cand["assessment"]
                overall_fit_status = selected_target.current_fit_status
                selection_reason = (
                    f"Selected target '{selected_target.device_name}' ({selected_target.backend}) "
                    f"based on best fit priority and memory headroom."
                )
            else:
                selected_target = None
                # Check if all assessed targets are does_not_fit
                all_targets = list(gpu_assessments)
                if cpu_assessment:
                    all_targets.append(cpu_assessment)

                if not all_targets:
                    overall_fit_status = "unknown"
                    selection_reason = (
                        "No hardware targets were available for assessment."
                    )
                else:
                    all_does_not_fit = all(
                        t.current_fit_status == "does_not_fit" for t in all_targets
                    )
                    if all_does_not_fit:
                        overall_fit_status = "does_not_fit"
                        selection_reason = "No target backend (GPU or CPU) fits the estimated workload requirement."
                    else:
                        overall_fit_status = "unknown"
                        selection_reason = "Could not determine target fit because one or more backends have unknown current memory availability."

        return WorkloadFitResponseModel(
            request=request,
            estimate=estimate,
            gpu_assessments=gpu_assessments,
            cpu_assessment=cpu_assessment,
            selected_target=selected_target,
            overall_fit_status=overall_fit_status,
            selection_reason=selection_reason,
            warnings=warnings,
        )
