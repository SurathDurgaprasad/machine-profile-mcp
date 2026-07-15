# Peer-Machine Quickstart Guide - MachineProfile MCP v1.1.0

This guide explains how to validate the MachineProfile MCP package on your Windows machine.

---

## 1. Prerequisites
You only need:
* Windows OS (10 or 11)
* Python 3.10, 3.11, 3.12, or 3.13 installed (and added to your PATH environment variable)

You do **not** need administrative privileges, Git, or source repository compilers.

---

## 2. Testing Steps

### Step 1: Copy Files
Copy the following two files from the distributor to a temporary testing directory (e.g. `C:\mcp-test\`) on your machine:
* `machine_profile_mcp-1.1.0-py3-none-any.whl`
* `peer_validate.py`

### Step 2: Open PowerShell
Open Windows PowerShell (standard user privileges are sufficient) and navigate to the directory:
```powershell
cd C:\mcp-test\
```

### Step 3: Create & Activate Virtual Environment
Run the following commands to create and activate a clean python virtualenv:
```powershell
python -m venv test-env
.\test-env\Scripts\Activate.ps1
```

### Step 4: Install the Package Wheel
Install the package wheel using pip:
```powershell
pip install machine_profile_mcp-1.1.0-py3-none-any.whl
```

### Step 5: Run the Validation Script
Execute the peer validation runner to run diagnostic collections and verify package health:
```powershell
python peer_validate.py
```

### Step 6: Return Results
Upon completion, the script will output:
`Validation completed. Report written to: machine_profile_peer_validation.json`
`Overall Status: PASS`

Verify that the `machine_profile_peer_validation.json` file has been created in your directory.
Please return this file along with any feedback. Thank you!
