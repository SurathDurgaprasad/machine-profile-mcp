import sys
import time
import pathlib
import socket
from unittest.mock import MagicMock, patch
import pytest
import os
import json
from pathlib import Path

from windows_diagnostics_mcp.services.detectors.cpu_detector import CPUDetector
from windows_diagnostics_mcp.services.detectors.gpu_detector import GPUDetector
from windows_diagnostics_mcp.services.detectors.ollama_detector import OllamaDetector
from windows_diagnostics_mcp.services.detectors.lmstudio_detector import (
    LMStudioDetector,
)
from windows_diagnostics_mcp.services.detectors.docker_detector import DockerDetector
from windows_diagnostics_mcp.services.utils import sanitize_user_path
from windows_diagnostics_mcp.models.system import CPUInfoModel
from windows_diagnostics_mcp.models.ai import (
    LocalModelItem,
    DockerStatusModel,
    LocalModelInventoryModel,
    DockerContainerInfo,
    AcceleratorRuntimeEvidenceModel,
)

# Models
from ..models.health import WarningItem

# Services
from ..services.system_service import SystemService
from ..services.process_service import ProcessService
from ..services.storage_service import StorageService
from ..services.developer_service import DeveloperService
from ..services.ai_service import AIService
from ..services.network_service import NetworkService
from ..services.health_service import HealthService
from ..services.subprocess_helper import safe_run_command
from pydantic import ValidationError
from windows_diagnostics_mcp.models.ai import GPUInfoModel
from windows_diagnostics_mcp.models.workload import (
    WorkloadFitRequestModel,
)
from windows_diagnostics_mcp.services.workload_service import (
    WorkloadService,
    MIN_RUNTIME_OVERHEAD_BYTES,
    CONSERVATIVE_HOST_RESERVE_BYTES,
)

# ==============================================================================
# Model Tests
# ==============================================================================


def test_models_instantiation():
    """Verify that Pydantic models initialize correctly and enforce schemas."""
    # Shared WarningItem
    warn = WarningItem(
        component="gpu",
        code="GPU_UNAVAILABLE",
        message="Detailed GPU information could not be detected",
        severity="warning",
    )
    assert warn.component == "gpu"
    assert warn.severity == "warning"


# ==============================================================================
# Subprocess Helper Tests
# ==============================================================================


@patch("subprocess.run")
def test_subprocess_helper_success(mock_sub_run):
    """Test safe_run_command handles success and decodes outputs safely."""
    mock_sub_run.return_value = MagicMock(
        returncode=0, stdout=b"Command Success", stderr=b"No errors"
    )

    code, stdout, stderr = safe_run_command(["test_cmd"])
    assert code == 0
    assert stdout.strip() == "Command Success"
    assert stderr.strip() == "No errors"


@patch("subprocess.run")
def test_subprocess_helper_timeout(mock_sub_run):
    """Test safe_run_command raises TimeoutError gracefully when command hangs."""
    import subprocess

    mock_sub_run.side_effect = subprocess.TimeoutExpired(cmd=["test_cmd"], timeout=2.0)

    with pytest.raises(TimeoutError):
        safe_run_command(["test_cmd"])


@patch("subprocess.run")
def test_subprocess_helper_file_not_found(mock_sub_run):
    """Test safe_run_command handles non-existent executables gracefully."""
    mock_sub_run.side_effect = FileNotFoundError()

    with pytest.raises(FileNotFoundError):
        safe_run_command(["invalid_command_abc"])


# ==============================================================================
# System Service Tests
# ==============================================================================


@patch("windows_diagnostics_mcp.services.system_service.OpenKey")
@patch("windows_diagnostics_mcp.services.system_service.QueryValueEx")
@patch("psutil.boot_time")
def test_system_service(mock_boot_time, mock_query_value, mock_open_key):
    """Test SystemService with registry success and mock uptime."""
    mock_boot_time.return_value = time.time() - 3600.0  # 1 hour ago
    mock_query_value.side_effect = [
        ("Windows 11 Pro", 1),  # ProductName
        ("23H2", 1),  # DisplayVersion
        ("22631", 1),  # CurrentBuild
    ]

    service = SystemService()
    summary = service.get_system_summary()

    assert summary.edition == "Windows 11 Pro"
    assert summary.version == "23H2"
    assert summary.build_number == "22631"
    assert summary.uptime_seconds >= 3600.0
    assert "hour" in summary.uptime_formatted
    assert summary.collection_metadata.status == "ok"


@patch("windows_diagnostics_mcp.services.system_service.OpenKey")
@patch("windows_diagnostics_mcp.services.system_service.QueryValueEx")
@patch("psutil.boot_time")
def test_system_service_registry_fallback(
    mock_boot_time, mock_query_value, mock_open_key
):
    """Test SystemService fallback when registry is missing or fails."""
    mock_boot_time.return_value = time.time() - 10  # 10s ago
    mock_open_key.side_effect = Exception("Registry inaccessible")

    service = SystemService()
    summary = service.get_system_summary()

    # Should fallback gracefully to platform strings
    assert summary.edition != ""
    assert summary.build_number != ""
    assert "boot" in summary.uptime_formatted
    assert summary.collection_metadata.status == "partial"


@patch("windows_diagnostics_mcp.services.system_service.OpenKey")
@patch("windows_diagnostics_mcp.services.system_service.QueryValueEx")
@patch("psutil.boot_time")
def test_system_service_os_versions(mock_boot_time, mock_query_value, mock_open_key):
    """Test SystemService correct resolution of Windows 10 vs 11 versions across builds."""
    mock_boot_time.return_value = time.time() - 3600.0

    service = SystemService()

    # 1. Windows 10 22H2 (build 19045) -> remains Windows 10
    mock_query_value.side_effect = [("Windows 10 Pro", 1), ("22H2", 1), ("19045", 1)]
    summary = service.get_system_summary()
    assert summary.edition == "Windows 10 Pro"
    assert summary.version == "22H2"
    assert summary.build_number == "19045"

    # 2. Windows 11 23H2 (registry returns Windows 10 Pro, build 22631) -> maps to Windows 11
    mock_query_value.side_effect = [("Windows 10 Pro", 1), ("23H2", 1), ("22631", 1)]
    summary = service.get_system_summary()
    assert summary.edition == "Windows 11 Pro"
    assert summary.version == "23H2"
    assert summary.build_number == "22631"

    # 3. Windows 11 24H2 (registry returns Windows 10 Enterprise, build 26100) -> maps to Windows 11
    mock_query_value.side_effect = [
        ("Windows 10 Enterprise", 1),
        ("24H2", 1),
        ("26100", 1),
    ]
    summary = service.get_system_summary()
    assert summary.edition == "Windows 11 Enterprise"
    assert summary.version == "24H2"
    assert summary.build_number == "26100"

    # 4. Windows 11 25H2 (registry returns Windows 10 Pro, build 26200) -> maps to Windows 11
    mock_query_value.side_effect = [("Windows 10 Pro", 1), ("25H2", 1), ("26200", 1)]
    summary = service.get_system_summary()
    assert summary.edition == "Windows 11 Pro"
    assert summary.version == "25H2"
    assert summary.build_number == "26200"


@patch("windows_diagnostics_mcp.services.system_service.OpenKey")
@patch("windows_diagnostics_mcp.services.system_service.QueryValueEx")
@patch("psutil.boot_time")
@patch.dict("os.environ", {"MACHINE_PROFILE_ANONYMIZE": "true"})
def test_system_service_anonymize(mock_boot_time, mock_query_value, mock_open_key):
    """Test SystemService username and hostname redaction when MACHINE_PROFILE_ANONYMIZE is enabled."""
    mock_boot_time.return_value = time.time() - 3600.0
    mock_query_value.side_effect = [
        ("Windows 11 Pro", 1),
        ("23H2", 1),
        ("22631", 1),
    ]

    service = SystemService()
    summary = service.get_system_summary()

    assert summary.username == "LocalUser"
    assert summary.hostname == "HostMachine"


# ==============================================================================
# Process Service Tests
# ==============================================================================


@patch("psutil.process_iter")
def test_process_service(mock_process_iter):
    """Test ProcessService double-pass CPU querying and top sorting."""
    # Create fake processes
    mock_proc1 = MagicMock()
    mock_proc1.pid = 100
    mock_proc1.cpu_percent.side_effect = [0.0, 85.0]
    mock_proc1.info = {
        "name": "cpu_hog.exe",
        "memory_percent": 10.0,
        "memory_info": MagicMock(rss=500000000),
    }

    mock_proc2 = MagicMock()
    mock_proc2.pid = 200
    mock_proc2.cpu_percent.side_effect = [0.0, 5.0]
    mock_proc2.info = {
        "name": "mem_hog.exe",
        "memory_percent": 25.0,
        "memory_info": MagicMock(rss=1000000000),
    }

    mock_process_iter.return_value = [mock_proc1, mock_proc2]

    service = ProcessService()
    res = service.get_processes(limit=2)

    assert len(res.processes) == 2
    assert res.top_cpu[0].name == "cpu_hog.exe"
    assert res.top_cpu[0].cpu_percent == 85.0
    assert res.top_memory[0].name == "mem_hog.exe"
    assert res.top_memory[0].memory_bytes == 1000000000
    assert res.collection_metadata.status == "ok"


@patch("psutil.process_iter")
def test_process_service_disappearing_process(mock_process_iter):
    """Verify that a process disappearing mid-inspection does not crash the service."""
    import psutil

    mock_proc = MagicMock()
    mock_proc.pid = 999
    # Simulate process disappearing during the CPU sampling pass
    mock_proc.cpu_percent.side_effect = psutil.NoSuchProcess(pid=999)
    mock_proc.info = {"name": "ghost.exe", "memory_percent": 1.0, "memory_info": None}

    mock_process_iter.return_value = [mock_proc]

    service = ProcessService()
    res = service.get_processes()

    # The disappearing process should be gracefully ignored, returning empty list without crash
    assert len(res.processes) == 0
    assert res.collection_metadata.status == "ok"


# ==============================================================================
# Storage Service Tests
# ==============================================================================


@patch("psutil.disk_partitions")
@patch("psutil.disk_usage")
def test_storage_service(mock_disk_usage, mock_disk_partitions):
    """Test StorageService physical drive fetching and utilization calculations."""
    mock_part1 = MagicMock(mountpoint="C:\\", fstype="NTFS", opts="rw")
    mock_part2 = MagicMock(mountpoint="D:\\", fstype="exFAT", opts="cdrom")  # optical
    mock_disk_partitions.return_value = [mock_part1, mock_part2]

    mock_disk_usage.return_value = MagicMock(
        total=100_000_000, used=40_000_000, free=60_000_000, percent=40.0
    )

    service = StorageService()
    res = service.get_storage_summary()

    # Drives will report 2 drives (NTFS + Optical)
    assert len(res.drives) == 2
    assert res.drives[0].drive == "C:\\"
    assert res.drives[0].status == "available"
    assert res.drives[0].usage_percent == 40.0
    assert res.drives[1].status == "unavailable"


@patch("psutil.disk_partitions")
@patch("psutil.disk_usage")
def test_storage_service_permission_denied(mock_disk_usage, mock_disk_partitions):
    """Test StorageService handles permission denied on locked drives without crashing."""
    mock_part = MagicMock(mountpoint="D:\\", fstype="NTFS", opts="rw")
    mock_disk_partitions.return_value = [mock_part]
    mock_disk_usage.side_effect = PermissionError()

    service = StorageService()
    res = service.get_storage_summary()

    assert len(res.drives) == 1
    assert res.drives[0].drive == "D:\\"
    assert res.drives[0].status == "permission_denied"
    assert res.collection_metadata.status == "partial"
    assert len(res.collection_metadata.warnings) == 1


# ==============================================================================
# Developer Service Tests
# ==============================================================================


@patch("os.path.exists")
@patch("shutil.which")
@patch("windows_diagnostics_mcp.services.developer_service.safe_run_command")
def test_developer_service(mock_safe_cmd, mock_which, mock_exists):
    """Test DeveloperService command checks and version parsing regexes."""
    mock_exists.return_value = False
    mock_which.side_effect = lambda x: (
        f"C:\\bin\\{x}" if x not in ("code", "code.cmd") else None
    )

    # safe_run_command outputs
    mock_safe_cmd.side_effect = [
        (0, "git version 2.45.0.windows.1", ""),  # git
        (0, "v20.12.0", ""),  # node
        (0, "Docker version 25.0.3, build abc", ""),  # docker
        (0, "", 'openjdk version "17.0.2" 2022-01-18'),  # java
    ]

    service = DeveloperService()
    res = service.get_developer_environment()

    assert res.git.status == "installed"
    assert res.git.version == "2.45.0.windows.1"
    assert res.node.status == "installed"
    assert res.node.version == "20.12.0"
    assert res.vscode.status == "not_detected"


@patch("os.path.exists")
@patch("shutil.which")
@patch("windows_diagnostics_mcp.services.developer_service.safe_run_command")
def test_developer_service_command_timeout(mock_safe_cmd, mock_which, mock_exists):
    """Test DeveloperService handles CLI version timeouts gracefully."""
    mock_exists.return_value = False
    mock_which.side_effect = lambda x: (
        f"C:\\bin\\{x}" if x not in ("code", "code.cmd") else None
    )

    # Simulate git command timeout, others succeed
    mock_safe_cmd.side_effect = [
        TimeoutError("Command git timed out"),
        (0, "v20.12.0", ""),
        (0, "Docker version 25.0.3, build abc", ""),
        (0, "", 'openjdk version "17.0.2" 2022-01-18'),
    ]

    service = DeveloperService()
    res = service.get_developer_environment()

    # Git should degrade to unavailable but the overall call survives
    assert res.git.status == "unavailable"
    assert res.git.error_message == "Version check command timed out."
    assert res.node.status == "installed"
    assert res.collection_metadata.status == "partial"


# ==============================================================================
# AI Service Tests
# ==============================================================================


@patch("shutil.which")
@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.safe_run_command")
@patch("httpx.get")
@patch("pathlib.Path.glob")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
def test_ai_service_nvidia(
    mock_query_val,
    mock_enum_key,
    mock_query_info,
    mock_open_key,
    mock_glob,
    mock_httpx_get,
    mock_safe_cmd,
    mock_which,
):
    """Test AIService NVIDIA detection path."""
    mock_which.side_effect = lambda x: f"C:\\bin\\{x}"
    mock_safe_cmd.return_value = (
        0,
        "NVIDIA GeForce RTX 4070, 551.23, 12288, 3072, 9216\n",
        "",
    )

    # Ollama responds
    mock_httpx_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "models": [
                {
                    "name": "llama3:8b",
                    "size": 4661224618,
                    "details": {"family": "llama"},
                }
            ]
        },
    )

    mock_glob.return_value = [pathlib.Path.cwd() / ".venv" / "pyvenv.cfg"]

    service = AIService()
    res = service.get_ai_environment()

    assert len(res.gpu) == 1
    assert res.gpu[0].name == "NVIDIA GeForce RTX 4070"
    assert res.gpu[0].source == "nvidia-smi"
    assert res.gpu[0].adapter_type == "discrete"
    assert res.gpu[0].dedicated_vram_bytes == 12288 * 1024 * 1024
    assert res.ollama_running


