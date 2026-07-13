# Model Context Protocol (MCP) Concepts

This document explains the Model Context Protocol (MCP) using the concrete implementations, files, and classes in this project.

---

## 1. What is an MCP Server?
An MCP server is a standardized backend service that exposes local data and capabilities to large language models (LLMs) via the Model Context Protocol. In this project, `server.py` is the main entry point that bootstraps our MCP server using the Python MCP SDK's `FastMCP` framework.

---

## 2. Server Startup & Stdio Transport
The server is designed to communicate with an MCP client (like Claude Desktop) using standard input/output streams (`stdio` transport).

* **How it starts**: The client launches the server process in the background:
  ```bash
  python server.py
  ```
* **Stdio communication**: The client writes JSON-RPC messages directly to the server's `stdin` stream, and the server responds by writing JSON-RPC messages to its `stdout` stream.
* **Logging boundary**: Because stdout is reserved for protocol frames, all server log statements are written exclusively to `stderr`. This prevents raw logs from corrupting the JSON-RPC stream.

---

## 3. Handshake & Initialization
When the client starts the server process, it triggers a handshake lifecycle:

```
Client                                     Server (server.py)
  │                                                │
  ├────── JSON-RPC "initialize" ──────────────────>┤ (FastMCP starts up)
  │                                                │
  ├<───── Capability Negotiation ──────────────────┤ (Reports version, resources, tools)
  │                                                │
  ├────── JSON-RPC "initialized" notification ─────>┤ (Handshake complete)
```

During initialization, the server negotiates protocol versions and publishes its capability capabilities (Tools list, Resources list, Prompts list).

---

## 4. MCP Tools & Dynamic Schema Generation

### What is a Tool?
A Tool is an executable capability exposed by the server. Tools can accept parameters from the LLM, perform operations, and return structured output.

### How Tool Discovery and Schema Generation Works
When registering a tool in FastMCP using decorators, the SDK automatically inspects the Python function's signature and type hints. It compiles these into a **JSON Schema** that is sent to the client during the `tools/list` request.

For example, our `running_processes` tool:
```python
@mcp.tool()
def running_processes(limit: int = 10) -> ProcessListModel:
    return process_service.get_processes(limit)
```
Generates a JSON Schema that informs the LLM:
* The tool accepts an optional argument `limit` of type `integer`.
* The tool returns a structured JSON payload conforming to the Pydantic `ProcessListModel`.

---

## 5. MCP Resources

### What is a Resource?
A Resource is a read-only data source identified by a unique URI scheme (similar to URLs). In this project, we register resources like:
* `windows://system`
* `windows://developer`
* `windows://ai`
* `windows://network`

### Why have Resources when we already have Tools?
* **Tools are executable actions**: The model decides when to execute them and supplies arguments dynamically. They are used for calculations, searches, and operations.
* **Resources are data attachments**: They represent static or dynamic documents that the client can fetch and read-mount directly into the model's context. Resources declare a `mime_type` (like `application/json`), making them ideal for exposing structured, read-only system snapshots.

---

## 6. MCP Prompts

An MCP Prompt is a predefined instruction template that the client can request from the server.
In `prompts/analyze_machine.py`, we expose `analyze_machine`. Instead of pre-fetching hardcoded snapshots (which inflates the context window and triggers slow, expensive queries), it returns a structured markdown instruction directing the LLM to call the appropriate tools (like `system_summary`, `machine_health`, etc.) dynamically as needed.

---

## 7. End-to-End Call Execution Flow

Here is a concrete trace of what happens when a user asks Claude Desktop: **"Why is my PC slow?"**

```
   User Message: "Why is my PC slow?"
        │
        ▼
  Claude Desktop
        │
        ├─► [1] MCP tools/list
        │   ◄─ Returns registered tools list (including 'machine_health')
        │
        ├─► [2] Decides to call 'machine_health' tool
        │
        ├─► [3] Send JSON-RPC tools/call request:
        │       { "method": "tools/call", "params": { "name": "machine_health" } }
        │
        ▼
   MachineProfile MCP Server
        │
        ├─► [4] Routes request to tools/health.py -> machine_health()
        │
        ├─► [5] Invokes HealthService.get_machine_health()
        │
        ├─► [6] Queries psutil for CPU / RAM / Startup Apps
        │       Queries StorageService for system drive utilization
        │       Queries ProcessService for top CPU/Memory consumers
        │
        ├─► [7] Computes heuristic score, warnings, and recommendations
        │
        ├─► [8] Compiles result into Pydantic MachineHealthModel
        │
        ◄─  [9] Serializes to JSON and writes JSON-RPC response to stdout
        │
  Claude Desktop
        │
        ├─► [10] Parses JSON payload
        │        Sees health_score is 65, and cpu_utilization is 90%
        │        Sees warning about "high_cpu_processes" (e.g., cpu_hog.exe at 85%)
        │
        ├─► [11] LLM reasons over data: "The PC is slow due to high CPU load by cpu_hog.exe."
        │
        ▼
   User Answer: "Your PC has a health score of 65/100 because CPU is at 90%. 'cpu_hog.exe' is using 85% CPU. I recommend closing it..."
```
