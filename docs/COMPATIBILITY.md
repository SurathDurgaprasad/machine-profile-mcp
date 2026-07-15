# Compatibility Matrix & Environment Status - MachineProfile MCP v1.1.0

This document lists the tested environments, compatibility matrix, and known validation status of the MachineProfile MCP Server based on actual evidence collected during v1.1.0 release preparation.

---

## 1. Tested & Verified Environment

Only the following specific host environment has been verified via the E2E protocol test suite and service verification scripts during the v1.1.0 release validation gate:

* **Operating System**: Windows 11 Pro (Version: 25H2, Build Number: 26200) [Verified on active host]
* **Processor (CPU)**: Intel Core Ultra 7 [Verified on active host]
* **Graphics Hardware (GPU)**: Intel(R) Arc(TM) 140V GPU [Verified on active host]
* **Python Runtime**: Python 3.14.4 (locally tested on active host), Python 3.10 - 3.13 (CI verified on Windows runners)
* **Local AI configurations**:
  - Ollama: CLI detected, daemon stopped. Offline discovery successful (3 models found: nomic-embed-text:latest, qwen2.5-coder:7b, qwen3:14b).
  - LM Studio: Not installed on active host (verified fallback).
  - Docker: CLI version 29.5.3 detected, daemon status resolved as `daemon_unavailable`.
* **Path Anonymization**: Verified absolute path redaction to `LocalUser` when `MACHINE_PROFILE_ANONYMIZE=true`.
* **Network reachability**: Direct local network available, outbound internet connectivity probe successful without proxy.

---

## 2. Compatibility Matrix

| Category | Component / Configuration | Status | Evidence |
| :--- | :--- | :--- | :--- |
| **OS** | Windows 11 Pro (25H2, Build 26200) | **Verified on real environment** | Checked via live `system_summary` tool during E2E validation. |
| **OS** | Windows 10 | **Pending physical validation** | Checked via unit test mocks only. |
| **OS** | Windows Server 2019 / 2022 | **Pending physical validation** | No test execution was performed on Server environments. |
| **OS** | Linux / macOS | **Unsupported** | Excluded by design due to Windows-specific API dependency (`winreg`, `%SystemDrive%`, Windows route commands). |
| **CPU** | Intel CPUs (Ultra 7) | **Verified on real hardware** | Parsed model, vendor, physical cores, logical processors, and frequency. |
| **CPU** | AMD CPUs | **Pending physical validation** | Verified by unit test mock layers only. |
| **GPU** | Intel GPUs (e.g. Arc 140V) | **Verified on real hardware** | Successfully parsed name and integrated type; VRAM correctly reports `null`. |
| **GPU** | NVIDIA GPUs | **Verified on real hardware / Fix Pending Revalidation** | `nvidia-smi` queries discrete GPU and VRAM on peer machine (GeForce GT 610). **Physical revalidation of duplicate adapter fix on the peer machine is pending.** |
| **GPU** | AMD GPUs | **Pending physical validation** | Registry query validated by automated mock tests but not on live AMD hardware. |
| **GPU** | Duplicate virtual GPUs | **Locally corrected and verified** | Inactive display registry adapters (e.g. Microsoft Remote Display Adapter) filtered. **Physical revalidation on the peer machine is pending.** |
| **Ollama** | Offline Model Discovery | **Verified on real environment** | Local manifests scanned and mapped with sizes even when daemon is stopped. |
| **LM Studio** | Offline GGUF Discovery | **Pending physical validation** | Traversal bounds and quantization parsing validated by mock tests. |
| **Docker** | Daemon status & containers | **Locally verified** | Docker status resolved. Container image Allowlist matching validated by mock tests. |
| **User Privileges** | Non-Admin User | **Verified on real environment** | Active test host ran E2E protocol tests under standard user space. |
| **Network** | Direct Outbound Internet | **Verified on real environment** | Socket connects to public DNS and HTTP test endpoints succeeded. |
| **Network** | Restricted Corporate Proxy | **Pending physical validation** | The active test host has direct network access. |

---

## 3. Known Limitations

* **Read-Only**: This server provides diagnostic statistics and does not support administrative modifications (e.g., terminating processes, deleting files, restarting network interfaces).
* **PATH-based Tool Detection**: Developer tool detection checks only system `PATH` and standard local directories (e.g. local VS Code directories). Portable installations or custom tool paths not in `PATH` will report `not_detected`.
* **Process CPU Utilization**: Process CPU percentage is calculated over a 0.1-second sleep interval. This is a short-sample duration and may fluctuate compared to Windows Performance Monitor long-run averages.