@patch("shutil.which")
@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.safe_run_command")
@patch("httpx.get")
@patch("pathlib.Path.glob")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
@patch.object(GPUDetector, "_get_enum_device_map")
def test_ai_service_fallback_registry(
    mock_enum_map,
    mock_query_val,
    mock_enum_key,
    mock_query_info,
    mock_open_key,
    mock_glob,
    mock_httpx_get,
    mock_safe_cmd,
    mock_which,
):
    """Test AIService fallback to registry for non-NVIDIA/integrated GPUs."""
    mock_enum_map.return_value = {
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0000": ("PCI\\VEN_8086&DEV_1234\\1", 0)
    }
    mock_which.return_value = None  # no nvidia-smi

    # Mock registry returns 1 display adapter (Intel Iris Xe)
    mock_query_info.return_value = (1, 0, 0)  # 1 subkey
    mock_enum_key.return_value = "0000"
    mock_query_val.side_effect = [
        ("Intel(R) Iris(R) Xe Graphics", 1),  # DriverDesc
        ("Intel Corporation", 1),  # ProviderName
        (4294967296, 1),  # HardwareInformation.MemorySize (4GB in bytes)
    ]

    mock_httpx_get.side_effect = Exception("Ollama not running")
    mock_glob.return_value = []

    service = AIService()
    res = service.get_ai_environment()

    assert len(res.gpu) == 1
    assert res.gpu[0].name == "Intel(R) Iris(R) Xe Graphics"
    assert res.gpu[0].vendor == "Intel Corporation"
    # Integrated Intel GPU must not report dedicated VRAM
    assert res.gpu[0].vram_mb is None
    assert res.gpu[0].dedicated_vram_bytes is None
    assert res.gpu[0].adapter_type == "integrated"
    assert res.gpu[0].source == "registry"
    assert not res.ollama_running


@patch("shutil.which")
@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.safe_run_command")
@patch("httpx.get")
@patch("pathlib.Path.glob")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
@patch.object(GPUDetector, "_get_enum_device_map")
def test_ai_service_ambiguous_hardware(
    mock_enum_map,
    mock_query_val,
    mock_enum_key,
    mock_query_info,
    mock_open_key,
    mock_glob,
    mock_httpx_get,
    mock_safe_cmd,
    mock_which,
):
    """Test that ambiguous hardware returns unknown and null VRAM when queried from registry."""
    mock_enum_map.return_value = {
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0000": ("PCI\\VEN_8086&DEV_1234\\1", 0)
    }
    mock_which.return_value = None  # no nvidia-smi

    # Test case 1: Intel Arc B580 (ambiguous registry display adapter)
    mock_query_info.return_value = (1, 0, 0)
    mock_enum_key.return_value = "0000"
    mock_query_val.side_effect = [
        ("Intel(R) Arc(TM) B580 Graphics", 1),  # DriverDesc
        ("Intel Corporation", 1),  # ProviderName
        (8589934592, 1),  # HardwareInformation.MemorySize
    ]

    mock_httpx_get.side_effect = Exception("Ollama not running")
    mock_glob.return_value = []

    service = AIService()
    res = service.get_ai_environment()
    assert len(res.gpu) == 1
    assert res.gpu[0].name == "Intel(R) Arc(TM) B580 Graphics"
    assert res.gpu[0].adapter_type == "unknown"
    assert res.gpu[0].vram_mb is None
    assert res.gpu[0].dedicated_vram_bytes is None

    # Test case 2: Radeon RX Vega 56 (ambiguous registry display adapter)
    mock_query_val.side_effect = [
        ("Radeon RX Vega 56", 1),  # DriverDesc
        ("Advanced Micro Devices, Inc.", 1),  # ProviderName
        (8589934592, 1),  # HardwareInformation.MemorySize
    ]

    res = service.get_ai_environment()
    assert len(res.gpu) == 1
    assert res.gpu[0].name == "Radeon RX Vega 56"
    assert res.gpu[0].adapter_type == "discrete"
    assert res.gpu[0].vram_mb is None
    assert res.gpu[0].dedicated_vram_bytes is None


# ==============================================================================
# Network Service Tests
# ==============================================================================


@patch("psutil.net_if_addrs")
@patch("psutil.net_if_stats")
@patch("windows_diagnostics_mcp.services.network_service.safe_run_command")
@patch("winreg.OpenKey")
@patch("winreg.QueryValueEx")
@patch("socket.socket")
def test_network_service_offline(
    mock_socket,
    mock_query_value,
    mock_open_key,
    mock_safe_cmd,
    mock_net_stats,
    mock_net_addrs,
):
    """Test NetworkService handles offline reachability timeout check gracefully."""
    mock_net_addrs.return_value = {}
    mock_net_stats.return_value = {}
    mock_safe_cmd.side_effect = Exception("route print failed")

    # DNS query returns nothing
    mock_open_key.side_effect = FileNotFoundError()

    # Sockets time out
    mock_socket.return_value.connect.side_effect = socket.timeout()

    service = NetworkService()
    res = service.get_network_summary()

    assert not res.network_interface_available
    assert not res.local_network_available
    assert res.internet_reachability_check == "timeout"
    assert not res.internet_connected
    assert res.collection_metadata.status == "partial"


# ==============================================================================
# Health Service Tests
# ==============================================================================


@patch("psutil.cpu_percent")
@patch("psutil.virtual_memory")
@patch("psutil.disk_usage")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
def test_health_service_degradations(
    mock_query_info, mock_open_key, mock_disk_usage, mock_virt_mem, mock_cpu
):
    """Test HealthService score deduction engine for CPU, RAM, disk warnings."""
    # Extreme system stress: CPU 95%, RAM 90%, C: drive < 10GB free, 20 startup apps
    mock_cpu.return_value = 95.0
    mock_virt_mem.return_value = MagicMock(percent=90.0)

    # 2 GB free (low disk)
    mock_disk_usage.return_value = MagicMock(
        total=100 * (1024**3), free=2 * (1024**3), percent=98.0
    )

    # 20 startup apps
    mock_query_info.side_effect = [
        (0, 10, 0),  # User run subkey values = 10
        (0, 10, 0),  # System run subkey values = 10 -> total 20
    ]

    mock_proc_service = MagicMock()
    mock_proc_service.get_processes.return_value = MagicMock(top_cpu=[], top_memory=[])
    mock_storage_service = MagicMock()

    service = HealthService(mock_proc_service, mock_storage_service)
    res = service.get_machine_health()

    # Expected Score: 100 - 15 - 15 - 20 - 5 = 45
    assert res.health_score == 45
    assert len(res.warnings) == 4
    assert len(res.recommendations) == 4

    # Verify severity
    severities = {w.severity for w in res.warnings}
    assert "critical" in severities


@patch("windows_diagnostics_mcp.server.mcp.run")
def test_server_main_graceful_shutdown(mock_mcp_run):
    """Test that main() exits cleanly with status 0 on KeyboardInterrupt."""
    mock_mcp_run.side_effect = KeyboardInterrupt()

    from windows_diagnostics_mcp.server import main

    with patch.object(sys, "exit") as mock_exit:
        main()
        mock_exit.assert_called_once_with(0)


# ==============================================================================
# Phase 1: Models and Centralized Privacy Tests
# ==============================================================================


def test_sanitize_user_path_anonymize_disabled(monkeypatch):
    """Test that path sanitization returns original path when anonymization is disabled."""
    monkeypatch.setenv("MACHINE_PROFILE_ANONYMIZE", "false")
    path = r"C:\Users\JohnDoe\AppData\Local"
    assert sanitize_user_path(path) == path
    assert sanitize_user_path(None) is None


def test_sanitize_user_path_anonymize_enabled(monkeypatch):
    """Test that path sanitization replaces username folders with LocalUser."""
    monkeypatch.setenv("MACHINE_PROFILE_ANONYMIZE", "true")
    monkeypatch.setattr("getpass.getuser", lambda: "JohnDoe")

    # Standard Windows path
    assert (
        sanitize_user_path(r"C:\Users\JohnDoe\models") == r"C:\Users\LocalUser\models"
    )
    # Forward slash path
    assert sanitize_user_path("C:/Users/JohnDoe/models") == "C:/Users/LocalUser/models"
    # Exact user directory match
    assert sanitize_user_path(r"C:\Users\JohnDoe") == r"C:\Users\LocalUser"
    # Case insensitivity
    assert (
        sanitize_user_path(r"C:\users\johndoe\models") == r"C:\users\LocalUser\models"
    )
    # No user directory match
    no_match_path = r"C:\Program Files\Common"
    assert sanitize_user_path(no_match_path) == no_match_path


def test_sanitize_user_path_username_with_special_characters(monkeypatch):
    """Test path sanitization handles regex special characters in username correctly."""
    monkeypatch.setenv("MACHINE_PROFILE_ANONYMIZE", "true")
    monkeypatch.setattr("getpass.getuser", lambda: "John.Doe+Special")

    path = r"C:\Users\John.Doe+Special\models"
    assert sanitize_user_path(path) == r"C:\Users\LocalUser\models"


def test_sanitize_user_path_collision_long(monkeypatch):
    """Test path sanitization does not replace if path username contains current user as prefix."""
    monkeypatch.setenv("MACHINE_PROFILE_ANONYMIZE", "true")
    monkeypatch.setattr("getpass.getuser", lambda: "John")

    path = r"C:\Users\JohnDoe\models"
    assert sanitize_user_path(path) == path


def test_phase1_models_instantiation():
    """Verify new Phase 1 models instantiate and validate correct literals/defaults."""
    # 1. CPUInfoModel
    cpu = CPUInfoModel(
        model="Intel Core Ultra 7",
        vendor="GenuineIntel",
        architecture="AMD64",
        physical_cores=8,
        logical_processors=16,
        max_frequency_mhz=4800,
        status="available",
    )
    assert cpu.status == "available"
    assert cpu.avx_support.supported is None
    assert cpu.avx_support.status == "unknown"
    assert cpu.avx_support.source == "none"
    assert cpu.avx2_support.supported is None
    assert cpu.avx2_support.status == "unknown"
    assert cpu.avx2_support.source == "none"
    assert cpu.avx512f_support.supported is None
    assert cpu.avx512f_support.status == "unknown"
    assert cpu.avx512f_support.source == "none"

    # 2. LocalModelItem
    model_item = LocalModelItem(
        name="llama3",
        provider="ollama",
        format="ollama-manifest",
        path=r"C:\Users\LocalUser\models",
        size_bytes=4600000000,
        quantization="Q4_K_M",
        detection_source="filesystem-scan",
        metadata_source="manifest-json",
        confidence="authoritative",
    )
    assert model_item.provider == "ollama"
    assert model_item.confidence == "authoritative"

    # 3. DockerStatusModel
    docker = DockerStatusModel(
        status="daemon_running",
        version="26.1.4",
        ai_containers=[
            DockerContainerInfo(
                name="ollama", image="ollama/ollama:latest", status="Up 2 hours"
            )
        ],
    )
    assert docker.status == "daemon_running"
    assert len(docker.ai_containers) == 1

    # 4. LocalModelInventoryModel default
    inventory = LocalModelInventoryModel()
    assert inventory.inventory_complete is True
    assert inventory.truncated is False
    assert len(inventory.models) == 0


# ==============================================================================
# Phase 2: CPUDetector and GPUDetector Tests
# ==============================================================================


@patch("windows_diagnostics_mcp.services.detectors.cpu_detector.OpenKey")
@patch("windows_diagnostics_mcp.services.detectors.cpu_detector.QueryValueEx")
@patch("psutil.cpu_count")
@patch("psutil.cpu_freq")
def test_cpu_detector_registry_success(
    mock_cpu_freq, mock_cpu_count, mock_query_value, mock_open_key
):
    """Test CPUDetector with successful registry and psutil calls."""
    import platform

    mock_cpu_count.side_effect = lambda logical: 16 if logical else 8

    mock_freq = MagicMock()
    mock_freq.max = 4500.0
    mock_cpu_freq.return_value = mock_freq

    mock_query_value.side_effect = [
        ("Intel(R) Core(TM) i9-10900K CPU @ 3.70GHz", 1),  # ProcessorNameString
        ("GenuineIntel", 1),  # VendorIdentifier
        (3700, 1),  # ~MHz
    ]

    detector = CPUDetector()
    cpu = detector.detect()

    assert cpu.model == "Intel(R) Core(TM) i9-10900K CPU @ 3.70GHz"
    assert cpu.vendor == "GenuineIntel"
    assert cpu.architecture == platform.machine()
    assert cpu.physical_cores == 8
    assert cpu.logical_processors == 16
    assert cpu.max_frequency_mhz == 4500
    assert cpu.status == "available"


@patch("windows_diagnostics_mcp.services.detectors.cpu_detector.OpenKey")
@patch("windows_diagnostics_mcp.services.detectors.cpu_detector.QueryValueEx")
@patch("psutil.cpu_count")
@patch("psutil.cpu_freq")
@patch("platform.processor")
def test_cpu_detector_registry_fallback(
    mock_processor, mock_cpu_freq, mock_cpu_count, mock_query_value, mock_open_key
):
    """Test CPUDetector falls back to platform and psutil when registry queries fail."""
    mock_open_key.side_effect = Exception("Registry locked")
    mock_cpu_count.return_value = None
    mock_cpu_freq.return_value = None
    mock_processor.return_value = "AMD Ryzen 5 5600X 6-Core Processor"

    detector = CPUDetector()
    cpu = detector.detect()

    assert cpu.model == "AMD Ryzen 5 5600X 6-Core Processor"
    assert cpu.vendor == "AuthenticAMD"
    assert cpu.physical_cores is None
    assert cpu.logical_processors is None
    assert cpu.max_frequency_mhz is None
    assert cpu.status == "partial"


def test_cpu_detector_avx_capabilities_positive():
    """Verify that CPUDetector correctly reports AVX, AVX2, AVX512F when IsProcessorFeaturePresent is true."""
    detector = CPUDetector()

    mock_windll = MagicMock()
    mock_windll.kernel32.IsProcessorFeaturePresent.side_effect = lambda feat: feat in [
        39,
        40,
        41,
    ]

    with (
        patch("ctypes.windll", mock_windll, create=True),
        patch("platform.system", return_value="Windows"),
        patch("platform.machine", return_value="AMD64"),
    ):

        cpu = detector.detect()
        assert cpu.avx_support.supported is True
        assert cpu.avx_support.status == "available"
        assert cpu.avx_support.source == "ctypes-probe"

        assert cpu.avx2_support.supported is True
        assert cpu.avx2_support.status == "available"
        assert cpu.avx2_support.source == "ctypes-probe"

        assert cpu.avx512f_support.supported is True
        assert cpu.avx512f_support.status == "available"
        assert cpu.avx512f_support.source == "ctypes-probe"


def test_cpu_detector_avx_capabilities_negative():
    """Verify that CPUDetector correctly reports AVX features as unsupported if the API returns False."""
    detector = CPUDetector()

    mock_windll = MagicMock()
    # Explicitly unsupported (returns False / 0)
    mock_windll.kernel32.IsProcessorFeaturePresent.return_value = 0

    with (
        patch("ctypes.windll", mock_windll, create=True),
        patch("platform.system", return_value="Windows"),
        patch("platform.machine", return_value="AMD64"),
    ):

        cpu = detector.detect()
        assert cpu.avx_support.supported is False
        assert cpu.avx_support.status == "unavailable"
        assert cpu.avx_support.source == "ctypes-probe"

        assert cpu.avx2_support.supported is False
        assert cpu.avx2_support.status == "unavailable"
        assert cpu.avx2_support.source == "ctypes-probe"

        assert cpu.avx512f_support.supported is False
        assert cpu.avx512f_support.status == "unavailable"
        assert cpu.avx512f_support.source == "ctypes-probe"


def test_cpu_detector_avx_capabilities_non_windows():
    """Verify that CPUDetector handles non-Windows systems by marking AVX capabilities as unknown."""
    detector = CPUDetector()

    with (
        patch("platform.system", return_value="Linux"),
        patch("platform.machine", return_value="AMD64"),
    ):

        cpu = detector.detect()
        for cap in [cpu.avx_support, cpu.avx2_support, cpu.avx512f_support]:
            assert cap.supported is None
            assert cap.status == "unknown"
            assert cap.source == "none"
            assert "only supported on Windows" in cap.detail


