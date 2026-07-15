import shutil
import re
import logging
from typing import Optional

from ...models.ai import DockerStatusModel, DockerContainerInfo
from ..subprocess_helper import safe_run_command

logger = logging.getLogger("machine-profile.detectors.docker")


def normalize_image_repo(image: str) -> str:
    """
    Normalizes a Docker image reference, stripping tags, digests, and registry prefix
    to extract the canonical 'namespace/repository' or 'repository'.
    """
    # 1. Strip digest if present (e.g., @sha256:...)
    if "@" in image:
        image = image.split("@", 1)[0]

    # 2. Strip tag if present (e.g., :latest)
    if ":" in image:
        last_slash = image.rfind("/")
        last_colon = image.rfind(":")
        if last_colon > last_slash:
            image = image[:last_colon]

    # 3. Strip registry prefix if present
    parts = image.split("/")
    if len(parts) > 1:
        first = parts[0]
        # Check if first part looks like a registry host
        if "." in first or ":" in first or first == "localhost":
            image = "/".join(parts[1:])

    return image


class DockerDetector:
    """
    Offline detector for Docker daemon status and AI containers.
    """

    def __init__(self):
        pass

    def _get_docker_version(self) -> Optional[str]:
        try:
            rc, stdout, stderr = safe_run_command(["docker", "--version"], timeout=2.0)
            if rc == 0:
                # Parse version like "Docker version 24.0.7, build afdd53b"
                match = re.search(r"version\s+([0-9.]+)", stdout, re.IGNORECASE)
                if match:
                    return match.group(1)
        except Exception:
            pass
        return None

    def detect(self) -> DockerStatusModel:
        # Check CLI executable availability
        if not shutil.which("docker"):
            return DockerStatusModel(
                status="not_installed", version=None, ai_containers=[]
            )

        cli_version = self._get_docker_version()

        # Probe daemon status
        status = "unknown"
        try:
            rc, stdout, stderr = safe_run_command(["docker", "info"], timeout=2.0)
            if rc == 0:
                status = "daemon_running"
            else:
                stderr_lower = stderr.lower()
                # Check for permission/context errors on stderr only using narrow signatures
                if any(
                    x in stderr_lower
                    for x in [
                        "permission denied",
                        "access is denied",
                        "access denied",
                        "context deadline exceeded",
                        'context "default" is not found',
                    ]
                ):
                    status = "permission_or_context_error"
                # Check for daemon unavailable on stderr only using narrow signatures
                elif any(
                    x in stderr_lower
                    for x in [
                        "connection refused",
                        "actively refused",
                        "not running",
                        "is the docker daemon running",
                        "error during connect",
                        "cannot connect to the docker daemon",
                        "failed to connect to the docker api",
                    ]
                ):
                    status = "daemon_unavailable"
                else:
                    status = "unknown"
        except TimeoutError:
            status = "timeout"
        except FileNotFoundError:
            status = "not_installed"
        except Exception as e:
            logger.debug(f"Docker info probe raised unexpected exception: {e}")
            status = "unknown"

        ai_containers = []
        if status == "daemon_running":
            try:
                # Query running containers
                rc, stdout, stderr = safe_run_command(
                    ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
                    timeout=2.0,
                )
                if rc == 0 and stdout.strip():
                    for line in stdout.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split("\t")
                        if len(parts) >= 3:
                            name, image, state = parts[0], parts[1], parts[2]
                            if (
                                not name.strip()
                                or not image.strip()
                                or not state.strip()
                            ):
                                continue

                            # Classification heuristics using conservative evidence hierarchy
                            is_ai = False
                            normalized_repo = normalize_image_repo(image).lower()
                            name_lower = name.lower()

                            # Explicit Allowlist of repositories
                            ALLOWLIST = {
                                "ollama/ollama",
                                "vllm/vllm-openai",
                                "vllm-project/vllm",
                                "localai/localai",
                                "mudler/localai",
                                "ggerganov/llama.cpp",
                            }

                            if normalized_repo in ALLOWLIST:
                                is_ai = True
                            # Secondary evidence: exact container name matches
                            elif name_lower in {
                                "ollama",
                                "vllm",
                                "localai",
                                "llama-cpp",
                                "llama.cpp",
                            }:
                                is_ai = True

                            if is_ai:
                                ai_containers.append(
                                    DockerContainerInfo(
                                        name=name, image=image, status=state
                                    )
                                )
            except Exception as e:
                logger.warning(f"Failed to scan Docker containers: {e}")

        return DockerStatusModel(
            status=status, version=cli_version, ai_containers=ai_containers
        )
