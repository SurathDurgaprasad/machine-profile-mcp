# MachineProfile MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP Protocol](https://img.shields.io/badge/MCP-Protocol-blue.svg)](https://modelcontextprotocol.io)

MachineProfile MCP is a read-only Model Context Protocol (MCP) server that gives AI assistants structured information about the local Windows machine they are running on.

Instead of exposing raw event logs, administrative service editors, or destructive command utilities, this server queries system specifications, resource loads, developer tooling paths, and local AI environments, providing structured machine diagnostics securely.

> [!IMPORTANT]
> **Read-Only Security Model**: This server is strictly read-only. It performs no write operations, registry updates, process terminations, package installations, or directory modifications. It runs entirely in standard user space and does not require administrator privileges.

---

## What It Does & Does Not Do

### What It Does (v1.1.0 Capabilities):
* **System & CPU Profile**: Reports Windows Edition, version, build number, boot uptime, and CPU hardware details (model, vendor, cores, logical processors, and frequency).
* **Machine Health**: Computes a heuristic 0-100 score indicating resource bottlenecks.
* **Running Processes**: Lists processes consuming the highest CPU or Memory.
* **Storage Summary**: Maps capacity, file system, and free space of mounted partitions.
* **Developer Environment**: Locates installation paths and versions of common runtimes (`python`, `git`, `node`, `docker`, `java`, `vscode`).
* **AI Environment & GPU Profile**: Queries GPU adapters (integrated/discrete), local package installations (`torch`, `onnxruntime`), and local Python virtualenvs.
* **GPU Deduplication**: Implements active/stale registry display adapter filtering and PnP-based hardware identity mapping to prevent stale/duplicate entries (e.g. Remote Display Adapters).
* **Offline Model Discovery**: Scans local directory tags and manifests for offline Ollama models (works even when the daemon is stopped) and LM Studio GGUF models (with depth/file bounds, quantization inference, and junction/symlink protection).
* **Docker Status & AI Containers**: Reports Docker CLI version and daemon connection status, alongside running AI-related container details (e.g., `ollama`, `vllm`, `localai`) via a strict image repository allowlist.
* **Privacy & Path Anonymization**: Supports path redaction when `MACHINE_PROFILE_ANONYMIZE=true` is enabled, sanitizing active-user profile folders (e.g., `C:\Users\LocalUser`) while leaving general usernames intact.
* **Network Topology**: Gathers DNS servers, gateway IPs, local addresses, and checks internet reachability.
* **Installed Developer Tools**: Exposes a summary checklist of local runtime availability.

### What It Does NOT Do:
* **No Administrative Privileges Required**: Avoids UAC prompts and administrative elevation.
* **No Administrative Actions**: Will not terminate tasks, restart interfaces, or edit registries.
* **No Event Log or BSOD Analysis**: Designed for profile scanning and state verification, not registry repair.

---

## Installation & Distribution

This project is packaged as a standard Python package exposing the console command `machine-profile`.

### Prerequisites
* **Operating System**: Windows OS (v1 Windows-only)
* **Python Runtime**: Python 3.10 - 3.13 (CI verified on Windows runners) and Python 3.14.4 (locally tested on Windows host)

---

### Option A: Clean Launch via `uvx` (No Installation Needed)
If using `uv` (recommended modern Python runner), the MCP client can run it directly:

* **Prerequisites**: [uv](https://astral.sh/uv) must be installed.
* **Claude Desktop Configuration**:
  ```json
  {
    "mcpServers": {
      "machine-profile": {
        "command": "uvx",
        "args": [
          "--from",
          "git+https://github.com/SurathDurgaprasad/machine-profile-mcp.git",
          "machine-profile"
        ]
      }
    }
  }
  ```

---

### Option B: Local User Space Isolation via `pipx`
Installs the server in an isolated virtual environment and exposes the console command `machine-profile` globally.

* **Prerequisites**: Python (3.10+) and [pipx](https://github.com/pypa/pipx) must be installed.
* **Command**: `pipx install git+https://github.com/SurathDurgaprasad/machine-profile-mcp.git`
* **Claude Desktop Configuration**:
  ```json
  {
    "mcpServers": {
      "machine-profile": {
        "command": "machine-profile"
      }
    }
  }
  ```

---

### Option C: Build and Install Wheel manually
For offline systems, build the package distribution wheel and install it in your environment.

* **Prerequisites**: Python (3.10+) and standard Python `build` library (`pip install build`).
1. **Build wheel**:
   ```powershell
   python -m build
   ```
2. **Install wheel in environment**:
   ```powershell
   pip install dist/machine_profile_mcp-1.1.0-py3-none-any.whl
   ```
3. **Claude Desktop Configuration**:
   ```json
   {
     "mcpServers": {
       "machine-profile": {
         "command": "python",
         "args": [
           "-m",
           "windows_diagnostics_mcp.server"
         ]
       }
     }
   }
   ```

---

## MCP Interface Catalog

### 1. MCP Tools

All tools return structured JSON payloads with performance metadata (`duration_ms` and `status`: `OK` | `PARTIAL` | `ERROR`).

| Tool Name | Description | Parameters | Returns |
| :--- | :--- | :--- | :--- |
| `system_summary` | Summary of Windows Edition, Version, Build Number, Hostname, and Uptime. | None | `SystemSummaryModel` |
| `machine_health` | Rule-based health scoring (0-100), warnings, recommendations, and top consumer processes. | None | `MachineHealthModel` |
| `developer_environment` | Location and version status of common tools (`python`, `git`, `node`, `docker`, `java`, `vscode`). | None | `DevEnvStatusModel` |
| `installed_tools` | Simplified check matrix (installed/version status) of dev tools including `ollama`. | None | `dict[str, ToolInfoModel]` |
| `ai_environment` | Details about GPU hardware, local packages (`torch`, `onnxruntime`), and local Ollama model files. | None | `AIEnvStatusModel` |
| `storage_summary` | Partition mappings, free space, and capacity utilization of local drives. | None | `StorageSummaryModel` |
| `running_processes` | Active process snapshots sorted by highest CPU and memory utilization. | `limit: int` (default `10`) | `ProcessListModel` |
| `network_summary` | DNS servers, gateway interface, local IPs, and outbound internet connectivity test. | None | `NetworkSummaryModel` |

### 2. MCP Resources

Exposes read-only snapshots of the host system's current state with MIME type `application/json`.

* `windows://system`: Returns a snapshot of system specifications and boot uptime.
* `windows://developer`: Returns a snapshot of installed development runtimes and IDEs.
* `windows://ai`: Returns a snapshot of GPU, Ollama state, and local ML packages.
* `windows://network`: Returns a snapshot of network routing, IPs, and DNS servers.

### 3. MCP Prompts

* `analyze_machine`: An instruction prompt that directs the LLM to call the registered diagnostic tools dynamically to compile a structured machine report, saving token context and avoiding unnecessary query overhead.

---

## Tested Environment & Evidence-Based Compatibility

* **Windows 11 Pro (25H2, Build 26200) with Intel CPU**: **Verified on real environment** (Tested on active host).
* **Intel Arc(TM) 140V GPU**: **Verified on real hardware** (Successfully parsed on host registry).
* **Non-Admin User space**: **Verified on real environment** (Tested UAC-free).
* **GPU Duplicate Adapter Fix**: **Validated via unit tests and local simulation**; physical revalidation on affected peer machine is **pending**.
* **Windows 10 physical validation**: **Pending** (Verified by unit test mock layers only).
* **AMD hardware validation**: **Pending** (Verified by unit test mock layers only).
* **Real LM Studio installation validation**: **Pending** (Verified by unit test mock layers only).
* **Active Docker AI-container validation**: **Pending** (Verified by unit test mock layers only).

---

## Testing & Verification

* Run unit tests:
  ```bash
  pytest windows_diagnostics_mcp/tests/test_diagnostics.py -v
  ```
* Run E2E protocol test:
  ```bash
  python -m windows_diagnostics_mcp.tests.e2e_mcp_test
  ```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) details.