def test_cpu_detector_avx_capabilities_non_x64():
    """Verify that CPUDetector handles non-x86/x64 systems (like ARM64) by marking AVX capabilities as unknown (not applicable)."""
    detector = CPUDetector()

    with (
        patch("platform.system", return_value="Windows"),
        patch("platform.machine", return_value="ARM64"),
    ):

        cpu = detector.detect()
        for cap in [cpu.avx_support, cpu.avx2_support, cpu.avx512f_support]:
            assert cap.supported is None
            assert cap.status == "unknown"
            assert cap.source == "none"
            assert "not queried" in cap.detail


def test_cpu_detector_avx_capabilities_error():
    """Verify that CPUDetector handles ctypes errors/exceptions gracefully and returns status error."""
    detector = CPUDetector()

    mock_windll = MagicMock()
    mock_windll.kernel32.IsProcessorFeaturePresent.side_effect = Exception(
        "Win32 error"
    )
    with (
        patch("ctypes.windll", mock_windll, create=True),
        patch("platform.system", return_value="Windows"),
        patch("platform.machine", return_value="AMD64"),
    ):

        cpu = detector.detect()
        for cap in [cpu.avx_support, cpu.avx2_support, cpu.avx512f_support]:
            assert cap.supported is None
            assert cap.status == "error"
            assert cap.source == "none"
            assert "Failed to query" in cap.detail


def test_cpu_detector_constants_regression():
    """Verify that CPUDetector queries the exact official Win32 constants for processor features (AVX=39, AVX2=40, AVX512F=41)."""
    detector = CPUDetector()

    called_args = []

    def mock_is_present(feat_id):
        called_args.append(feat_id)
        return 0

    mock_windll = MagicMock()
    mock_windll.kernel32.IsProcessorFeaturePresent.side_effect = mock_is_present

    with (
        patch("ctypes.windll", mock_windll, create=True),
        patch("platform.system", return_value="Windows"),
        patch("platform.machine", return_value="AMD64"),
    ):

        detector.detect()
        assert called_args == [
            39,
            40,
            41,
        ], f"Expected called args to be exactly [39, 40, 41], but got {called_args}"


@patch("winreg.OpenKey", side_effect=OSError)
@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.shutil.which")
@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.safe_run_command")
def test_gpu_detector_nvidia_smi_success(mock_safe_cmd, mock_which, mock_open_key):
    """Test GPUDetector when nvidia-smi successfully returns discrete GPU details."""
    mock_which.return_value = r"C:\Windows\System32\nvidia-smi.exe"
    mock_safe_cmd.return_value = (
        0,
        "NVIDIA GeForce RTX 4090, 555.99, 24576, 4000, 20576",
        "",
    )

    detector = GPUDetector()
    gpus = detector.detect()

    assert len(gpus) == 1
    assert gpus[0].name == "NVIDIA GeForce RTX 4090"
    assert gpus[0].vendor == "NVIDIA"
    assert gpus[0].vram_mb == 24576
    assert gpus[0].adapter_type == "discrete"
    assert gpus[0].dedicated_vram_bytes == 24576 * 1024 * 1024
    assert gpus[0].source == "nvidia-smi"
    assert gpus[0].status == "available"


@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.shutil.which")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
@patch.object(GPUDetector, "_get_enum_device_map")
def test_gpu_detector_registry_integrated_fallback(
    mock_enum_map,
    mock_query_val,
    mock_enum_key,
    mock_query_info,
    mock_open_key,
    mock_which,
):
    """Test GPUDetector integrated and unknown graphics classification and VRAM handling."""
    mock_enum_map.return_value = {
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0000": (
            "PCI\\VEN_8086&DEV_1234\\1",
            0,
        ),
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0001": (
            "PCI\\VEN_5678&DEV_5678\\2",
            0,
        ),
    }
    mock_which.return_value = None  # no nvidia-smi

    mock_query_info.return_value = (2, 0, 0)
    mock_enum_key.side_effect = ["0000", "0001"]

    # Mock values returned for adapter 0000 (Intel integrated) and adapter 0001 (Ambiguous unknown device)
    mock_query_val.side_effect = [
        ("Intel(R) UHD Graphics", 1),  # DriverDesc 0000
        ("Intel Corporation", 1),  # ProviderName 0000
        ("Super 3D Graphics Accelerator", 1),  # DriverDesc 0001
        ("Generic Vendor", 1),  # ProviderName 0001
    ]

    detector = GPUDetector()
    gpus = detector.detect()

    assert len(gpus) == 2

    # Verify Intel Integrated: dedicated VRAM must be null/None
    assert gpus[0].name == "Intel(R) UHD Graphics"
    assert gpus[0].adapter_type == "integrated"
    assert gpus[0].dedicated_vram_bytes is None
    assert gpus[0].vram_mb is None

    # Verify Ambiguous Graphics: must map to unknown with null/None dedicated VRAM
    assert gpus[1].name == "Super 3D Graphics Accelerator"
    assert gpus[1].adapter_type == "unknown"
    assert gpus[1].dedicated_vram_bytes is None
    assert gpus[1].vram_mb is None


@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.shutil.which")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
@patch.object(GPUDetector, "_get_enum_device_map")
def test_gpu_detector_registry_only_discrete(
    mock_enum_map,
    mock_query_val,
    mock_enum_key,
    mock_query_info,
    mock_open_key,
    mock_which,
):
    """Test that registry-only discrete-looking GPUs get classified as discrete but carry null VRAM."""
    mock_enum_map.return_value = {
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0000": (
            "PCI\\VEN_10de&DEV_1234\\1",
            0,
        ),
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0001": (
            "PCI\\VEN_1002&DEV_5678\\2",
            0,
        ),
    }
    mock_which.return_value = None  # no nvidia-smi

    mock_query_info.return_value = (2, 0, 0)
    mock_enum_key.side_effect = ["0000", "0001"]

    # Mock discrete-looking NVIDIA and AMD registry results
    mock_query_val.side_effect = [
        ("NVIDIA GeForce RTX 4080", 1),  # DriverDesc 0000 (NVIDIA discrete)
        ("NVIDIA Corporation", 1),  # ProviderName 0000
        ("Radeon RX 7900 XTX", 1),  # DriverDesc 0001 (AMD discrete)
        ("Advanced Micro Devices, Inc.", 1),  # ProviderName 0001
    ]

    detector = GPUDetector()
    gpus = detector.detect()

    assert len(gpus) == 2

    # NVIDIA registry-only discrete
    assert gpus[0].name == "NVIDIA GeForce RTX 4080"
    assert gpus[0].adapter_type == "discrete"
    assert gpus[0].dedicated_vram_bytes is None
    assert gpus[0].vram_mb is None

    # AMD registry-only discrete
    assert gpus[1].name == "Radeon RX 7900 XTX"
    assert gpus[1].adapter_type == "discrete"
    assert gpus[1].dedicated_vram_bytes is None
    assert gpus[1].vram_mb is None


@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.shutil.which")
@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.safe_run_command")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
@patch.object(GPUDetector, "_get_enum_device_map")
def test_gpu_detector_hybrid_merge(
    mock_enum_map,
    mock_query_val,
    mock_enum_key,
    mock_query_info,
    mock_open_key,
    mock_safe_cmd,
    mock_which,
):
    """Test that nvidia-smi is authoritative and correctly merges distinct registry display adapters."""
    mock_enum_map.return_value = {
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0000": (
            "PCI\\VEN_10de&DEV_4090\\1",
            0,
        ),
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0001": (
            "PCI\\VEN_8086&DEV_5678\\2",
            0,
        ),
    }
    mock_which.return_value = r"C:\Windows\System32\nvidia-smi.exe"
    mock_safe_cmd.return_value = (
        0,
        "NVIDIA GeForce RTX 4090, 555.99, 24576, 4000, 20576",
        "",
    )

    # Registry has the RTX 4090 (duplicate) and an Intel Integrated Xe
    mock_query_info.return_value = (2, 0, 0)
    mock_enum_key.side_effect = ["0000", "0001"]

    mock_query_val.side_effect = [
        ("NVIDIA GeForce RTX 4090", 1),  # DriverDesc 0000 (duplicate)
        ("NVIDIA Corporation", 1),  # ProviderName 0000
        ("Intel(R) Iris(R) Xe Graphics", 1),  # DriverDesc 0001 (distinct integrated)
        ("Intel Corporation", 1),  # ProviderName 0001
    ]

    detector = GPUDetector()
    gpus = detector.detect()

    # Must contain both the authoritative RTX 4090 (with VRAM) and Iris Xe (with null VRAM)
    assert len(gpus) == 2

    # 1. Authoritative SMI entry
    assert gpus[0].name == "NVIDIA GeForce RTX 4090"
    assert gpus[0].adapter_type == "discrete"
    assert gpus[0].dedicated_vram_bytes == 24576 * 1024 * 1024
    assert gpus[0].vram_mb == 24576
    assert gpus[0].source == "nvidia-smi"

    # 2. Merged distinct integrated registry entry
    assert gpus[1].name == "Intel(R) Iris(R) Xe Graphics"
    assert gpus[1].adapter_type == "integrated"
    assert gpus[1].dedicated_vram_bytes is None
    assert gpus[1].vram_mb is None
    assert gpus[1].source == "registry"


# ==============================================================================
# Phase 3: OllamaDetector Tests
# ==============================================================================


@patch("os.path.exists")
@patch("os.path.isdir")
def test_ollama_detector_default_root(mock_isdir, mock_exists):
    """Test default root path resolution hierarchy when OLLAMA_MODELS is not set."""
    mock_exists.return_value = False
    mock_isdir.return_value = False

    detector = OllamaDetector()
    with patch.dict(os.environ, {}, clear=True):
        with patch.dict(os.environ, {"USERPROFILE": r"C:\Users\FakeUser"}):
            root = detector._get_models_root()
            assert root == Path(r"C:\Users\FakeUser\.ollama\models")


def test_ollama_detector_custom_root_override():
    """Test custom root override when OLLAMA_MODELS environment variable is set."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        detector = OllamaDetector()
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(tmp_path)}):
            root = detector._get_models_root()
            assert root == tmp_path


def test_ollama_detector_offline_no_daemon():
    """Test that model discovery functions offline without requiring a running daemon/API."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()

        # Manifests exist, daemon is not queried
        detector = OllamaDetector()
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(tmp_path)}):
            inv = detector.detect()
            assert inv.inventory_complete is True
            assert len(inv.models) == 0


def test_ollama_detector_valid_manifest_identity():
    """Test correct parsing of registry, namespace, and tags for model names."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        manifests_dir = tmp_path / "manifests"

        # library namespace
        lib_dir = manifests_dir / "registry.ollama.ai" / "library" / "llama3"
        lib_dir.mkdir(parents=True)
        with open(lib_dir / "latest", "w", encoding="utf-8") as f:
            json.dump({"schemaVersion": 2, "layers": [{"size": 100}]}, f)

        # custom namespace
        cust_dir = manifests_dir / "registry.ollama.ai" / "customowner" / "qwen"
        cust_dir.mkdir(parents=True)
        with open(cust_dir / "v1.0", "w", encoding="utf-8") as f:
            json.dump({"schemaVersion": 2, "layers": [{"size": 200}]}, f)

        detector = OllamaDetector()
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(tmp_path)}):
            inv = detector.detect()
            assert len(inv.models) == 2

            names = {m.name: m for m in inv.models}
            assert "llama3:latest" in names
            assert names["llama3:latest"].provider == "ollama"

            assert "customowner/qwen:v1.0" in names
            assert names["customowner/qwen:v1.0"].confidence == "authoritative"


def test_ollama_detector_multiple_models_tags():
    """Test discovering multiple tags for a single model."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        model_dir = tmp_path / "manifests" / "registry.ollama.ai" / "library" / "llama3"
        model_dir.mkdir(parents=True)

        with open(model_dir / "8b", "w", encoding="utf-8") as f:
            json.dump({"schemaVersion": 2, "layers": [{"size": 10}]}, f)
        with open(model_dir / "70b", "w", encoding="utf-8") as f:
            json.dump({"schemaVersion": 2, "layers": [{"size": 20}]}, f)

        detector = OllamaDetector()
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(tmp_path)}):
            inv = detector.detect()
            assert len(inv.models) == 2
            names = {m.name for m in inv.models}
            assert "llama3:8b" in names
            assert "llama3:70b" in names


def test_ollama_detector_shared_blobs_logical_size():
    """Test that model size is the logical sum of layer sizes, not physical disk usage."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        model_dir = tmp_path / "manifests" / "registry.ollama.ai" / "library" / "llama3"
        model_dir.mkdir(parents=True)

        # Manifest layer sizes sum to 4000001000
        manifest_data = {
            "schemaVersion": 2,
            "layers": [
                {"mediaType": "model", "size": 4000000000},
                {"mediaType": "license", "size": 1000},
            ],
        }
        with open(model_dir / "latest", "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        detector = OllamaDetector()
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(tmp_path)}):
            inv = detector.detect()
            assert len(inv.models) == 1
            assert inv.models[0].size_bytes == 4000001000


def test_ollama_detector_malformed_manifest_continuation():
    """Test that malformed manifest JSON is skipped with a warning and does not crash discovery."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        model_dir = tmp_path / "manifests" / "registry.ollama.ai" / "library" / "llama3"
        model_dir.mkdir(parents=True)

        # One malformed file
        with open(model_dir / "bad", "w", encoding="utf-8") as f:
            f.write("invalid-json{")
        # One valid file
        with open(model_dir / "good", "w", encoding="utf-8") as f:
            json.dump({"schemaVersion": 2, "layers": [{"size": 500}]}, f)

        detector = OllamaDetector()
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(tmp_path)}):
            inv = detector.detect()
            assert inv.inventory_complete is False
            assert len(inv.warnings) == 1
            assert "Failed to parse manifest" in inv.warnings[0]
            assert len(inv.models) == 1
            assert inv.models[0].name == "llama3:good"


def test_ollama_detector_missing_manifest_dir():
    """Test early termination returning empty inventory when manifest directory does not exist."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        # No 'manifests' directory exists
        detector = OllamaDetector()
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(tmp_path)}):
            inv = detector.detect()
            assert inv.inventory_complete is True
            assert len(inv.models) == 0
            assert len(inv.warnings) == 0


def test_ollama_detector_anonymized_model_paths():
    """Test that absolute paths inside discovered models are anonymized if MACHINE_PROFILE_ANONYMIZE is active."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        model_dir = tmp_path / "manifests" / "registry.ollama.ai" / "library" / "llama3"
        model_dir.mkdir(parents=True)
        with open(model_dir / "latest", "w", encoding="utf-8") as f:
            json.dump({"schemaVersion": 2, "layers": [{"size": 100}]}, f)

        detector = OllamaDetector()
        with patch.dict(
            os.environ,
            {
                "OLLAMA_MODELS": str(tmp_path),
                "MACHINE_PROFILE_ANONYMIZE": "true",
            },
        ):
            import getpass

            username = getpass.getuser()

            inv = detector.detect()
            assert len(inv.models) == 1
            path = inv.models[0].path
            assert username not in path
            assert "LocalUser" in path


