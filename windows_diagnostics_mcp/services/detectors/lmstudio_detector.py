import os
import json
import logging
import re
import stat
from pathlib import Path
from typing import Optional, List

from ...models.ai import LocalModelItem, LocalModelInventoryModel
from ..utils import sanitize_user_path

logger = logging.getLogger("machine-profile.detectors.lmstudio")


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
        err_msg = sanitize_user_path(str(e))
        warnings_list.append(f"Junction check failed for {san_path}: {err_msg}")
        return False


class LMStudioDetector:
    """
    Offline detector for LM Studio models based on GGUF files stored on disk.
    """

    def __init__(self):
        self._inventory_complete = True
        self._truncated = False

    def _get_custom_paths(self) -> List[Path]:
        custom_paths = []
        candidates = []

        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "lm-studio" / "settings.json")

        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            candidates.append(Path(userprofile) / ".lmstudio" / "settings.json")

        for path in candidates:
            if path.exists() and path.is_file():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for key in [
                        "modelDownloadsDir",
                        "modelDownloadDir",
                        "localModelsDir",
                    ]:
                        val = data.get(key)
                        if val and isinstance(val, str):
                            p = Path(val)
                            if p.exists() and p.is_dir():
                                custom_paths.append(p.resolve())
                except Exception:
                    # Ignore parsing failures for candidate settings paths
                    pass
        return custom_paths

    def _parse_quantization(self, filename: str) -> Optional[str]:
        # Search for exact standard GGUF quantization patterns case-insensitively
        match = re.search(
            r"\b(Q[2-8]_[0-9KMSLXNPAB_]+|IQ[1-4]_[0-9KMSLXNPAB_]+|FP16|BF16|F16|F32)\b",
            filename,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).upper()
        return None

    def _walk_models(
        self, current_dir: Path, depth: int, warnings: list, manifest_files: list
    ):
        try:
            for entry in os.scandir(current_dir):
                if entry.is_dir(follow_symlinks=False):
                    if depth < 3:
                        if is_safe_directory(entry.path, warnings):
                            self._walk_models(
                                Path(entry.path),
                                depth + 1,
                                warnings,
                                manifest_files,
                            )
                        else:
                            self._inventory_complete = False
                    else:
                        # Directory recursion too deep
                        self._truncated = True
                        self._inventory_complete = False
                elif entry.is_file(follow_symlinks=False):
                    if entry.name.lower().endswith(".gguf"):
                        if len(manifest_files) < 200:
                            manifest_files.append((entry.path, depth))
                        else:
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

        raw_roots = []

        # Default roots
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            # Verified default cache path
            default_root = Path(userprofile) / ".cache" / "lm-studio" / "models"
            if default_root.exists() and default_root.is_dir():
                raw_roots.append(default_root)
            # Candidate/best-effort cache path (new v0.3+ beta configurations)
            hub_root = Path(userprofile) / ".lmstudio" / "hub"
            if hub_root.exists() and hub_root.is_dir():
                raw_roots.append(hub_root)

        # Custom roots
        custom_roots = self._get_custom_paths()
        raw_roots.extend(custom_roots)

        # Normalization and Deduplication of Roots
        roots = []
        seen_roots = set()
        for r in raw_roots:
            try:
                resolved = r.resolve()
                key = str(resolved).lower()
                if key not in seen_roots:
                    seen_roots.add(key)
                    roots.append(resolved)
            except Exception:
                # Safe fallback to normalized absolute path on resolution failure
                try:
                    abs_p = r.absolute()
                    key = str(abs_p).lower()
                    if key not in seen_roots:
                        seen_roots.add(key)
                        roots.append(abs_p)
                except Exception:
                    pass

        if not roots:
            return LocalModelInventoryModel(
                models=[], inventory_complete=True, truncated=False, warnings=[]
            )

        manifest_files = []
        for root in roots:
            self._walk_models(root, 0, warnings, manifest_files)
            if self._truncated:
                break

        # Deduplicate model files based on resolved canonical paths
        deduplicated_files = []
        seen_model_paths = set()
        for path_str, depth in manifest_files:
            try:
                resolved = Path(path_str).resolve()
                key = str(resolved).lower()
                if key not in seen_model_paths:
                    seen_model_paths.add(key)
                    deduplicated_files.append((path_str, depth))
            except Exception:
                if path_str.lower() not in seen_model_paths:
                    seen_model_paths.add(path_str.lower())
                    deduplicated_files.append((path_str, depth))

        for path_str, depth in deduplicated_files:
            try:
                path_obj = Path(path_str)
                matching_root = None
                for root in roots:
                    try:
                        path_obj.relative_to(root)
                        matching_root = root
                        break
                    except ValueError:
                        continue

                if matching_root:
                    rel_path = path_obj.relative_to(matching_root)
                    parts = rel_path.parts
                    if len(parts) >= 3:
                        model_name = f"{parts[-3]}/{parts[-2]}"
                    elif len(parts) == 2:
                        model_name = parts[-2]
                    else:
                        model_name = rel_path.stem
                else:
                    model_name = path_obj.stem

                quant = self._parse_quantization(path_obj.name)
                sanitized_path = sanitize_user_path(path_str)

                try:
                    size_bytes = os.path.getsize(path_str)
                except Exception as e:
                    size_bytes = None
                    err_msg = sanitize_user_path(str(e))
                    san_path = sanitize_user_path(path_str)
                    warnings.append(f"Failed to get size for {san_path}: {err_msg}")
                    self._inventory_complete = False

                models_list.append(
                    LocalModelItem(
                        name=model_name,
                        provider="lm-studio",
                        format="gguf",
                        path=sanitized_path,
                        size_bytes=size_bytes,
                        quantization=quant,
                        detection_source="filesystem-scan",
                        metadata_source="filename-parse",
                        confidence="inferred",
                    )
                )
            except Exception as e:
                san_path = sanitize_user_path(path_str)
                err_msg = sanitize_user_path(str(e))
                warnings.append(f"Failed to parse model {san_path}: {err_msg}")
                self._inventory_complete = False

        return LocalModelInventoryModel(
            models=models_list,
            inventory_complete=self._inventory_complete,
            truncated=self._truncated,
            warnings=warnings,
        )
