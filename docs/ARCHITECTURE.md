# Architecture Overview - MachineProfile MCP Server

This document outlines the architectural layers and directory structure of the MachineProfile MCP Server.

## Layered Design Pattern

The project is structured around a strict layered design to isolate MCP protocol concerns from system integration and diagnostic calculations:

```
            +-------------------------------------------+
            |  MCP Interface (tools, resources, prompt)  |
            +-------------------------------------------+
                                  │
                                  ▼
            +-------------------------------------------+
            |   Core Services (health calculations)     |
            +-------------------------------------------+
                                  │
                                  ▼
            +-------------------------------------------+
            |   Subprocess & OS API Integration Layer   |
            +-------------------------------------------+
```

1. **MCP Interface Layer**: Translates MCP protocol requests (STDIO transport) into core service invocations. Employs Pydantic schemas to validate and serialize data returned to the client.
2. **Core Services Layer**: Encapsulates business logic, system rule parsing, and diagnostic heuristic scoring. Reuses data from other services to compile summary states.
3. **OS API Integration Layer**: Interfaces directly with the Windows environment using registry APIs (`winreg`), monitoring frameworks (`psutil`), and local CLI utility spawns (using the safe subprocess wrapper).

---

## Package Component Layout

The code is contained in the `windows_diagnostics_mcp` module:

* `server.py`: Server bootstrap file. Initializes all services, imports tool/resource/prompt modules, registers handlers on FastMCP, and runs the stdio transport listener loop.
* `models/`: Contains the Pydantic schemas representing serializable JSON data objects.
  * `metadata.py`: Defines shared performance timers and warnings list parameters.
  * `system.py`, `process.py`, `storage.py`, `developer.py`, `ai.py`, `network.py`, `health.py`: Define target data shapes for each tool.
* `services/`: Contains classes query-mapping OS configurations.
  * `subprocess_helper.py`: Shared subprocess utility that runs system executables windowlessly with timeouts.
  * `system_service.py`: Queries edition registry and parses boot uptime.
  * `process_service.py`: Employs double-pass caching CPU checks on processes.
  * `storage_service.py`: Resolves space usage of mounted local storage.
  * `developer_service.py`: Verifies compiler PATH runtimes.
  * `ai_service.py`: Resolves GPU status, Ollama tagging APIs, and workspace venvs.
  * `network_service.py`: Resolves DNS servers, default gateway, and tests reachability targets.
  * `health_service.py`: Calculates heuristic score and compiles recommendations.
* `tools/`: Declares and registers MCP tools onto the FastMCP server.
* `resources/`: Declares and registers dynamic MCP resources (`windows://`).
* `prompts/`: Registers the prompt template directing models to dynamically run diagnostics.
* `tests/`: Automated unit, verification, and end-to-end tests.

---

## Safe Subprocess Execution

To avoid system commands blocking the MCP communication stream indefinitely, the service layers execute CLI binaries exclusively via `safe_run_command` in `subprocess_helper.py`. This helper enforces:
* **Explicit Timeouts**: Kills stuck processes if they run longer than a strict 2-3s boundary.
* **No Console Popups**: Uses the Windows process creation flag `CREATE_NO_WINDOW` to prevent terminal CMD frames flashing when Claude queries system data.
* **Byte-Safe Multi-Encoding Decoders**: Decodes outputs by falling back through UTF-8, CP1252 (Windows English default), GBK (Windows Chinese default), and ASCII, protecting the server against UnicodeDecodeError failures on localized OS variants.