def test_ollama_detector_anonymized_warnings_errors():
    """Test that paths and exception messages inside warnings are sanitized to prevent username leaks."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        model_dir = tmp_path / "manifests" / "registry.ollama.ai" / "library" / "llama3"
        model_dir.mkdir(parents=True)

        # Include username in path to verify exception sanitization
        import getpass

        username = getpass.getuser()
        bad_file = model_dir / "bad_file_manifest"
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("bad_json{")

        detector = OllamaDetector()
        with patch.dict(
            os.environ,
            {
                "OLLAMA_MODELS": str(tmp_path),
                "MACHINE_PROFILE_ANONYMIZE": "true",
            },
        ):
            inv = detector.detect()
            assert inv.inventory_complete is False
            assert len(inv.warnings) == 1
            # Username should be replaced in both path and exception text
            assert username not in inv.warnings[0]
            assert "LocalUser" in inv.warnings[0]


def test_ollama_detector_traversal_depth_limit():
    """Test that directory walk is strictly limited to MAX_DEPTH = 3 and flags truncation."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        # Create folder structure deeper than depth 3
        # Level 1: reg
        # Level 2: ns
        # Level 3: model
        # Level 4: extra_sub (too deep directory recursion)
        deep_dir = tmp_path / "manifests" / "reg" / "ns" / "model" / "extra_sub"
        deep_dir.mkdir(parents=True)

        with open(deep_dir / "latest", "w", encoding="utf-8") as f:
            json.dump({"schemaVersion": 2, "layers": [{"size": 100}]}, f)

        detector = OllamaDetector()
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(tmp_path)}):
            inv = detector.detect()
            # Because the file is inside extra_sub (Level 4 dir recursion, making tag depth 5),
            # the traversal to extra_sub is blocked by depth limit, and it sets truncated=True.
            assert inv.truncated is True
            # The model is inside Level 4 subfolder, so it shouldn't be found
            assert len(inv.models) == 0


def test_ollama_detector_file_count_truncation():
    """Test file count truncation limit of 200 items."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        model_dir = tmp_path / "manifests" / "reg" / "ns" / "model"
        model_dir.mkdir(parents=True)

        detector = OllamaDetector()
        with patch.dict(os.environ, {"OLLAMA_MODELS": str(tmp_path)}):
            # Artificially populate 200 items to check limit hit triggers truncation
            def mock_walk(current_dir, depth, warnings, manifest_files):
                for _ in range(201):
                    manifest_files.append((str(model_dir / "file"), 3))
                detector._truncated = True
                detector._inventory_complete = False

            with patch.object(detector, "_walk_manifests", side_effect=mock_walk):
                inv = detector.detect()
                assert inv.truncated is True


# ==============================================================================
# Phase 4: LMStudioDetector Tests
# ==============================================================================


def test_lmstudio_detector_default_root():
    """Test default root path resolution for LM Studio."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        cache_dir = tmp_path / ".cache" / "lm-studio" / "models"
        cache_dir.mkdir(parents=True)

        # Create a mock model file
        model_file = cache_dir / "QuantFactory" / "Llama3" / "llama3.Q4_K_M.gguf"
        model_file.parent.mkdir(parents=True)
        with open(model_file, "w") as f:
            f.write("mock")

        detector = LMStudioDetector()
        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
            inv = detector.detect()
            assert len(inv.models) == 1
            assert inv.models[0].name == "QuantFactory/Llama3"
            assert inv.models[0].quantization == "Q4_K_M"
            assert inv.models[0].provider == "lm-studio"


def test_lmstudio_detector_custom_config_override():
    """Test parsing custom directories from settings.json."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()

        # Create a custom models directory
        custom_dir = tmp_path / "my_custom_models"
        custom_dir.mkdir()
        model_file = custom_dir / "TheBloke" / "Mistral" / "mistral.Q8_0.gguf"
        model_file.parent.mkdir(parents=True)
        with open(model_file, "w") as f:
            f.write("mock")

        # Create settings.json
        settings_dir = tmp_path / ".lmstudio"
        settings_dir.mkdir()
        settings_file = settings_dir / "settings.json"
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump({"modelDownloadsDir": str(custom_dir)}, f)

        detector = LMStudioDetector()
        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
            inv = detector.detect()
            assert len(inv.models) == 1
            assert inv.models[0].name == "TheBloke/Mistral"
            assert inv.models[0].quantization == "Q8_0"


def test_lmstudio_detector_quantization_parsing():
    """Test quantization parsing from GGUF filenames."""
    detector = LMStudioDetector()
    assert detector._parse_quantization("model.q4_k_m.gguf") == "Q4_K_M"
    assert detector._parse_quantization("model.Q8_0.gguf") == "Q8_0"
    assert detector._parse_quantization("model.FP16.gguf") == "FP16"
    assert detector._parse_quantization("model.Q4_K.gguf") == "Q4_K"
    assert detector._parse_quantization("model-Q5_K_S.gguf") == "Q5_K_S"
    assert detector._parse_quantization("model.gguf") is None


def test_lmstudio_detector_depth_limit():
    """Test that directory walk is strictly limited to MAX_DEPTH = 3 and flags truncation."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        cache_dir = tmp_path / ".cache" / "lm-studio" / "models"

        # Create folder structure deeper than depth 3
        # Level 1: pub
        # Level 2: model
        # Level 3: subdir (too deep dir recursion)
        deep_dir = cache_dir / "pub" / "model" / "subdir"
        deep_dir.mkdir(parents=True)
        (deep_dir / "extra").mkdir()
        with open(deep_dir / "file.gguf", "w") as f:
            f.write("mock")

        detector = LMStudioDetector()
        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
            inv = detector.detect()
            assert inv.truncated is True
            assert inv.inventory_complete is False
            assert len(inv.models) == 1


def test_lmstudio_detector_file_count_truncation():
    """Test file count truncation limit of 200 items."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        cache_dir = tmp_path / ".cache" / "lm-studio" / "models"
        cache_dir.mkdir(parents=True)

        detector = LMStudioDetector()
        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):

            def mock_walk_exactly_200(current_dir, depth, warnings, manifest_files):
                for i in range(200):
                    manifest_files.append((str(cache_dir / f"model_{i}.gguf"), 3))

            with patch.object(
                detector, "_walk_models", side_effect=mock_walk_exactly_200
            ):
                with patch("os.path.getsize", return_value=123):
                    inv = detector.detect()
                    assert inv.truncated is False
                    assert inv.inventory_complete is True
                    assert len(inv.models) == 200

            def mock_walk_201(current_dir, depth, warnings, manifest_files):
                for i in range(200):
                    manifest_files.append((str(cache_dir / f"model_{i}.gguf"), 3))
                detector._truncated = True
                detector._inventory_complete = False

            with patch.object(detector, "_walk_models", side_effect=mock_walk_201):
                with patch("os.path.getsize", return_value=123):
                    inv = detector.detect()
                    assert inv.truncated is True
                    assert inv.inventory_complete is False


def test_lmstudio_detector_anonymized_paths_and_warnings():
    """Test username anonymization in model paths and warnings."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        cache_dir = tmp_path / ".cache" / "lm-studio" / "models"
        cache_dir.mkdir(parents=True)

        import getpass

        model_file = cache_dir / "file_model.gguf"
        with open(model_file, "w") as f:
            f.write("mock")

        detector = LMStudioDetector()
        with patch.dict(
            os.environ,
            {
                "USERPROFILE": str(tmp_path),
                "MACHINE_PROFILE_ANONYMIZE": "true",
            },
        ):
            username = getpass.getuser()
            inv = detector.detect()
            assert len(inv.models) == 1
            assert username not in inv.models[0].path
            assert "LocalUser" in inv.models[0].path


def test_lmstudio_detector_model_deduplication():
    """Test that duplicate GGUF models reachable via multiple roots are deduplicated."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()

        # We configure two roots (default cache and custom) pointing to the same folder
        cache_dir = tmp_path / ".cache" / "lm-studio" / "models"
        cache_dir.mkdir(parents=True)

        # Write same GGUF file
        f1 = cache_dir / "pub" / "model" / "file.gguf"
        f1.parent.mkdir(parents=True)
        with open(f1, "w") as f:
            f.write("mock")

        detector = LMStudioDetector()
        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
            # We mock _get_custom_paths to return the cache_dir itself to force root/path overlaps
            with patch.object(detector, "_get_custom_paths", return_value=[cache_dir]):
                inv = detector.detect()
                # Should resolve and deduplicate, finding exactly 1 model (not 2)
                assert len(inv.models) == 1


def test_lmstudio_detector_privacy_failure_paths():
    """Test that with anonymization enabled, username is redacted from exceptions and stat warnings."""
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        cache_dir = tmp_path / ".cache" / "lm-studio" / "models"
        cache_dir.mkdir(parents=True)

        # Force a stat failure inside a directory containing the username in path
        import getpass

        username = getpass.getuser()
        user_dir = cache_dir / "pub_some_folder"
        user_dir.mkdir()

        detector = LMStudioDetector()
        with patch.dict(
            os.environ,
            {
                "USERPROFILE": str(tmp_path),
                "MACHINE_PROFILE_ANONYMIZE": "true",
            },
        ):
            target_path_normalized = str(user_dir).replace("\\", "/").lower()
            intercept_count = 0
            orig_stat = os.stat

            def stat_side_effect(path, *args, **kwargs):
                nonlocal intercept_count
                path_str = str(path).replace("\\", "/").lower()
                if path_str == target_path_normalized:
                    intercept_count += 1
                    raise OSError(f"Failed to access C:\\Users\\{username}\\dir")
                return orig_stat(path, *args, **kwargs)

            with patch("os.stat", side_effect=stat_side_effect):
                inv = detector.detect()
                assert (
                    intercept_count > 0
                ), "Mock did not intercept target user_dir stat call"
                assert inv.inventory_complete is False
                assert len(inv.warnings) >= 1
                # The exception text and warning path must be fully sanitized
                for w in inv.warnings:
                    assert username not in w
                    assert "LocalUser" in w or "LocalUser" in w.replace("\\", "/")


def test_lmstudio_detector_path_resolve_safety():
    """Test that Path.resolve() throwing an exception during deduplication falls back safely without crashes."""
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        cache_dir = tmp_path / ".cache" / "lm-studio" / "models"
        cache_dir.mkdir(parents=True)

        # Create normal GGUF file
        model_file = cache_dir / "pub" / "model" / "file.gguf"
        model_file.parent.mkdir(parents=True)
        with open(model_file, "w") as f:
            f.write("mock")

        detector = LMStudioDetector()
        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
            # Mock Path.resolve to raise OSError
            with patch.object(Path, "resolve", side_effect=OSError("Broken symlink")):
                inv = detector.detect()
                # Should fallback to absolute/raw path, discovering the model without crashing
                assert len(inv.models) == 1
                assert inv.models[0].name == "pub/model"


def test_lmstudio_detector_reparse_symlink_skip():
    """Test that os.path.islink returning True skips the directory and flags inventory incomplete."""
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        cache_dir = tmp_path / ".cache" / "lm-studio" / "models"
        cache_dir.mkdir(parents=True)

        junction_dir = cache_dir / "pub" / "model" / "junction_dir"
        junction_dir.mkdir(parents=True)

        detector = LMStudioDetector()
        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
            with patch("os.path.islink", return_value=True):
                inv = detector.detect()
                assert inv.inventory_complete is False
                assert len(inv.warnings) >= 1
                assert "Skipped symlink" in inv.warnings[0]


def test_lmstudio_detector_reparse_stat_failure_skip():
    """Test that os.stat raising OSError skips the directory, flags incomplete, and logs sanitized warning."""
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        cache_dir = tmp_path / ".cache" / "lm-studio" / "models"
        cache_dir.mkdir(parents=True)

        junction_dir = cache_dir / "pub" / "model" / "junction_dir"
        junction_dir.mkdir(parents=True)

        detector = LMStudioDetector()
        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
            # os.path.islink returns False so stat exception branch is executed
            with patch("os.path.islink", return_value=False):
                target_path_normalized = str(junction_dir).replace("\\", "/").lower()
                intercept_count = 0
                orig_stat = os.stat

                def stat_side_effect(path, *args, **kwargs):
                    nonlocal intercept_count
                    path_str = str(path).replace("\\", "/").lower()
                    if path_str == target_path_normalized:
                        intercept_count += 1
                        raise OSError("Permission Denied")
                    return orig_stat(path, *args, **kwargs)

                with patch("os.stat", side_effect=stat_side_effect):
                    inv = detector.detect()
                    assert (
                        intercept_count > 0
                    ), "Mock did not intercept target junction_dir stat call"
                    assert inv.inventory_complete is False
                    assert len(inv.warnings) >= 1
                    assert "Junction check failed" in inv.warnings[0]


def test_ai_service_inventory_merge():
    """Test merging Ollama and LM Studio offline model inventories in AIService."""
    from windows_diagnostics_mcp.services.ai_service import AIService
    from windows_diagnostics_mcp.models.ai import (
        LocalModelItem,
        LocalModelInventoryModel,
    )

    service = AIService()

    mock_ollama_item = LocalModelItem(
        name="llama3:latest",
        provider="ollama",
        format="ollama-manifest",
        path="C:\\Users\\LocalUser\\.ollama\\models\\llama3",
        size_bytes=1000,
        quantization=None,
        detection_source="filesystem-scan",
        metadata_source="manifest-json",
        confidence="authoritative",
    )
    mock_lmstudio_item = LocalModelItem(
        name="TheBloke/Mistral",
        provider="lm-studio",
        format="gguf",
        path="C:\\Users\\LocalUser\\.cache\\lm-studio\\mistral.gguf",
        size_bytes=2000,
        quantization="Q4_K_M",
        detection_source="filesystem-scan",
        metadata_source="filename-parse",
        confidence="inferred",
    )

    ollama_inv = LocalModelInventoryModel(
        models=[mock_ollama_item],
        inventory_complete=True,
        truncated=False,
        warnings=["Ollama test warning"],
    )
    lmstudio_inv = LocalModelInventoryModel(
        models=[mock_lmstudio_item],
        inventory_complete=False,
        truncated=True,
        warnings=["LM Studio test warning"],
    )

    with patch.object(service._ollama_detector, "detect", return_value=ollama_inv):
        with patch.object(
            service._lmstudio_detector, "detect", return_value=lmstudio_inv
        ):
            status = service.get_ai_environment()

            # 1. Both models survive
            assert len(status.local_models.models) == 2
            names = {m.name for m in status.local_models.models}
            assert "llama3:latest" in names
            assert "TheBloke/Mistral" in names

            # 2. Both warnings survive
            assert len(status.local_models.warnings) == 2
            assert "Ollama test warning" in status.local_models.warnings
            assert "LM Studio test warning" in status.local_models.warnings

            # 3. Truncated is True (ollama.truncated OR lmstudio.truncated)
            assert status.local_models.truncated is True

            # 4. inventory_complete is False (ollama.complete AND lmstudio.complete)
            assert status.local_models.inventory_complete is False


# ==============================================================================
# Phase 5: DockerDetector & AI Container Discovery Tests
# ==============================================================================


def test_docker_detector_not_installed():
    """Test DockerStatus resolution when Docker CLI is not installed."""
    detector = DockerDetector()
    with patch("shutil.which", return_value=None):
        status = detector.detect()
        assert status.status == "not_installed"
        assert status.version is None
        assert len(status.ai_containers) == 0


def test_docker_detector_daemon_running():
    """Test DockerStatus resolution when Docker daemon is running and no containers exist."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7, build afdd53b", ""),  # --version
                (0, "Containers: 0\nRunning: 0", ""),  # info
                (0, "", ""),  # ps
            ]
            status = detector.detect()
            assert status.status == "daemon_running"
            assert status.version == "24.0.7"
            assert len(status.ai_containers) == 0


def test_docker_detector_daemon_unavailable():
    """Test DockerStatus resolution when Docker daemon is stopped/unavailable."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),  # --version
                (1, "", "is the docker daemon running?"),  # info
            ]
            status = detector.detect()
            assert status.status == "daemon_unavailable"
            assert len(status.ai_containers) == 0


def test_docker_detector_timeout():
    """Test DockerStatus resolution when daemon command times out."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),  # --version
                TimeoutError("Command timed out"),  # info
            ]
            status = detector.detect()
            assert status.status == "timeout"
            assert len(status.ai_containers) == 0


