import sys
import time
import pathlib
import socket
from unittest.mock import MagicMock, patch
import pytest

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
@patch("windows_diagnostics_mcp.services.ai_service.safe_run_command")
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
@patch("windows_diagnostics_mcp.services.ai_service.safe_run_command")
@patch("httpx.get")
@patch("pathlib.Path.glob")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
def test_ai_service_fallback_registry(
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
@patch("windows_diagnostics_mcp.services.ai_service.safe_run_command")
@patch("httpx.get")
@patch("pathlib.Path.glob")
@patch("winreg.OpenKey")
@patch("winreg.QueryInfoKey")
@patch("winreg.EnumKey")
@patch("winreg.QueryValueEx")
def test_ai_service_ambiguous_hardware(
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
    assert res.gpu[0].adapter_type == "unknown"
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
