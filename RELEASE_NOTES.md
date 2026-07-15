# Release Notes - MachineProfile MCP v1.2.0

MachineProfile MCP v1.2.0 introduces CPU capability discovery, passive accelerator runtime evidence, and deterministic workload fit intelligence for Windows hosts.

---

## New Features & Capabilities

### 1. CPU Capability Discovery (Phase A)
* **Instruction Set Probing**: Queries the Windows kernel via `IsProcessorFeaturePresent` to determine OS-visible support for instruction sets:
  * **AVX** (`PF_AVX_INSTRUCTIONS_AVAILABLE`)
  * **AVX2** (`PF_AVX2_INSTRUCTIONS_AVAILABLE`)
  * **AVX512F** (`PF_AVX512F_INSTRUCTIONS_AVAILABLE`)
* **Behavior and Guardrails**:
  * **Windows x86/x64**: Queries processor features directly from the OS.
  * **Non-Windows / Non-x86_x64**: Returns `unknown` with descriptive metadata.
  * **Telemetry Failures**: API errors are caught and reported as `error` status. No raw traceback details leak to the client.
  * **Backward Compatibility**: Fully preserves all v1.1.0 CPU properties.

### 2. Passive Accelerator Runtime Evidence (Phase B)
* **Passive Library Verification**: Performs silent filesystem checks for system-provided dynamic link libraries inside `System32` (and `Sysnative` for WOW64 redirection contexts):
  * **CUDA Driver Library** (`nvcuda.dll`)
  * **D3D12 Runtime Library** (`d3d12.dll`)
  * **System DirectML Library** (`directml.dll`)
* **Read-Only / Low-Side-Effect Guardrails**:
  * **No DLL Loading**: Checks file existence using `os.path.isfile`. Does not call `ctypes.WinDLL`, `ctypes.windll`, `LoadLibrary`, or similar active loading mechanisms.
  * **No Subprocesses**: Bypasses active probes or process spawns.
  * **No GPU Initialization**: Does not invoke active device controls (`cuInit`, Direct3D or DirectML device creation).
  * **Important Limitation**: Passive file presence of a library **does not prove or verify actual runtime or device usability**, which depends on driver versions, hardware compatibility, and execution environments.

### 3. Workload Fit Intelligence (Phase C)
* **New MCP Tool**: Adds the `assess_workload_fit` tool to FastMCP.
* **Deterministic Memory Footprint Estimation**:
  * **Raw Model Weight Size**: Calculated as $\lceil \text{parameter\_count\_billions} \times 10^9 \times \frac{\text{bits\_per\_parameter}}{8} \rceil$.
  * **Runtime Execution Overhead**: Heuristically estimated as $\lceil \max(1\text{ GiB}, \text{raw\_weight} \times 0.20) \rceil$.
  * **Configurable Safety Margin**: Calculated as $\lceil (\text{raw\_weight} + \text{overhead}) \times \frac{\text{safety\_margin\_percent}}{100} \rceil$.
  * **Rounding Semantics**: All calculations are completed using deterministic upward integer ceiling rounding (`math.ceil`) at each step. *Note: Intermediate ceiling rounding may alter byte-exact boundary outcomes slightly.*
* **Telemetry Evidence Extraction**:
  * **GPU VRAM**: Extracts available VRAM from nvidia-smi if accessible (`observed_free_memory`). Maps registry-discovered GPUs to total capacity only (`total_capacity_only`) with available memory set to `None` and current fit status set to `unknown`.
  * **CPU usable memory**: Queries available system RAM and reserves exactly `2,000,000,000` bytes (2 GB) for host processes.
* **Fit Decisions and Target Selection**:
  * **Target Backend Options**: Supports `cpu`, `gpu`, and `auto` modes.
  * **AUTO Target Ranking**: Only backends reporting `fits` or `marginal` are eligible for selection. Backends are ranked using priority (`fits` over `marginal`), greatest available memory headroom, and stable index tie-breakers.
  * **Important Limitations**:
    * **No VRAM Pooling**: VRAM capacities of multiple GPUs are evaluated independently and never aggregated.
    * **Estimates Only**: All outcomes are mathematical estimates based on bounded assumptions, **not guaranteed runtime execution fits**.
    * **KV Cache & Activations**: KV cache, activation memory, and engine-specific memory allocations are not modeled.
    * **Context Length**: The `context_length` argument is strictly informational and is **excluded from memory calculations** because model architecture and KV-cache configurations are unknown. A specific warning is returned if it is supplied.

---

## Compatibility & Verification
* **Additive Surface**: All existing tools (`system_summary`, `ai_environment`, etc.), resources, and prompts from v1.1.0 are fully preserved.
* **Runtime Support**: Fully tested and verified across Python 3.10, 3.11, 3.12, 3.13, and 3.14.4 on Windows environments.