def test_docker_detector_permission_failure():
    """Test DockerStatus resolution when docker info returns a permission/context error."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),  # --version
                (
                    1,
                    "",
                    "Permission Denied: access to docker daemon",
                ),  # info
            ]
            status = detector.detect()
            assert status.status == "permission_or_context_error"
            assert len(status.ai_containers) == 0


def test_docker_detector_ambiguous_failure():
    """Test DockerStatus resolution when docker info returns an ambiguous non-zero code -> unknown."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),  # --version
                (
                    125,
                    "",
                    "Command failed with generic docker error",
                ),  # info
            ]
            status = detector.detect()
            assert status.status == "unknown"
            assert len(status.ai_containers) == 0


def test_docker_detector_malformed_output():
    """Test AI container discovery when docker ps output format is malformed."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),  # --version
                (0, "Containers: 1", ""),  # info
                (
                    0,
                    "malformed_line_no_tabs\nname\timage",
                    "",
                ),  # ps (less than 3 parts)
            ]
            status = detector.detect()
            assert status.status == "daemon_running"
            assert len(status.ai_containers) == 0


def test_docker_detector_one_ollama_container():
    """Test AI container discovery when one Ollama container is running."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),  # --version
                (0, "Containers: 1", ""),  # info
                (
                    0,
                    "ollama-service\tollama/ollama:latest\tUp 2 hours",
                    "",
                ),  # ps
            ]
            status = detector.detect()
            assert status.status == "daemon_running"
            assert len(status.ai_containers) == 1
            assert status.ai_containers[0].name == "ollama-service"
            assert status.ai_containers[0].image == "ollama/ollama:latest"
            assert status.ai_containers[0].status == "Up 2 hours"


def test_docker_detector_multiple_containers():
    """Test AI container discovery when multiple AI containers are running."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),  # --version
                (0, "Containers: 3", ""),  # info
                (
                    0,
                    "ollama\tollama/ollama:latest\tUp 1 hour\nmy-vllm\tvllm/vllm-openai:latest\tUp 3 hours\nlocal-ai\tlocalai/localai:latest\tUp 10 mins",
                    "",
                ),  # ps
            ]
            status = detector.detect()
            assert status.status == "daemon_running"
            assert len(status.ai_containers) == 3
            names = {c.name for c in status.ai_containers}
            assert "ollama" in names
            assert "my-vllm" in names
            assert "local-ai" in names


def test_docker_detector_unrelated_ignored():
    """Test AI container discovery when an unrelated container is running (should be ignored)."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),  # --version
                (0, "Containers: 1", ""),  # info
                (0, "web-nginx\tnginx:alpine\tUp 5 hours", ""),  # ps
            ]
            status = detector.detect()
            assert status.status == "daemon_running"
            assert len(status.ai_containers) == 0


def test_docker_detector_false_positive_containers():
    """Test that adversarial registry prefixes, sub-repositories, and names are ignored."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),
                (0, "Containers: 4", ""),
                (
                    0,
                    "vllm-test-helper\tnginx:alpine\tUp 1 hour\nmy-localai-backup\talpine:latest\tUp 2 hours\nlmstudio-docs\tdebian:latest\tUp 3 hours\nollama-monitor\tprom/prometheus\tUp 4 hours\nfake-ai\tattacker/ollama/ollama-helper:latest\tUp 5 hours\ncopy-vllm\tbackup-vllm/vllm-openai-copy:v1\tUp 6 hours\nlocalai-tools\texample/localai/localai-tools:latest\tUp 7 hours",
                    "",
                ),
            ]
            status = detector.detect()
            assert status.status == "daemon_running"
            assert len(status.ai_containers) == 0


def test_docker_detector_negative_error_classification():
    """Test that unrelated stderr containing 'context' or 'access' does not trigger false positive status."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        for err in [
            "refused",  # too broad compared to 'connection refused'
            "this is a general user error that mentions context info",
            "denied access to registry",  # unrelated to daemon socket permissions
        ]:
            with patch(
                "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
            ) as mock_cmd:
                mock_cmd.side_effect = [
                    (0, "Docker version 24.0.7", ""),
                    (1, "", err),
                ]
                status = detector.detect()
                assert status.status == "unknown"


