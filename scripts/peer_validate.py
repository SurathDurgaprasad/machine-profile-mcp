import sys
import os
import json
import platform
import traceback


def run_validation():
    # Enable anonymization at the boundary
    os.environ["MACHINE_PROFILE_ANONYMIZE"] = "true"

    report = {
        "validation_metadata": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "anonymize_enabled": os.environ.get("MACHINE_PROFILE_ANONYMIZE") == "true",
        },
        "system": {},
        "cpu": {},
        "gpus": [],
        "ollama": {},
        "lm_studio": {},
        "docker": {},
        "mcp": {
            "import_success": False,
            "site_packages_verified": False,
            "import_path": None,
            "error": None,
        },
        "warnings": [],
        "overall_status": "FAIL",
    }

    try:
        # Import the installed package
        import windows_diagnostics_mcp
        from windows_diagnostics_mcp.services.utils import sanitize_user_path

        report["mcp"]["import_success"] = True
        report["mcp"]["import_path"] = sanitize_user_path(
            windows_diagnostics_mcp.__file__
        )

        # Verify that it is loaded from site-packages (or dist-packages)
        is_site_packages = (
            "site-packages" in windows_diagnostics_mcp.__file__
            or "dist-packages" in windows_diagnostics_mcp.__file__
        )
        report["mcp"]["site_packages_verified"] = is_site_packages

        # Instantiate services
        from windows_diagnostics_mcp.services.system_service import SystemService
        from windows_diagnostics_mcp.services.ai_service import AIService

        sys_service = SystemService()
        ai_service = AIService()

        # Collect system & CPU info
        sys_summary = sys_service.get_system_summary()
        report["system"] = {
            "edition": sys_summary.edition,
            "version": sys_summary.version,
            "build_number": sys_summary.build_number,
            "architecture": sys_summary.architecture,
            "uptime_seconds": sys_summary.uptime_seconds,
            "collection_status": sys_summary.collection_metadata.status,
        }

        if sys_summary.cpu:
            report["cpu"] = {
                "model": sys_summary.cpu.model,
                "vendor": sys_summary.cpu.vendor,
                "architecture": sys_summary.cpu.architecture,
                "physical_cores": sys_summary.cpu.physical_cores,
                "logical_processors": sys_summary.cpu.logical_processors,
                "max_frequency_mhz": sys_summary.cpu.max_frequency_mhz,
                "status": sys_summary.cpu.status,
            }

        # Collect AI environment info (GPU, Ollama, LM Studio, Docker)
        ai_env = ai_service.get_ai_environment()

        # GPUs
        for gpu in ai_env.gpu:
            report["gpus"].append(
                {
                    "name": gpu.name,
                    "vendor": gpu.vendor,
                    "vram_mb": gpu.vram_mb,
                    "adapter_type": gpu.adapter_type,
                    "dedicated_vram_bytes": gpu.dedicated_vram_bytes,
                    "source": gpu.source,
                    "status": gpu.status,
                }
            )

        # Ollama
        report["ollama"] = {
            "installed": ai_env.ollama_installed,
            "running": ai_env.ollama_running,
            "active_models_count": len(ai_env.ollama_models),
        }

        # Model discovery separation
        if ai_env.local_models:
            ollama_discovered = []
            lmstudio_discovered = []
            for m in ai_env.local_models.models:
                item = {
                    "name": m.name,
                    "format": m.format,
                    "size_bytes": m.size_bytes,
                    "quantization": m.quantization,
                    "detection_source": m.detection_source,
                    "confidence": m.confidence,
                }
                if m.provider == "ollama":
                    ollama_discovered.append(item)
                elif m.provider == "lm-studio":
                    lmstudio_discovered.append(item)

            report["ollama"]["offline_models_discovered"] = ollama_discovered
            report["lm_studio"] = {
                "offline_models_discovered": lmstudio_discovered,
                "inventory_complete": ai_env.local_models.inventory_complete,
                "truncated": ai_env.local_models.truncated,
            }
            if ai_env.local_models.warnings:
                report["warnings"].extend(ai_env.local_models.warnings)

        # Docker
        if ai_env.docker:
            report["docker"] = {
                "status": ai_env.docker.status,
                "version": ai_env.docker.version,
                "ai_containers": [
                    {"name": c.name, "image": c.image, "status": c.status}
                    for c in ai_env.docker.ai_containers
                ],
            }

        if sys_summary.collection_metadata.warnings:
            report["warnings"].extend(sys_summary.collection_metadata.warnings)
        if ai_env.collection_metadata.warnings:
            report["warnings"].extend(ai_env.collection_metadata.warnings)

        # Determine overall status: Succeeded discovery is a PASS, not dependent on dependencies presence
        report["overall_status"] = "PASS"

    except Exception as e:
        report["overall_status"] = "FAIL"
        report["mcp"]["error"] = f"{type(e).__name__}: {str(e)}"
        report["warnings"].append(traceback.format_exc())

    # Write JSON report
    report_file = "machine_profile_peer_validation.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Validation completed. Report written to: {report_file}")
    print(f"Overall Status: {report['overall_status']}")


if __name__ == "__main__":
    run_validation()
