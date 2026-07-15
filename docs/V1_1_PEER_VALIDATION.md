# MachineProfile MCP - v1.1.0 Peer-Machine Validation Checklist

This checklist guides verification of the v1.1.0 release capabilities on a physical peer machine running Windows.

---

## A. Machine Information
Record the peer machine details:
* **Windows Edition/Version/Build**: ____________________________________
* **CPU Vendor/Model**: ____________________________________
* **GPU Vendor/Model**: ____________________________________
* **Python Version**: ____________________________________

---

## B. Installation & Setup
1. Create a clean virtual environment:
   ```powershell
   python -m venv test-env
   .\test-env\Scripts\Activate.ps1
   ```
2. Install the built wheel:
   ```powershell
   pip install machine_profile_mcp-1.1.0-py3-none-any.whl
   ```
3. Verify the console command exists in PATH:
   ```powershell
   Get-Command machine-profile
   ```

---

## C. MCP Interface & Handshake
1. Run the E2E protocol validation test locally:
   ```powershell
   # Run the E2E test file from the repository
   python windows_diagnostics_mcp/tests/e2e_mcp_test.py
   ```
2. Verify all handshakes and outputs:
   - [ ] Initialize handshake succeeds
   - [ ] `tools/list` returns all 8 expected tools
   - [ ] `resources/list` returns all 4 expected resource URIs
   - [ ] `prompts/list` returns `analyze_machine`
   - [ ] `system_summary` can be called successfully
   - [ ] `ai_environment` can be called successfully
   - [ ] `windows://system` resource can be read successfully
   - [ ] `windows://ai` resource can be read successfully

---

## D. Hardware Specification Accuracy
1. **CPU Capability Verification**:
   - Check `system_summary` tool output:
     - [ ] `cpu` field is present and not null.
     - [ ] CPU model name is accurate (e.g. Intel Core i5 / AMD Ryzen).
     - [ ] CPU vendor, physical cores, logical cores, and max frequency match actual hardware.
2. **GPU Capability Verification**:
   - Check `ai_environment` tool output:
     - [ ] `gpu` array contains all graphic cards.
     - [ ] For integrated GPUs (Intel/AMD), `vram_mb` and `dedicated_vram_bytes` must be `null` unless authoritative SMI evidence exists.
     - [ ] For discrete NVIDIA GPUs, VRAM is populated only when `nvidia-smi` is available.

---

## E. Optional AI Runtimes Discovery
1. **Ollama Discovery**:
   - Check when stopped:
     - [ ] `ollama_installed` is `True` (if CLI exists), `ollama_running` is `False`.
     - [ ] `local_models.models` lists offline cached models from the manifests directory.
   - Check when running:
     - [ ] `ollama_running` is `True`.
2. **LM Studio Discovery**:
   - Verify GGUF models are discovered:
     - [ ] Default cache directory (`.cache\lm-studio\models`) is searched.
     - [ ] Custom settings directories (if configured in `settings.json`) are searched.
     - [ ] Quantization is inferred from filenames (e.g., `Q4_K_M`).
3. **Docker Discovery**:
   - Check when daemon is stopped:
     - [ ] `docker.status` is resolved to `daemon_unavailable`.
   - Check when daemon is running:
     - [ ] `docker.status` is resolved to `daemon_running`.
     - [ ] `docker.ai_containers` lists only supported runtimes (e.g. `ollama`, `vllm`, `localai`) and strips registry prefixes/digests.

---

## F. Privacy & Anonymization
1. Enable anonymization:
   ```powershell
   $env:MACHINE_PROFILE_ANONYMIZE="true"
   ```
2. Execute E2E checks:
   - [ ] Active user directory names under `C:\Users\` are replaced with `LocalUser` in paths.
   - [ ] General username text in logs (not under Users directory) remains unmodified.

---

## G. Validation Result
* **Overall Status**: [ ] PASS | [ ] PARTIAL | [ ] FAIL
* **Notes**:
