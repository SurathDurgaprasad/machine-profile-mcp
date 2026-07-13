# Compatibility Matrix & Environment Status - MachineProfile MCP

This document lists the tested environments, compatibility matrix, and known limitations of the MachineProfile MCP Server based on actual evidence collected during validation.

---

## 1. Tested & Verified Environment

Only the following specific host environment has been verified via the E2E protocol test suite and service verification scripts during the Phase 9 release gate:

* **Operating System**: Windows 11 Pro (Version: 25H2, Build Number: 26200) [Verified on active host]
* **Processor (CPU)**: Intel Core Ultra 7
* **Graphics Hardware (GPU)**: Intel(R) Arc(TM) 140V GPU (detected via Registry display adapter query fallback) and Microsoft Remote Display Adapters [Verified on active host]
* **Python Runtime**: Python 3.14.4 (locally tested on active host), Python 3.10 - 3.13 (CI verified on Windows runners)
* **Local AI configurations**: Ollama installed but not running (empty models list), PyTorch and ONNX Runtime not installed in target workspace virtualenvs.
* **Network reachability**: Direct local network available, outbound internet connectivity probe successful without proxy.

All other setups are currently classified as **Not Yet Tested** to ensure engineering accuracy.

---

## 2. Compatibility Matrix

| Category | Component / Configuration | Status | Evidence |
| :--- | :--- | :--- | :--- |
| **OS** | Windows 11 Pro (25H2, Build 26200) | **Verified on real environment** | Checked via live `system_summary` tool during E2E validation. |
| **OS** | Windows 10 | *Not Yet Tested* | Checked via unit test mocks but not on live Windows 10 hardware. |
| **OS** | Windows Server 2019 / 2022 | *Not Yet Tested* | No test execution was performed on Server environments. |
| **OS** | Linux / macOS | **Unsupported** | Excluded by design due to Windows-specific API dependency (`winreg`, `%SystemDrive%`, Windows route commands). |
| **GPU** | Intel GPUs (e.g. Arc 140V) | **Verified on real hardware** | Successfully parsed name, vendor, and virtual VRAM from Class registry adapters path. |
| **GPU** | NVIDIA GPUs | *Not Yet Tested* | `nvidia-smi` was not present on the active test host, but fallback logic was validated by automated mock tests. |
| **GPU** | AMD GPUs | *Not Yet Tested* | Registry query validated by automated mock tests but not on live AMD hardware. |
| **GPU** | No dedicated GPU | **Verified on real hardware** | Succeeded on test host remote desktop display adapters. |
| **User Privileges** | Non-Admin User | **Verified on real environment** | Active test host ran E2E protocol tests under standard user space. |
| **Network** | Direct Outbound Internet | **Verified on real environment** | Socket connects to public DNS and HTTP test endpoints succeeded. |
| **Network** | Restricted Corporate Proxy | *Not Yet Tested* | The active test host has direct network access. Proxy handling has not been verified. |

---

## 3. Known Limitations

* **Read-Only**: This server provides diagnostic statistics and does not support administrative modifications (e.g., terminating processes, deleting files, restarting network interfaces).
* **PATH-based Tool Detection**: Developer tool detection checks only system `PATH` and standard local directories (e.g. local VS Code directories). Portable installations or custom tool paths not in `PATH` will report `not_detected`.
* **Process CPU Utilization**: Process CPU percentage is calculated over a 0.1-second sleep interval. This is a short-sample duration and may fluctuate compared to Windows Performance Monitor long-run averages.