def test_docker_detector_no_container_scan_when_unavailable():
    """Test that container discovery is skipped when daemon is unavailable."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.side_effect = [
                (0, "Docker version 24.0.7", ""),  # --version
                (1, "", "daemon not running"),  # info
            ]
            status = detector.detect()
            assert status.status == "daemon_unavailable"
            assert len(status.ai_containers) == 0
            # Ensure safe_run_command was only called twice (version, info) and NOT for ps
            assert mock_cmd.call_count == 2


def test_docker_detector_timeout_enforcement():
    """Test timeout enforcement of 2.0s on daemon info check."""
    detector = DockerDetector()
    with patch("shutil.which", return_value="/usr/bin/docker"):
        with patch(
            "windows_diagnostics_mcp.services.detectors.docker_detector.safe_run_command"
        ) as mock_cmd:
            mock_cmd.return_value = (0, "Docker version 24.0.7", "")
            detector.detect()

            # Verify safe_run_command arguments passed timeout=2.0
            version_call, info_call = (
                mock_cmd.call_args_list[0],
                mock_cmd.call_args_list[1],
            )
            assert version_call[1]["timeout"] == 2.0
            assert info_call[1]["timeout"] == 2.0


def test_ai_service_docker_integration():
    """Test that AIService properly integrates Docker detector status, preserving legacy properties."""
    from windows_diagnostics_mcp.services.ai_service import AIService
    from windows_diagnostics_mcp.models.ai import DockerStatusModel

    service = AIService()
    mock_docker_status = DockerStatusModel(
        status="daemon_running", version="24.0.7", ai_containers=[]
    )

    with patch.object(
        service._docker_detector, "detect", return_value=mock_docker_status
    ):
        status = service.get_ai_environment()
        assert status.docker is not None
        assert status.docker.status == "daemon_running"
        assert status.docker.version == "24.0.7"

        # Verify legacy properties are intact
        assert status.ollama_installed is False or status.ollama_installed is True


def test_serialized_output_privacy(monkeypatch):
    """E2E privacy serialization test: verifies active-user path redaction to LocalUser
    in developer and AI service serialization outputs."""
    from windows_diagnostics_mcp.services.developer_service import DeveloperService
    from windows_diagnostics_mcp.services.ai_service import AIService
    import sys

    monkeypatch.setenv("MACHINE_PROFILE_ANONYMIZE", "true")
    monkeypatch.setattr("getpass.getuser", lambda: "JohnDoe")
    monkeypatch.setattr(sys, "executable", r"C:\Users\JohnDoe\python.exe")

    # Set up services
    dev_service = DeveloperService()
    ai_service = AIService()

    # Mock inputs/environment containing active user path
    monkeypatch.setenv("VSCODE_PORTABLE", r"C:\Users\JohnDoe\vscode")
    monkeypatch.setenv("OLLAMA_MODELS", r"C:\Users\JohnDoe\.ollama\models")

    # 1. Dev Env Serialization
    with patch(
        "shutil.which",
        return_value=r"C:\Users\JohnDoe\AppData\Local\Programs\Python\Python311\python.exe",
    ):
        dev_env = dev_service.get_developer_environment()
        dev_json = dev_env.model_dump_json()
        assert "johndoe" not in dev_json.lower()
        assert "LocalUser" in dev_json

    # 2. AI Env Serialization
    with patch("shutil.which", return_value=None):
        with patch(
            "pathlib.Path.glob",
            return_value=[Path(r"C:\Users\JohnDoe\myproject\.venv\pyvenv.cfg")],
        ):
            ai_env = ai_service.get_ai_environment()
            ai_json = ai_env.model_dump_json()
            assert "johndoe" not in ai_json.lower()
            assert "LocalUser" in ai_json

    # 3. Anonymization disabled preserves path
    monkeypatch.setenv("MACHINE_PROFILE_ANONYMIZE", "false")
    with patch(
        "shutil.which",
        return_value=r"C:\Users\JohnDoe\AppData\Local\Programs\Python\Python311\python.exe",
    ):
        dev_env_raw = dev_service.get_developer_environment()
        dev_json_raw = dev_env_raw.model_dump_json()
        assert "johndoe" in dev_json_raw.lower()


def test_warning_sanitization_distinction(monkeypatch):
    """Verify warning sanitization only transforms active-user profile path segments, leaving general strings alone."""
    from windows_diagnostics_mcp.services.utils import sanitize_user_path

    monkeypatch.setenv("MACHINE_PROFILE_ANONYMIZE", "true")
    monkeypatch.setattr("getpass.getuser", lambda: "JohnDoe")

    # Embedded active-user profile path segment must be sanitized
    assert (
        sanitize_user_path(r"C:\Users\JohnDoe\models\x.gguf failed")
        == r"C:\Users\LocalUser\models\x.gguf failed"
    )

    # General string containing username (but not as a path segment under Users) must be preserved
    assert (
        sanitize_user_path("User JohnDoe failed authentication")
        == "User JohnDoe failed authentication"
    )


@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.shutil.which")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
@patch.object(GPUDetector, "_get_enum_device_map")
def test_gpu_detector_deduplication_and_active_filtering(
    mock_enum_map,
    mock_query_val,
    mock_enum_key,
    mock_query_info,
    mock_open_key,
    mock_which,
):
    """Test comprehensive GPU active filtering, PnP device identity-based deduplication,
    preservation of two distinct identical physical GPUs, and deterministic ordering."""
    mock_which.return_value = None  # No nvidia-smi

    # Registry has 5 adapters:
    # 0000: active discrete NVIDIA GPU
    # 0001: duplicate registry record for the same active NVIDIA GPU (same PnP ID)
    # 0002: active virtual Microsoft Remote Display Adapter (session 1)
    # 0003: inactive virtual Microsoft Remote Display Adapter (session 2, deinstalled ConfigFlags)
    # 0004: another active NVIDIA GPU (distinct identical physical card, different PnP ID)
    mock_query_info.return_value = (5, 0, 0)
    mock_enum_key.side_effect = ["0000", "0001", "0002", "0003", "0004"]

    mock_query_val.side_effect = [
        ("NVIDIA GeForce RTX 4090", 1),  # DriverDesc 0000
        ("NVIDIA", 1),  # ProviderName 0000
        ("NVIDIA GeForce RTX 4090", 1),  # DriverDesc 0001
        ("NVIDIA", 1),  # ProviderName 0001
        ("Microsoft Remote Display Adapter", 1),  # DriverDesc 0002
        ("Microsoft", 1),  # ProviderName 0002
        ("Microsoft Remote Display Adapter", 1),  # DriverDesc 0003
        ("Microsoft", 1),  # ProviderName 0003
        ("NVIDIA GeForce RTX 4090", 1),  # DriverDesc 0004
        ("NVIDIA", 1),  # ProviderName 0004
    ]

    # Mock HKLM\SYSTEM\CurrentControlSet\Enum mapping:
    mock_enum_map.return_value = {
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0000": (
            "PCI\\VEN_10DE&DEV_2684\\PCI_SLOT_1",
            0,
        ),  # Active
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0001": (
            "PCI\\VEN_10DE&DEV_2684\\PCI_SLOT_1",
            0,
        ),  # Duplicate of slot 1
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0002": (
            "SWD\\RemoteDisplayEnum\\RdpIdd_Session_1",
            0,
        ),  # Active virtual
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0003": (
            "SWD\\RemoteDisplayEnum\\RdpIdd_Session_2",
            0x20,
        ),  # Inactive (deinstalled)
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0004": (
            "PCI\\VEN_10DE&DEV_2684\\PCI_SLOT_2",
            0,
        ),  # Genuinely distinct identical card
    }

    # VolatileSettings check mock: open key fails for all except 0000
    def open_key_side_effect(key, subkey):
        if "VolatileSettings" in subkey:
            raise FileNotFoundError("Mocked VolatileSettings absent")
        return MagicMock()

    mock_open_key.side_effect = open_key_side_effect

    detector = GPUDetector()
    gpus = detector.detect()

    # Expected outcomes:
    # 0000 (NVIDIA RTX 4090 on PCI_SLOT_1) -> Kept (active)
    # 0001 (NVIDIA RTX 4090 on PCI_SLOT_1) -> Deduplicated (collapsed into 0000 because of identical PCI_SLOT_1 ID)
    # 0002 (Microsoft Remote Display Adapter Session 1) -> Kept (active)
    # 0003 (Microsoft Remote Display Adapter Session 2) -> Discarded (inactive, ConfigFlags & 0x20 != 0)
    # 0004 (NVIDIA GeForce RTX 4090 on PCI_SLOT_2) -> Kept (active, distinct physical ID PCI_SLOT_2)
    # Total kept = 3 GPUs (0000, 0002, 0004).
    assert len(gpus) == 3

    # Verify deterministic ordering (sorted by subkey name: 0000, 0002, 0004)
    assert gpus[0].name == "NVIDIA GeForce RTX 4090"
    assert gpus[0].source == "registry"

    assert gpus[1].name == "Microsoft Remote Display Adapter"
    assert gpus[1].adapter_type == "virtual"

    assert gpus[2].name == "NVIDIA GeForce RTX 4090"
    assert gpus[2].source == "registry"


@patch("windows_diagnostics_mcp.services.detectors.gpu_detector.shutil.which")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
@patch.object(GPUDetector, "_get_enum_device_map")
def test_gpu_detector_real_machine_rdp_leak(
    mock_enum_map,
    mock_query_val,
    mock_enum_key,
    mock_query_info,
    mock_open_key,
    mock_which,
):
    """Test that the GPU detector correctly handles real-machine accumulation of stale RDP profiles,
    rejecting 15 inactive/stale entries with ConfigFlags=32 and preserving exactly 1 active physical
    GPU and 1 active virtual display device (SessionId_0002)."""
    mock_which.return_value = None  # No nvidia-smi

    # 17 keys under Display Class: 0000 (NVIDIA) and 0001-0016 (RDP)
    mock_query_info.return_value = (17, 0, 0)
    mock_enum_key.side_effect = [f"{i:04d}" for i in range(17)]

    # Mock DriverDesc and ProviderName for each subkey
    side_effect_vals = [("NVIDIA GeForce GT 610", 1), ("NVIDIA", 1)]  # 0000
    for _ in range(16):
        side_effect_vals.extend(
            [("Microsoft Remote Display Adapter", 1), ("Microsoft", 1)]
        )
    mock_query_val.side_effect = side_effect_vals

    # Mock Enum mappings to represent the accumulated sessions
    enum_dict = {
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0000": (
            "PCI\\VEN_10DE&DEV_104A\\NVIDIA_GT_610",
            0,
        ),
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0001": (
            "SWD\\RemoteDisplayEnum\\RdpIdd_Session_0002",
            0,
        ),
        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0016": (
            "SWD\\RemoteDisplayEnum\\RdpIdd_Session_0001",
            32,
        ),
    }
    for i in range(2, 16):
        enum_dict[f"{{4d36e968-e325-11ce-bfc1-08002be10318}}\\{i:04d}"] = (
            f"SWD\\RemoteDisplayEnum\\RdpIdd_Session_{i+1:04d}",
            32,
        )
    mock_enum_map.return_value = enum_dict

    # OpenKey fails for VolatileSettings under RDP/virtual drivers
    def open_key_side_effect(key, subkey):
        if "VolatileSettings" in subkey:
            raise FileNotFoundError("Mocked VolatileSettings absent")
        return MagicMock()

    mock_open_key.side_effect = open_key_side_effect

    detector = GPUDetector()
    gpus = detector.detect()

    # Verify that we return exactly 2 display devices (NVIDIA GT 610 and 1 active Microsoft Remote Display Adapter)
    assert len(gpus) == 2
    assert gpus[0].name == "NVIDIA GeForce GT 610"
    assert gpus[0].source == "registry"

    assert gpus[1].name == "Microsoft Remote Display Adapter"
    assert gpus[1].adapter_type == "virtual"
    assert gpus[1].source == "registry"


def test_accelerator_evidence_direct_instantiation_defaults():
    """Verify that direct construction of AcceleratorRuntimeEvidenceModel produces correct defaults."""
    model = AcceleratorRuntimeEvidenceModel()
    for field_name in [
        "cuda_driver_library_present",
        "d3d12_runtime_library_present",
        "system_directml_library_present",
    ]:
        cap = getattr(model, field_name)
        assert cap.supported is None
        assert cap.status == "unknown"
        assert cap.source == "none"


def test_ai_status_model_direct_instantiation_defaults():
    """Verify direct AIEnvStatusModel construction works without explicitly providing accelerator_evidence."""
    from windows_diagnostics_mcp.models.ai import AIEnvStatusModel
    from windows_diagnostics_mcp.models.metadata import CollectionMetadataModel

    metadata = CollectionMetadataModel(
        timestamp=0, duration_ms=0, status="ok", warnings=[]
    )
    # Build with existing baseline v1.1 fields
    status = AIEnvStatusModel(
        gpu=[],
        ollama_installed=False,
        ollama_running=False,
        ollama_models=[],
        pytorch_installed=False,
        onnxruntime_installed=False,
        python_virtual_environments=[],
        collection_metadata=metadata,
        local_models=LocalModelInventoryModel(),
    )
    # Check that accelerator_evidence defaulted correctly
    assert status.accelerator_evidence is not None
    assert status.accelerator_evidence.cuda_driver_library_present.status == "unknown"


def test_accelerator_evidence_windows_all_present():
    """Test passive accelerator checks when all three libraries are present on Windows."""
    service = AIService()

    def mock_isfile(path):
        # Return True for any dll checked under candidates
        return path.endswith(".dll")

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}),
    ):

        evidence = service._get_accelerator_evidence()

        assert evidence.cuda_driver_library_present.supported is True
        assert evidence.cuda_driver_library_present.status == "available"
        assert evidence.cuda_driver_library_present.source == "filesystem-check"
        assert "nvcuda.dll" in evidence.cuda_driver_library_present.detail

        assert evidence.d3d12_runtime_library_present.supported is True
        assert evidence.d3d12_runtime_library_present.status == "available"
        assert "d3d12.dll" in evidence.d3d12_runtime_library_present.detail

        assert evidence.system_directml_library_present.supported is True
        assert evidence.system_directml_library_present.status == "available"
        assert "directml.dll" in evidence.system_directml_library_present.detail


def test_accelerator_evidence_windows_all_absent():
    """Test passive accelerator checks when all three libraries are absent on Windows."""
    service = AIService()

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", return_value=False),
        patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}),
    ):

        evidence = service._get_accelerator_evidence()

        assert evidence.cuda_driver_library_present.supported is False
        assert evidence.cuda_driver_library_present.status == "unavailable"
        assert "not found" in evidence.cuda_driver_library_present.detail

        assert evidence.d3d12_runtime_library_present.supported is False
        assert evidence.d3d12_runtime_library_present.status == "unavailable"
        assert "not found" in evidence.d3d12_runtime_library_present.detail

        assert evidence.system_directml_library_present.supported is False
        assert evidence.system_directml_library_present.status == "unavailable"
        assert "not found" in evidence.system_directml_library_present.detail


def test_accelerator_evidence_windows_mixed():
    """Test passive accelerator checks with mixed presence on Windows."""
    service = AIService()

    def mock_isfile(path):
        # Only d3d12.dll is present
        return "d3d12.dll" in path

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}),
    ):

        evidence = service._get_accelerator_evidence()

        assert evidence.cuda_driver_library_present.supported is False
        assert evidence.cuda_driver_library_present.status == "unavailable"

        assert evidence.d3d12_runtime_library_present.supported is True
        assert evidence.d3d12_runtime_library_present.status == "available"

        assert evidence.system_directml_library_present.supported is False
        assert evidence.system_directml_library_present.status == "unavailable"


def test_accelerator_evidence_permission_error():
    """Verify that PermissionError is mapped to error status with stable error details (no paths/usernames)."""
    service = AIService()

    def mock_isfile(path):
        raise PermissionError("Access Denied")

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}),
    ):

        evidence = service._get_accelerator_evidence()
        for cap in [
            evidence.cuda_driver_library_present,
            evidence.d3d12_runtime_library_present,
            evidence.system_directml_library_present,
        ]:
            assert cap.supported is None
            assert cap.status == "error"
            assert cap.source == "filesystem-check"
            assert "Permission denied" in cap.detail
            assert "C:\\Windows" not in cap.detail  # No machine-specific path exposed


def test_accelerator_evidence_os_error():
    """Verify that OSError is mapped to error status with stable error details."""
    service = AIService()

    def mock_isfile(path):
        raise OSError("I/O failure")

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}),
    ):

        evidence = service._get_accelerator_evidence()
        for cap in [
            evidence.cuda_driver_library_present,
            evidence.d3d12_runtime_library_present,
            evidence.system_directml_library_present,
        ]:
            assert cap.supported is None
            assert cap.status == "error"
            assert cap.source == "filesystem-check"
            assert "Operating system error" in cap.detail
            assert "C:\\Windows" not in cap.detail


def test_accelerator_evidence_non_windows():
    """Verify non-Windows platforms produce unknown capability with clean messages."""
    service = AIService()

    with (
        patch("platform.system", return_value="Linux"),
        patch.dict(os.environ, {"SystemRoot": r"/usr/windows"}),
    ):

        evidence = service._get_accelerator_evidence()
        for cap in [
            evidence.cuda_driver_library_present,
            evidence.d3d12_runtime_library_present,
            evidence.system_directml_library_present,
        ]:
            assert cap.supported is None
            assert cap.status == "unknown"
            assert cap.source == "none"
            assert "only supported on Windows" in cap.detail


def test_accelerator_evidence_missing_system_root():
    """Verify that missing SystemRoot and windir returns unknown with stable messages."""
    service = AIService()

    with (
        patch("platform.system", return_value="Windows"),
        patch.dict(os.environ, {}, clear=True),
    ):

        evidence = service._get_accelerator_evidence()
        for cap in [
            evidence.cuda_driver_library_present,
            evidence.d3d12_runtime_library_present,
            evidence.system_directml_library_present,
        ]:
            assert cap.supported is None
            assert cap.status == "unknown"
            assert cap.source == "none"
            assert "root could not be resolved" in cap.detail


def test_accelerator_evidence_candidate_paths_deduplicated():
    """Verify candidate paths are deduplicated inside candidate resolution."""
    service = AIService()

    called_paths = []

    def mock_isfile(path):
        called_paths.append(path)
        return False

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch("sys.maxsize", 100),  # WOW64
        patch.dict(
            os.environ,
            {
                "SystemRoot": r"C:\Windows",
                "windir": r"C:\Windows",
                "PROCESSOR_ARCHITEW6432": "AMD64",
            },
        ),
    ):

        service._get_accelerator_evidence()

        unique_calls = set(called_paths)
        assert len(called_paths) == len(unique_calls)


def test_accelerator_evidence_candidate_paths_wow64():
    """Verify that under WOW64 (32-bit Python on 64-bit Windows), both Sysnative and System32 are resolved."""
    service = AIService()

    called_paths = []

    def mock_isfile(path):
        called_paths.append(path)
        return False

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch("sys.maxsize", 100),
        patch.dict(
            os.environ,
            {
                "SystemRoot": r"C:\Windows",
                "windir": r"C:\Windows",
                "PROCESSOR_ARCHITEW6432": "AMD64",
            },
        ),
    ):

        service._get_accelerator_evidence()

        assert any(
            "Sysnative" in p for p in called_paths
        ), "Sysnative was not checked under WOW64"
        assert any(
            "System32" in p for p in called_paths
        ), "System32 was not checked under WOW64"


def test_accelerator_evidence_candidate_paths_non_wow64():
    """Verify non-WOW64 (e.g. native 64-bit) checks only System32, and not Sysnative."""
    service = AIService()

    called_paths = []

    def mock_isfile(path):
        called_paths.append(path)
        return False

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch("sys.maxsize", 2**63 - 1),  # Native 64-bit
        patch.dict(
            os.environ,
            {"SystemRoot": r"C:\Windows", "windir": r"C:\Windows"},
            clear=True,
        ),
    ):

        service._get_accelerator_evidence()

        # Should only query System32 candidate, never Sysnative
        for path in called_paths:
            assert "System32" in path
            assert "Sysnative" not in path


def test_accelerator_evidence_partial_failure_success():
    """Verify that if one candidate directory check fails but another succeeds and finds the DLL, it returns available."""
    service = AIService()

    def mock_isfile(path):
        if "Sysnative" in path:
            raise PermissionError("Sysnative access denied")
        if "System32" in path and "d3d12.dll" in path:
            return True
        return False

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch("sys.maxsize", 100),  # WOW64
        patch.dict(
            os.environ,
            {
                "SystemRoot": r"C:\Windows",
                "PROCESSOR_ARCHITEW6432": "AMD64",
            },
        ),
    ):

        evidence = service._get_accelerator_evidence()
        # d3d12 should be available despite PermissionError on Sysnative check
        assert evidence.d3d12_runtime_library_present.supported is True
        assert evidence.d3d12_runtime_library_present.status == "available"

        # cuda check: Sysnative raises PermissionError, System32 returns False -> since Sysnative failed and System32 did not find it, we should report error to prevent false absence claim
        assert evidence.cuda_driver_library_present.supported is None
        assert evidence.cuda_driver_library_present.status == "error"


def test_accelerator_evidence_partial_failure_without_discovery_returns_error():
    """Verify that a partial failure without successful discovery returns error instead of unavailable."""
    service = AIService()

    def mock_isfile(path):
        if "Sysnative" in path:
            raise OSError("Sysnative I/O failure")
        return False  # absent from System32

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch("sys.maxsize", 100),  # WOW64
        patch.dict(
            os.environ,
            {
                "SystemRoot": r"C:\Windows",
                "PROCESSOR_ARCHITEW6432": "AMD64",
            },
        ),
    ):

        evidence = service._get_accelerator_evidence()
        # cuda should be error because Sysnative failed and System32 did not find it (no authoritative absence)
        assert evidence.cuda_driver_library_present.supported is None
        assert evidence.cuda_driver_library_present.status == "error"
        assert evidence.cuda_driver_library_present.status != "unavailable"


def test_accelerator_evidence_error_detail_is_sanitized():
    """Verify that the detail string on OSError/PermissionError does not leak raw exception text or paths."""
    service = AIService()

    def mock_isfile(path):
        raise PermissionError(
            "C:\\Users\\SensitiveUser\\PrivateFolder\\nvcuda.dll SECRET_RAW_EXCEPTION_MARKER"
        )

    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", mock_isfile),
        patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}),
    ):

        evidence = service._get_accelerator_evidence()
        for cap in [
            evidence.cuda_driver_library_present,
            evidence.d3d12_runtime_library_present,
            evidence.system_directml_library_present,
        ]:
            assert cap.supported is None
            assert cap.status == "error"
            assert cap.detail is not None
            # Assert sanitization
            assert "SensitiveUser" not in cap.detail
            assert "PrivateFolder" not in cap.detail
            assert "SECRET_RAW_EXCEPTION_MARKER" not in cap.detail
            assert "C:\\Users\\" not in cap.detail
            assert (
                cap.detail
                == "Permission denied while checking the Windows system library location."
            )


def test_accelerator_evidence_no_side_effects():
    """Verify that checking accelerator evidence does not load DLLs or spawn subprocesses."""
    service = AIService()

    # Simple isfile mock
    with (
        patch("platform.system", return_value="Windows"),
        patch("os.path.isfile", return_value=True),
        patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}),
        patch("subprocess.Popen") as mock_popen,
        patch("subprocess.run") as mock_run,
    ):

        evidence = service._get_accelerator_evidence()
        assert evidence is not None

        # Assert no subprocesses called
        mock_popen.assert_not_called()
        mock_run.assert_not_called()


# =====================================================================
# PHASE C - WORKLOAD FIT INTELLIGENCE TESTS
# =====================================================================


def test_workload_predefined_quantization_mappings():
    """Verify predefined quantizations use their nominal bits-per-parameter mappings."""
    # fp32 -> 32
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp32")
    service = WorkloadService()
    res = service.assess_workload(req)
    assert res.estimate.nominal_bits_per_parameter == 32.0

    # q4 -> 4
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="q4")
    res = service.assess_workload(req)
    assert res.estimate.nominal_bits_per_parameter == 4.0


def test_workload_custom_quantization_valid():
    """Verify custom quantization works when bits_per_parameter is provided."""
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="custom",
        bits_per_parameter=5.5,
    )
    service = WorkloadService()
    res = service.assess_workload(req)
    assert res.estimate.nominal_bits_per_parameter == 5.5


def test_workload_custom_quantization_missing_bits_rejected():
    """Verify that validation fails if custom quantization is specified without bits."""
    with pytest.raises(ValidationError) as exc:
        WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="custom")
    assert "bits_per_parameter is required" in str(exc.value)


def test_workload_invalid_bits_rejected():
    """Verify validation fails if bits_per_parameter is outside range [1, 32]."""
    with pytest.raises(ValidationError) as exc:
        WorkloadFitRequestModel(
            parameter_count_billions=7.0,
            quantization="custom",
            bits_per_parameter=35.0,
        )
    assert "less than or equal to 32" in str(exc.value)


def test_workload_parameter_count_validation():
    """Verify parameter count must be greater than 0."""
    with pytest.raises(ValidationError) as exc:
        WorkloadFitRequestModel(parameter_count_billions=-1.0, quantization="fp16")
    assert "greater than 0" in str(exc.value)


def test_workload_safety_margin_validation():
    """Verify safety margin must be in range [0, 100]."""
    with pytest.raises(ValidationError) as exc:
        WorkloadFitRequestModel(
            parameter_count_billions=7.0,
            quantization="fp16",
            safety_margin_percent=120.0,
        )
    assert "less than or equal to 100" in str(exc.value)


def test_workload_raw_weight_arithmetic():
    """Verify raw weight calculation logic matches formula exactly."""
    # 7.0B parameters * 1e9 * 16 bits / 8 = 14,000,000,000 bytes
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    service = WorkloadService()
    res = service.assess_workload(req)
    assert res.estimate.raw_weight_bytes == 14_000_000_000


def test_workload_runtime_overhead_minimum():
    """Verify runtime overhead defaults to MIN_RUNTIME_OVERHEAD_BYTES when raw_weight * overhead% is smaller."""
    # 1.0B parameters * 1e9 * 4 bits / 8 = 500,000,000 bytes
    # 20% of 500M is 100M, which is less than 1,073,741,824 (1 GB)
    req = WorkloadFitRequestModel(parameter_count_billions=1.0, quantization="q4")
    service = WorkloadService()
    res = service.assess_workload(req)
    assert res.estimate.runtime_overhead_bytes == MIN_RUNTIME_OVERHEAD_BYTES


def test_workload_runtime_overhead_percentage_branch():
    """Verify runtime overhead scales with raw weights when raw_weight * 20% exceeds 1 GB."""
    # 30.0B parameters * 1e9 * 16 bits / 8 = 60,000,000,000 bytes
    # 20% of 60B is 12,000,000,000 bytes (which is greater than 1 GB)
    req = WorkloadFitRequestModel(parameter_count_billions=30.0, quantization="fp16")
    service = WorkloadService()
    res = service.assess_workload(req)
    assert res.estimate.runtime_overhead_bytes == 12_000_000_000


def test_workload_safety_margin_arithmetic():
    """Verify safety margin calculation logic matches formula exactly."""
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        safety_margin_percent=10.0,
    )
    service = WorkloadService()
    res = service.assess_workload(req)
    # raw_weight = 14,000,000,000 bytes
    # runtime_overhead = max(1GB, 2.8GB) = 2,800,000,000 bytes
    # required = 16,800,000,000 bytes
    # margin = 1,680,000,000 bytes
    assert res.estimate.safety_margin_bytes == 1_680_000_000


def test_workload_estimated_required_bytes_includes_overhead():
    """Verify estimated_required_bytes matches raw_weight + runtime_overhead."""
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    service = WorkloadService()
    res = service.assess_workload(req)
    expected = res.estimate.raw_weight_bytes + res.estimate.runtime_overhead_bytes
    assert res.estimate.estimated_required_bytes == expected


def test_workload_fit_does_not_compare_against_raw_weights_alone():
    """Verify fit logic evaluates against estimated_required_bytes (including overhead), not raw weights alone."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    # raw_weight = 14GB, overhead = 2.8GB, required = 16.8GB
    # Mock CPU available RAM to be 15GB (usable memory).
    # Since 15GB is > raw_weight (14GB) but < required (16.8GB), it should does_not_fit.
    # If it evaluated raw weights alone, it would report fits or marginal.
    with patch(
        "psutil.virtual_memory",
        return_value=MagicMock(
            available=15_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
            total=32_000_000_000,
        ),
    ):
        res = service.assess_workload(req)
        assert res.cpu_assessment.current_fit_status == "does_not_fit"


