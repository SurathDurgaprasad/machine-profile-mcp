import os
import json
import logging
import stat
from pathlib import Path

from ...models.ai import LocalModelItem, LocalModelInventoryModel
from ..utils import sanitize_user_path

logger = logging.getLogger("machine-profile.detectors.ollama")


def is_safe_directory(path: str, warnings_list: list) -> bool:
    """
    Returns True only if the directory is verified safe and not a junction/reparse point.
    Fails closed on any inspection exception.
    """
    try:
        # Check standard symlink
        if os.path.islink(path):
            san_path = sanitize_user_path(path)
            warnings_list.append(f"Skipped symlink directory: {san_path}")
            return False

        # Check Windows reparse point attribute (covers junctions)
        st = os.stat(path, follow_symlinks=False)
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            san_path = sanitize_user_path(path)
            warnings_list.append(
                f"Skipped reparse point/junction directory: {san_path}"
            )
            return False

        return True
    except Exception as e:
        san_path = sanitize_user_path(path)
        warnings_list.append(f"Junction check failed for {san_path}: {str(e)}")
        return False


class OllamaDetector:
    """
    Offline detector for Ollama models based on manifests stored on disk.
    """

    def __init__(self):
        self._inventory_complete = True
        self._truncated = False

    def _get_models_root(self) -> Path:
        override = os.environ.get("OLLAMA_MODELS")
        if override:
            p = Path(override)
            if p.exists() and p.is_dir():
                return p
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            return Path(user_profile) / ".ollama" / "models"
        return Path.home() / ".ollama" / "models"

    def _walk_manifests(
        self, current_dir: Path, depth: int, warnings: list, manifest_files: list
    ):
        try:
            for entry in os.scandir(current_dir):
                if entry.is_dir(follow_symlinks=False):
                    if depth < 3:
                        if is_safe_directory(entry.path, warnings):
                            self._walk_manifests(
                                Path(entry.path), depth + 1, warnings, manifest_files
                            )
                        else:
                            self._inventory_complete = False
                    else:
                        # We have a directory at depth 3 (recursion level 4). We cannot enter it.
                        self._truncated = True
                        self._inventory_complete = False
                elif entry.is_file(follow_symlinks=False):
                    if len(manifest_files) < 200:
                        manifest_files.append((entry.path, depth))
                    else:
                        # We have more files than the limit, so we are truncating
                        self._truncated = True
                        self._inventory_complete = False
        except Exception as e:
            san_dir = sanitize_user_path(str(current_dir))
            err_msg = sanitize_user_path(str(e))
            warnings.append(f"Directory listing failed for {san_dir}: {err_msg}")
            self._inventory_complete = False

    def detect(self) -> LocalModelInventoryModel:
        warnings = []
        models_list = []
        self._inventory_complete = True
        self._truncated = False

        models_root = self._get_models_root()
        manifests_root = models_root / "manifests"

        if not manifests_root.exists() or not manifests_root.is_dir():
            return LocalModelInventoryModel(
                models=[], inventory_complete=True, truncated=False, warnings=[]
            )

        manifest_files = []
        self._walk_manifests(manifests_root, 0, warnings, manifest_files)

        for path_str, depth in manifest_files:
            try:
                rel_path = Path(path_str).relative_to(manifests_root)
                parts = rel_path.parts

                if len(parts) >= 3:
                    tag = parts[-1]
                    model = parts[-2]
                    namespace = parts[-3]

                    if namespace == "library":
                        model_name = f"{model}:{tag}"
                    else:
                        model_name = f"{namespace}/{model}:{tag}"
                else:
                    model_name = f"{rel_path.name}:latest"

                with open(path_str, "r", encoding="utf-8") as f:
                    data = json.load(f)

                layers = data.get("layers", [])
                size_bytes = sum(layer.get("size", 0) for layer in layers)

                sanitized_path = sanitize_user_path(path_str)

                models_list.append(
                    LocalModelItem(
                        name=model_name,
                        provider="ollama",
                        format="ollama-manifest",
                        path=sanitized_path,
                        size_bytes=size_bytes,
                        quantization=None,
                        detection_source="filesystem-scan",
                        metadata_source="manifest-json",
                        confidence="authoritative",
                    )
                )
            except Exception as e:
                san_path = sanitize_user_path(path_str)
                err_msg = sanitize_user_path(str(e))
                warnings.append(f"Failed to parse manifest {san_path}: {err_msg}")
                self._inventory_complete = False

        return LocalModelInventoryModel(
            models=models_list,
            inventory_complete=self._inventory_complete,
            truncated=self._truncated,
            warnings=warnings,
        )
