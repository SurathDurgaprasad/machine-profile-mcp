# Testing & Verification Guide - MachineProfile MCP

This document describes how to execute the testing suite, performance benchmarks, and programmatic E2E protocol validation for the MachineProfile MCP Server.

---

## 1. Unit Tests (`pytest`)

We maintain a mock-based unit test suite in `windows_diagnostics_mcp/tests/test_diagnostics.py`. It uses `unittest.mock` to mock all OS layers to run deterministically on any hardware.

To run the unit tests:
```bash
pytest windows_diagnostics_mcp/tests/test_diagnostics.py -v
```
*Verification status: Passed (all 17 unit tests succeeded in 0.47s).*

---

## 2. Live Services Verification

To query the *actual* Windows host system APIs without mocks and print the output schemas, run:
```bash
python -m windows_diagnostics_mcp.tests.verify_services
```

To verify that the MCP tools, resources, and prompts register cleanly on the server, run:
* Verify tools: `python -m windows_diagnostics_mcp.tests.verify_tools`
* Verify resources: `python -m windows_diagnostics_mcp.tests.verify_resources`
* Verify prompts: `python -m windows_diagnostics_mcp.tests.verify_prompts`

---

## 3. Performance Benchmarks

To measure the latency of all 8 diagnostic collection tools and evaluate compliance with performance budgets, run:
```bash
python -m windows_diagnostics_mcp.tests.benchmark_tools
```

---

## 4. True End-to-End MCP Protocol Test

We maintain a true E2E protocol client validation script in `windows_diagnostics_mcp/tests/e2e_mcp_test.py`.
This script:
1. Spawns the packaged server.
2. Uses the official Python MCP SDK client components (`stdio_client` and `ClientSession`) to establish a JSON-RPC transport connection over the subprocess standard input/output streams.
3. Conducts initialization and capability negotiations.
4. Executes calls for all 8 tools, reads all 4 resources, and fetches prompt templates.
5. Verifies schema validity of all outputs, confirms there are no tracebacks, and asserts graceful error mappings.
6. Terminates the server process cleanly.

To run the E2E protocol test:
```bash
python -m windows_diagnostics_mcp.tests.e2e_mcp_test
```
*Verification status: Successfully called and validated all 8 tools, 4 resources, and the prompt template over standard JSON-RPC stdin/stdout.*
