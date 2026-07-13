# Windows Diagnostic Heuristics & Detection Systems

This document describes the algorithms and detection strategies utilized by the core service classes to evaluate host system diagnostics.

---

## 1. Machine Health Scoring & Warnings (HealthService)

The `HealthService` calculates a heuristic health score starting at `100` and applies deductions based on resource boundaries.

### Scoring Deductions Matrix
* **CPU Stress**: If CPU utilization is > 80%, subtracts `15` points. Creates a warnings list item. Severity is `critical` if CPU is > 95%, otherwise `warning`.
* **Memory Stress**: If RAM utilization is > 85%, subtracts `15` points. Creates a warnings list item. Severity is `critical` if RAM is > 95%, otherwise `warning`.
* **Storage Capacity Stress**: Queries the Windows installation system drive dynamically using `%SystemDrive%`.
  * If free space is < 10.0 GB, subtracts `20` points. Severity is `critical` if free space is < 5.0 GB, otherwise `warning`.
  * If drive utilization is > 90.0% (but free space is >= 10GB), subtracts `10` points. Severity is `warning`.
* **Startup Applications Bloat**: Counts values in registry Run keys (`HKCU` and `HKLM`). If total startup applications count is > 15, subtracts `5` points. Severity is `warning`.

*The score is bounded to a minimum of 0 and maximum of 100.*

---

## 2. Centralized Registry Startup Count Check
The `HealthService` counts auto-start configurations inside the standard Windows Registry Run keys:
* `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
* `HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Run`

Each value entry inside these paths represents an executable that launches on Windows user logon.

---

## 3. Layered GPU Detection System (AIService)
The `AIService` utilizes a layered detection framework to resolve GPU hardware on various graphics architectures:

1. **Primary Layer (`nvidia-smi`)**: Probes PATH and standard install directories (`C:\Windows\System32\nvidia-smi.exe`, `C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe`). If found, executes with `--query-gpu` flags to extract NVIDIA model names, driver versions, and total/used/free VRAM.
2. **Secondary Layer (Windows Registry display adapters class)**: If `nvidia-smi` is unavailable (such as on Intel, AMD, or virtual machines), scans subkeys under:
   `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}`
   * Reads `DriverDesc` for device name.
   * Reads `ProviderName` to identify the vendor (e.g. Intel, AMD).
   * Reads `HardwareInformation.MemorySize` for total VRAM bytes.
3. **Merge Engine**: Merges registry results with `nvidia-smi` findings (ignoring duplicate records based on substring matching) to present a consolidated report of all display adapters.

---

## 4. Multi-Target Outbound Network Check (NetworkService)
To avoid false-negative "offline" statuses when Google DNS (`8.8.8.8`) is blocked by corporate VPN firewalls or localized network settings, the `NetworkService` probes multiple reachability targets sequentially with a strict 1.0s timeout per attempt:

* Target 1: `8.8.8.8:53` (Google DNS - standard TCP/UDP check)
* Target 2: `1.1.1.1:53` (Cloudflare DNS - alternative DNS check)
* Target 3: `clients3.google.com:80` (HTTP check)
* Target 4: `www.msftconnecttest.com:80` (Standard Windows Connection Probe)

If any connection succeeds, the system reports `internet_connected=True` and `internet_reachability_check="success"`. If all time out, it returns status `"timeout"`. If sockets raise direct network errors, it returns `"failed"`.