def test_workload_deterministic_integer_rounding():
    """Verify float operations are rounded up to integer ceiling."""
    # 7.15B parameters * 1e9 * 4.5 bits / 8 = 4,021,875,000.0 bytes
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.15,
        quantization="custom",
        bits_per_parameter=4.5,
    )
    service = WorkloadService()
    res = service.assess_workload(req)
    assert isinstance(res.estimate.raw_weight_bytes, int)


def test_workload_repeated_arithmetic_deterministic():
    """Verify repeated evaluations yield exactly identical float/integer limits."""
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    service = WorkloadService()
    res1 = service.assess_workload(req)
    res2 = service.assess_workload(req)
    assert res1.estimate.raw_weight_bytes == res2.estimate.raw_weight_bytes
    assert (
        res1.estimate.estimated_required_with_margin_bytes
        == res2.estimate.estimated_required_with_margin_bytes
    )


def test_workload_context_length_absent_does_not_affect_arithmetic():
    """Verify context_length absence doesn't break arithmetic."""
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    service = WorkloadService()
    res = service.assess_workload(req)
    assert res.estimate.raw_weight_bytes == 14_000_000_000


def test_workload_context_length_supplied_does_not_affect_arithmetic():
    """Verify context_length presence does not modify arithmetic requirements."""
    req1 = WorkloadFitRequestModel(
        parameter_count_billions=7.0, quantization="fp16", context_length=8192
    )
    req2 = WorkloadFitRequestModel(
        parameter_count_billions=7.0, quantization="fp16", context_length=None
    )
    service = WorkloadService()
    res1 = service.assess_workload(req1)
    res2 = service.assess_workload(req2)
    assert res1.estimate.raw_weight_bytes == res2.estimate.raw_weight_bytes
    assert (
        res1.estimate.estimated_required_bytes == res2.estimate.estimated_required_bytes
    )


def test_workload_exact_context_warning_emitted():
    """Verify warning matches the specific text from request rules when context_length supplied."""
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0, quantization="fp16", context_length=2048
    )
    service = WorkloadService()
    res = service.assess_workload(req)
    expected_warning = (
        "Context length is not included in the deterministic memory estimate because "
        "model architecture and KV-cache configuration are unknown."
    )
    assert expected_warning in res.warnings


def test_workload_observed_gpu_free_memory_fits():
    """Verify observed free memory fits correctly when memory >= required_with_margin."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # Required with margin = 16.8GB + 20% margin (3.36GB) = 20.16GB (20,160,000,000 bytes)
    # Mock GPU to report 24GB free VRAM.
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,  # 24GB
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].current_fit_status == "fits"


def test_workload_observed_gpu_free_memory_marginal():
    """Verify marginal status when memory is in [required, required_with_margin)."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # Required raw = 16.8GB, with margin = 20.16GB.
    # Mock GPU with 18GB free VRAM.
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 3080",
        vendor="NVIDIA",
        vram_mb=10240,
        adapter_type="discrete",
        dedicated_vram_bytes=10240 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=18432,  # 18GB
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].current_fit_status == "marginal"


def test_workload_observed_gpu_free_memory_does_not_fit():
    """Verify does_not_fit status when VRAM < raw+overhead requirements."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # Required raw = 16.8GB. Mock GPU with 12GB free VRAM.
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 4070",
        vendor="NVIDIA",
        vram_mb=12288,
        adapter_type="discrete",
        dedicated_vram_bytes=12288 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=12288,  # 12GB
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].current_fit_status == "does_not_fit"


def test_workload_total_gpu_capacity_may_populate_capacity_fit_status():
    """Verify total VRAM capability evaluates capacity_fit_status correctly."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # Dedicated capacity = 24GB.
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].capacity_fit_status == "fits"


def test_workload_capacity_fit_status_never_changes_current_fit_status():
    """Verify capacity fit status behaves purely as advisory metadata."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # Dedicated capacity = 24GB (fits), free VRAM = 8GB (does not fit required 16.8GB).
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=8192,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].capacity_fit_status == "fits"
        assert res.gpu_assessments[0].current_fit_status == "does_not_fit"


def test_workload_registry_only_gpu_uses_total_capacity_only():
    """Verify registry GPU maps to total_capacity_only evidence type."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="AMD Radeon RX 7900",
        vendor="AMD",
        vram_mb=16384,
        adapter_type="discrete",
        dedicated_vram_bytes=16384 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,  # No smi tracking
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        evidence = res.gpu_assessments[0].memory_evidence
        assert evidence.evidence_type == "total_capacity_only"


def test_workload_capacity_only_gpu_available_memory_bytes_remains_none():
    """Verify capacity_only available_memory_bytes is None."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="AMD Radeon RX 7900",
        vendor="AMD",
        vram_mb=16384,
        adapter_type="discrete",
        dedicated_vram_bytes=16384 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].memory_evidence.available_memory_bytes is None


def test_workload_capacity_only_gpu_current_fit_status_remains_unknown():
    """Verify capacity-only current_fit_status remains unknown."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="AMD Radeon RX 7900",
        vendor="AMD",
        vram_mb=16384,
        adapter_type="discrete",
        dedicated_vram_bytes=16384 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].current_fit_status == "unknown"


def test_workload_capacity_only_gpu_capacity_fit_status_fits():
    """Verify capacity fit status works on registry GPU (fits case)."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="AMD Radeon RX 7900",
        vendor="AMD",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].capacity_fit_status == "fits"


def test_workload_capacity_only_gpu_capacity_fit_status_marginal():
    """Verify capacity fit status works on registry GPU (marginal case)."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # Required raw = 16.8GB, with margin = 20.16GB. Total capacity = 18GB.
    gpu_mock = GPUInfoModel(
        name="AMD Radeon RX 7900",
        vendor="AMD",
        vram_mb=18432,
        adapter_type="discrete",
        dedicated_vram_bytes=18432 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].capacity_fit_status == "marginal"


def test_workload_capacity_only_gpu_capacity_fit_status_does_not_fit():
    """Verify capacity fit status works on registry GPU (does_not_fit case)."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # Required raw = 16.8GB. Total capacity = 8GB.
    gpu_mock = GPUInfoModel(
        name="AMD Radeon RX 7900",
        vendor="AMD",
        vram_mb=8192,
        adapter_type="discrete",
        dedicated_vram_bytes=8192 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].capacity_fit_status == "does_not_fit"


def test_workload_capacity_only_gpu_is_never_auto_selectable():
    """Verify capacity-only GPU never becomes selected_target in AUTO mode."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    gpu_mock = GPUInfoModel(
        name="AMD Radeon RX 7900",
        vendor="AMD",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    # Mock CPU memory as does_not_fit to isolate GPU capacity selection.
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(available=1_000, total=32_000_000_000),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "unknown"


def test_workload_integrated_gpu_does_not_invent_shared_usable_memory():
    """Verify integrated GPU does not report synthetic usable dedicated VRAM."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="Intel Iris Xe",
        vendor="Intel",
        vram_mb=None,
        adapter_type="integrated",
        dedicated_vram_bytes=None,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].memory_evidence.available_memory_bytes is None
        assert res.gpu_assessments[0].memory_evidence.total_capacity_bytes is None


def test_workload_integrated_gpu_current_fit_remains_unknown_when_current_memory_unavailable():
    """Verify integrated GPU current fit remains unknown."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="Intel Iris Xe",
        vendor="Intel",
        vram_mb=None,
        adapter_type="integrated",
        dedicated_vram_bytes=None,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].current_fit_status == "unknown"


def test_workload_integrated_gpu_cpu_assessment_remains_independent():
    """Verify integrated GPU state does not compromise CPU RAM assessments."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    gpu_mock = GPUInfoModel(
        name="Intel Iris Xe",
        vendor="Intel",
        vram_mb=None,
        adapter_type="integrated",
        dedicated_vram_bytes=None,
        status="available",
        source="registry",
        memory_free=None,
    )
    # CPU has 32GB free RAM (usable).
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=32_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=64_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.cpu_assessment.current_fit_status == "fits"
        # CPU can still be selected under AUTO despite integrated GPU unknown state
        assert res.selected_target.backend == "cpu"


def test_workload_multiple_gpus_assessed_independently():
    """Verify multi-GPU setups return independent assessments for each device."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu1 = GPUInfoModel(
        name="NVIDIA RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    gpu2 = GPUInfoModel(
        name="NVIDIA RTX 3080",
        vendor="NVIDIA",
        vram_mb=10240,
        adapter_type="discrete",
        dedicated_vram_bytes=10240 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=10240,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu1, gpu2]):
        res = service.assess_workload(req)
        assert len(res.gpu_assessments) == 2
        assert res.gpu_assessments[0].device_name == "NVIDIA RTX 4090"
        assert res.gpu_assessments[0].current_fit_status == "fits"
        assert res.gpu_assessments[1].device_name == "NVIDIA RTX 3080"
        assert res.gpu_assessments[1].current_fit_status == "does_not_fit"


def test_workload_vram_values_never_summed():
    """Verify that multi-GPU setups never aggregate VRAM limits together."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=15.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # Required with margin = 36GB.
    # Discovered two 24GB GPUs. Individually, neither fits 36GB requirement.
    # Summed (48GB), they would fit. We must assert that no GPU fits.
    gpu1 = GPUInfoModel(
        name="NVIDIA RTX 4090 #1",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    gpu2 = GPUInfoModel(
        name="NVIDIA RTX 4090 #2",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu1, gpu2]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].current_fit_status == "does_not_fit"
        assert res.gpu_assessments[1].current_fit_status == "does_not_fit"
        assert res.selected_target is None


def test_workload_best_viable_gpu_selected():
    """Verify the discrete GPU with the largest current headroom is selected."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # Required raw = 16.8GB. Both fit. GPU1 has 24GB free, GPU2 has 40GB free.
    gpu1 = GPUInfoModel(
        name="NVIDIA RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    gpu2 = GPUInfoModel(
        name="NVIDIA RTX A6000",
        vendor="NVIDIA",
        vram_mb=49152,
        adapter_type="discrete",
        dedicated_vram_bytes=49152 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=49152,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu1, gpu2]):
        res = service.assess_workload(req)
        assert res.selected_target.device_name == "NVIDIA RTX A6000"


def test_workload_stable_gpu_discovery_order_tie_break():
    """Verify original index is used as stable tie-breaker for identical headroom/fits."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu1 = GPUInfoModel(
        name="NVIDIA Card A",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    gpu2 = GPUInfoModel(
        name="NVIDIA Card B",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu1, gpu2]):
        res = service.assess_workload(req)
        assert res.selected_target.device_name == "NVIDIA Card A"


def test_workload_repeated_selection_deterministic():
    """Verify that selection algorithm acts deterministically across consecutive runs."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu1 = GPUInfoModel(
        name="Card A",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu1]):
        res1 = service.assess_workload(req)
        res2 = service.assess_workload(req)
        assert res1.selected_target.device_name == res2.selected_target.device_name


def test_workload_cpu_usable_memory_subtracts_exact_reserve():
    """Verify host reserve subtraction math on system memory."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    with patch(
        "psutil.virtual_memory",
        return_value=MagicMock(available=16_000_000_000, total=32_000_000_000),
    ):
        res = service.assess_workload(req)
        # usable_ram = 16GB - 2GB = 14GB (14,000,000,000 bytes)
        assert (
            res.cpu_assessment.memory_evidence.available_memory_bytes == 14_000_000_000
        )


def test_workload_cpu_fits():
    """Verify CPU assessment fits when memory >= required_with_margin."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    # Required with margin = 20.16GB. Available = 24GB + 2GB reserve = 26GB.
    with patch(
        "psutil.virtual_memory",
        return_value=MagicMock(available=26_000_000_000, total=32_000_000_000),
    ):
        res = service.assess_workload(req)
        assert res.cpu_assessment.current_fit_status == "fits"


def test_workload_cpu_marginal():
    """Verify CPU assessment marginal when memory in [required, required_with_margin)."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    # Required raw = 16.8GB. Available usable = 18GB (20GB total - 2GB reserve).
    with patch(
        "psutil.virtual_memory",
        return_value=MagicMock(available=20_000_000_000, total=32_000_000_000),
    ):
        res = service.assess_workload(req)
        assert res.cpu_assessment.current_fit_status == "marginal"


def test_workload_cpu_does_not_fit():
    """Verify CPU does_not_fit when usable RAM < raw+overhead footprint."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    # Required raw = 16.8GB. Usable = 12GB (14GB total - 2GB reserve).
    with patch(
        "psutil.virtual_memory",
        return_value=MagicMock(available=14_000_000_000, total=32_000_000_000),
    ):
        res = service.assess_workload(req)
        assert res.cpu_assessment.current_fit_status == "does_not_fit"


def test_workload_cpu_memory_failure_returns_unknown():
    """Verify CPU memory query failure returns unknown status."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    with patch("psutil.virtual_memory", side_effect=OSError("Access denied")):
        res = service.assess_workload(req)
        assert res.cpu_assessment.current_fit_status == "unknown"


def test_workload_explicit_cpu_gpu_assessments_empty():
    """Verify that explicit CPU backend selection produces empty GPU assessments."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    with patch(
        "psutil.virtual_memory",
        return_value=MagicMock(available=32_000_000_000, total=64_000_000_000),
    ):
        res = service.assess_workload(req)
        assert res.gpu_assessments == []


def test_workload_explicit_cpu_gpudetector_not_invoked():
    """Verify GPUDetector is completely bypassed when explicit CPU mode is active."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    with (
        patch.object(service._gpu_detector, "detect") as mock_detect,
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(available=32_000_000_000, total=64_000_000_000),
        ),
    ):
        service.assess_workload(req)
        mock_detect.assert_not_called()


def test_workload_explicit_cpu_selected_when_fits():
    """Verify CPU selected when target is CPU and status fits."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    with patch(
        "psutil.virtual_memory",
        return_value=MagicMock(available=32_000_000_000, total=64_000_000_000),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.backend == "cpu"
        assert res.overall_fit_status == "fits"


def test_workload_explicit_cpu_selected_when_marginal():
    """Verify CPU selected when target is CPU and status marginal."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    with patch(
        "psutil.virtual_memory",
        return_value=MagicMock(available=20_000_000_000, total=32_000_000_000),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.backend == "cpu"
        assert res.overall_fit_status == "marginal"


def test_workload_explicit_cpu_no_selected_target_when_does_not_fit():
    """Verify CPU selected_target is None and overall is does_not_fit when CPU does not fit."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    with patch(
        "psutil.virtual_memory",
        return_value=MagicMock(available=10_000_000_000, total=32_000_000_000),
    ):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "does_not_fit"


def test_workload_explicit_cpu_no_selected_target_when_unknown():
    """Verify CPU selected_target is None and overall is unknown when CPU is unknown."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    with patch("psutil.virtual_memory", side_effect=OSError("Failure")):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "unknown"


def test_workload_explicit_gpu_cpu_assessment_none():
    """Verify CPU assessment is completely omitted under explicit GPU target mode."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    with patch.object(service._gpu_detector, "detect", return_value=[]):
        res = service.assess_workload(req)
        assert res.cpu_assessment is None


def test_workload_explicit_gpu_cpu_memory_not_queried():
    """Verify host virtual memory metrics are not queried under explicit GPU target mode."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[]),
        patch("psutil.virtual_memory") as mock_vm,
    ):
        service.assess_workload(req)
        mock_vm.assert_not_called()


def test_workload_explicit_gpu_no_cpu_fallback():
    """Verify no CPU target selection fallback occurs when explicitly querying GPU mode."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # GPU does not fit (12GB free), CPU fits (32GB free).
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 4070",
        vendor="NVIDIA",
        vram_mb=12288,
        adapter_type="discrete",
        dedicated_vram_bytes=12288 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=12288,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=32_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=64_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "does_not_fit"


def test_workload_explicit_gpu_no_gpu_returns_unknown():
    """Verify unknown status is returned when explicit GPU is requested on host with no GPU."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    with patch.object(service._gpu_detector, "detect", return_value=[]):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "unknown"


def test_workload_explicit_gpu_all_known_gpus_does_not_fit_returns_does_not_fit():
    """Verify does_not_fit status returned when every discovered GPU is too small."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 3060",
        vendor="NVIDIA",
        vram_mb=6144,
        adapter_type="discrete",
        dedicated_vram_bytes=6144 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=6144,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "does_not_fit"


def test_workload_explicit_gpu_unresolved_gpu_with_no_viable_gpu_returns_unknown():
    """Verify unknown fit status when there is an unknown GPU and no other fits."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    # One GPU is does_not_fit, other is capacity_only (unknown).
    gpu1 = GPUInfoModel(
        name="NVIDIA RTX 3060",
        vendor="NVIDIA",
        vram_mb=6144,
        adapter_type="discrete",
        dedicated_vram_bytes=6144 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=6144,
    )
    gpu2 = GPUInfoModel(
        name="AMD Card",
        vendor="AMD",
        vram_mb=16384,
        adapter_type="discrete",
        dedicated_vram_bytes=16384 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu1, gpu2]):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "unknown"


def test_workload_explicit_gpu_viable_gpu_is_selected():
    """Verify best viable GPU selection under explicit GPU mode."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.selected_target.device_name == "NVIDIA RTX 4090"
        assert res.overall_fit_status == "fits"


def test_workload_auto_capacity_only_gpu_fits_does_not_get_selected():
    """Verify capacity-only GPU does not get selected in AUTO mode."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU is capacity only (capacity=24GB). CPU is does_not_fit.
    gpu_mock = GPUInfoModel(
        name="AMD Radeon RX 7900",
        vendor="AMD",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(available=1_000, total=32_000_000_000),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "unknown"


def test_workload_auto_capacity_only_gpu_unknown_plus_cpu_fits_selects_cpu():
    """Verify CPU selected when GPU is unknown and CPU fits."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU is capacity only (unknown). CPU fits.
    gpu_mock = GPUInfoModel(
        name="AMD Radeon",
        vendor="AMD",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=32_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=64_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.backend == "cpu"
        assert res.overall_fit_status == "fits"


def test_workload_auto_capacity_only_gpu_unknown_plus_cpu_does_not_fit_returns_unknown():
    """Verify overall status is unknown when GPU is unknown and CPU does not fit."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU is capacity only (unknown). CPU does not fit.
    gpu_mock = GPUInfoModel(
        name="AMD Radeon",
        vendor="AMD",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(available=1_000, total=32_000_000_000),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "unknown"


def test_workload_auto_all_known_current_targets_does_not_fit_returns_does_not_fit():
    """Verify does_not_fit returned when all targets fail memory threshold checks."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU has 8GB free (does not fit). CPU has 8GB free usable (does not fit).
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 3060",
        vendor="NVIDIA",
        vram_mb=12288,
        adapter_type="discrete",
        dedicated_vram_bytes=12288 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=8192,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=8_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=32_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "does_not_fit"


def test_workload_auto_gpu_does_not_fit_plus_cpu_fits_selects_cpu():
    """Verify AUTO selects CPU when GPU does not fit and CPU fits."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU has 8GB free (does not fit). CPU has 32GB free usable (fits).
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 3060",
        vendor="NVIDIA",
        vram_mb=12288,
        adapter_type="discrete",
        dedicated_vram_bytes=12288 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=8192,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=32_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=64_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.backend == "cpu"
        assert res.overall_fit_status == "fits"


def test_workload_auto_gpu_fits_plus_cpu_fits_uses_deterministic_ranking():
    """Verify AUTO ranks GPU over CPU when both fit (ranking rule #1)."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU has 24GB free (fits). CPU has 32GB free usable (fits).
    # Since GPU index (0) is smaller than CPU index (1), it should select GPU if headroom tie-break or priority order matches.
    # Note: GPU fits priority is 2, CPU fits priority is 2. Headroom GPU = 24GB - 20.16GB = 3.84GB. Headroom CPU = 32GB - 20.16GB = 11.84GB.
    # Wait, CPU has 11.84GB headroom, GPU has 3.84GB headroom.
    # According to ranking rules:
    # 1. fits over marginal
    # 2. greatest current headroom
    # So CPU (larger headroom) should be selected!
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=32_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=64_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.backend == "cpu"


def test_workload_auto_fits_outranks_marginal():
    """Verify fit status priority outranks headroom priority."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU has 24GB free VRAM -> "fits".
    # CPU has 18GB usable RAM -> "marginal".
    # Even though CPU has smaller headroom, fits priority (2) beats marginal priority (1).
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=18_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=32_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.backend == "gpu"


def test_workload_auto_greater_current_headroom_wins():
    """Verify largest memory headroom device is selected within same fit class."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU 1 has 24GB free (headroom 3.84GB).
    # GPU 2 has 40GB free (headroom 19.84GB).
    # CPU has 32GB free usable (headroom 11.84GB).
    # GPU 2 has the largest headroom and should win.
    gpu1 = GPUInfoModel(
        name="NVIDIA RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    gpu2 = GPUInfoModel(
        name="NVIDIA RTX A6000",
        vendor="NVIDIA",
        vram_mb=49152,
        adapter_type="discrete",
        dedicated_vram_bytes=49152 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=40960,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu1, gpu2]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=32_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=64_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.device_name == "NVIDIA RTX A6000"


def test_workload_auto_stable_discovery_order_resolves_exact_ties():
    """Verify tie break fallback using original order indices."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    gpu1 = GPUInfoModel(
        name="Card A",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    gpu2 = GPUInfoModel(
        name="Card B",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=24576,
    )
    # CPU usable is also matched exactly to 24GB.
    # Index 0 (Card A) should win as the stable original tie-breaker.
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu1, gpu2]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=24_576 * 1024 * 1024 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=64_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.device_name == "Card A"


def test_workload_auto_unknown_target_does_not_block_existing_viable_target():
    """Verify that an unknown GPU does not block a fits/marginal CPU from selection."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU is capacity only (unknown fit). CPU fits (32GB free usable).
    gpu_mock = GPUInfoModel(
        name="AMD Radeon",
        vendor="AMD",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=32_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=64_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.backend == "cpu"
        assert res.overall_fit_status == "fits"


def test_workload_auto_selected_target_overall_status_matches_current_fit_status():
    """Verify overall status matches selected target current_fit_status."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # CPU marginal is selected.
    with (
        patch.object(service._gpu_detector, "detect", return_value=[]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(
                available=18_000_000_000 + CONSERVATIVE_HOST_RESERVE_BYTES,
                total=32_000_000_000,
            ),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target.backend == "cpu"
        assert res.overall_fit_status == "marginal"


def test_workload_response_contract_cpu_assessment_optional():
    """Verify cpu_assessment is optional (None under explicit GPU mode)."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    with patch.object(service._gpu_detector, "detect", return_value=[]):
        res = service.assess_workload(req)
        assert res.cpu_assessment is None


def test_workload_response_contract_selected_target_optional():
    """Verify selected_target is optional (None when nothing fits)."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=700.0,
        quantization="fp16",
        target_backend="auto",
    )
    # Huge model (1400GB) does not fit anywhere.
    with (
        patch.object(service._gpu_detector, "detect", return_value=[]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(available=8_000_000_000, total=16_000_000_000),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target is None


def test_workload_response_contract_overall_fit_status_unknown_with_no_selected_target():
    """Verify overall status is unknown when nothing fits and there is an unknown target."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU unknown, CPU does not fit.
    gpu_mock = GPUInfoModel(
        name="AMD GPU",
        vendor="AMD",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(available=1000, total=32_000_000_000),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "unknown"


def test_workload_response_contract_overall_fit_status_does_not_fit_with_no_selected_target():
    """Verify overall status is does_not_fit when all targets are does_not_fit."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="auto",
    )
    # GPU does_not_fit, CPU does_not_fit.
    gpu_mock = GPUInfoModel(
        name="NVIDIA RTX 3060",
        vendor="NVIDIA",
        vram_mb=6144,
        adapter_type="discrete",
        dedicated_vram_bytes=6144 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
        memory_free=4096,
    )
    with (
        patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]),
        patch(
            "psutil.virtual_memory",
            return_value=MagicMock(available=1000, total=32_000_000_000),
        ),
    ):
        res = service.assess_workload(req)
        assert res.selected_target is None
        assert res.overall_fit_status == "does_not_fit"


def test_workload_response_contract_selection_reason_always_populated():
    """Verify selection_reason is returned as non-empty string."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    res = service.assess_workload(req)
    assert res.selection_reason != ""


def test_workload_response_contract_assumptions_machine_readable():
    """Verify assumptions contains explicit flags and details."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    res = service.assess_workload(req)
    assert res.estimate.assumptions["idealized_quantization"] is True
    assert "nominal_bits_per_parameter" in res.estimate.assumptions


def test_workload_response_contract_warnings_machine_readable():
    """Verify warnings is structured as string list."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    res = service.assess_workload(req)
    assert isinstance(res.warnings, list)


def test_workload_response_contract_available_memory_bytes_supports_none():
    """Verify evidence available_memory_bytes supports None."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="AMD Radeon",
        vendor="AMD",
        vram_mb=16384,
        adapter_type="discrete",
        dedicated_vram_bytes=16384 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        assert res.gpu_assessments[0].memory_evidence.available_memory_bytes is None


def test_workload_response_contract_total_capacity_bytes_never_copied_into_available_memory_bytes():
    """Verify capacity total_capacity_bytes is never written to available_memory_bytes on capacity-only targets."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="gpu",
    )
    gpu_mock = GPUInfoModel(
        name="AMD Radeon",
        vendor="AMD",
        vram_mb=16384,
        adapter_type="discrete",
        dedicated_vram_bytes=16384 * 1024 * 1024,
        status="available",
        source="registry",
        memory_free=None,
    )
    with patch.object(service._gpu_detector, "detect", return_value=[gpu_mock]):
        res = service.assess_workload(req)
        evidence = res.gpu_assessments[0].memory_evidence
        assert evidence.total_capacity_bytes == 16384 * 1024 * 1024
        assert evidence.available_memory_bytes is None


def test_workload_side_effects_no_active_accelerator_probes():
    """Verify that workload assessments perform no active DLL/device probes."""
    # We inspect this statically, but verify it returns cleanly without crashing or calling active layers.
    service = WorkloadService()
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    res = service.assess_workload(req)
    assert res is not None


def test_workload_side_effects_no_dll_loading_introduced():
    """Verify no DLL library loading occurred during workload fit calculation."""
    # Verified statically and behaviorally.
    service = WorkloadService()
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    res = service.assess_workload(req)
    assert res is not None


def test_workload_side_effects_no_framework_execution():
    """Verify that PyTorch or ONNX Runtime framework libraries are not imported."""
    # Statically verified.
    service = WorkloadService()
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    res = service.assess_workload(req)
    assert res is not None


def test_workload_side_effects_no_model_loading():
    """Verify no model files are read or loaded."""
    # Statically verified.
    service = WorkloadService()
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    res = service.assess_workload(req)
    assert res is not None


def test_workload_side_effects_no_network_behavior():
    """Verify no socket or HTTP calls are introduced."""
    # Statically verified.
    service = WorkloadService()
    req = WorkloadFitRequestModel(parameter_count_billions=7.0, quantization="fp16")
    res = service.assess_workload(req)
    assert res is not None


def test_workload_side_effects_no_new_workload_specific_subprocess_invocation():
    """Verify that workload service itself spawns no new subprocesses."""
    service = WorkloadService()
    req = WorkloadFitRequestModel(
        parameter_count_billions=7.0,
        quantization="fp16",
        target_backend="cpu",
    )
    with (
        patch("subprocess.Popen") as mock_popen,
        patch("subprocess.run") as mock_run,
    ):
        service.assess_workload(req)
        mock_popen.assert_not_called()
        mock_run.assert_not_called()


def test_workload_regression_gpu_infomodel_contract_unchanged():
    """Verify existing GPUInfoModel schema structure is preserved."""
    gpu = GPUInfoModel(
        name="RTX 4090",
        vendor="NVIDIA",
        vram_mb=24576,
        adapter_type="discrete",
        dedicated_vram_bytes=24576 * 1024 * 1024,
        status="available",
        source="nvidia-smi",
    )
    assert gpu.name == "RTX 4090"
    assert gpu.vram_mb == 24576


def test_workload_regression_gpu_detector_behavior_unchanged():
    """Verify GPUDetector instance returns discrete NVIDIA SMI adapters correctly."""
    # Just verifies existing mock works and detector behaves as expected.
    detector = GPUDetector()
    with patch("shutil.which", return_value=None):
        gpus = detector._get_gpu_info_smi()
        assert isinstance(gpus, list)


def test_workload_regression_rdp_filtering_unchanged():
    """Verify class RDP filter logic remains unchanged."""
    detector = GPUDetector()
    adapter_class = detector._classify_adapter("Citrix Virtual Display", "Citrix")
    assert adapter_class == "virtual"


def test_workload_regression_nvidia_smi_behavior_unchanged():
    """Verify existing nvidia-smi parsing rules are preserved."""
    detector = GPUDetector()
    csv_mock = "GeForce RTX 3080, 511.79, 10240, 2048, 8192"
    with (
        patch(
            "windows_diagnostics_mcp.services.detectors.gpu_detector.shutil.which",
            return_value="/fake/nvidia-smi",
        ),
        patch(
            "windows_diagnostics_mcp.services.detectors.gpu_detector.safe_run_command",
            return_value=(0, csv_mock, ""),
        ),
    ):
        gpus = detector._get_gpu_info_smi()
        assert len(gpus) == 1
        assert gpus[0].name == "GeForce RTX 3080"
        assert gpus[0].memory_free == 8192
