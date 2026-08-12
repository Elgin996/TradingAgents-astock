"""Immutable, content-addressed market-data snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from uuid import uuid4
import re
from pathlib import Path
from typing import Any

from .models import MarketDataResult


class SnapshotError(RuntimeError):
    pass


class SnapshotNotFound(SnapshotError):
    pass


class SnapshotCorrupt(SnapshotError):
    pass


_SENSITIVE_KEY = re.compile(r"(?i)(api.?key|token|cookie|authorization|secret|password|signature)")


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("<redacted>" if _SENSITIVE_KEY.search(str(key)) else _sanitize(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in value]
    if isinstance(value, bytes):
        return {"encoding": "bytes", "sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    if isinstance(value, str):
        value = re.sub(r"(?i)(api.?key|token|cookie|authorization|signature)=([^&\s]+)", r"\1=<redacted>", value)
        value = re.sub(r"https?://[^\s]+", "<url-redacted>", value)
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(_sanitize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class SnapshotStore:
    """Store and verify complete normalized-data snapshots.

    A snapshot directory is only made visible after all files and the manifest
    have been written.  Existing directories are never overwritten.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser() / "snapshots"

    def snapshot_path(self, snapshot_id: str) -> Path:
        digest = snapshot_id.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SnapshotError("invalid snapshot id")
        return self.root / digest[:2] / digest

    def exists(self, snapshot_id: str) -> bool:
        target = self.snapshot_path(snapshot_id)
        if not target.is_dir() or not (target / "manifest.json").is_file():
            return False
        try:
            self._verify_manifest(target, snapshot_id)
        except SnapshotError:
            return False
        return True

    def find_by_request(self, request: Any) -> MarketDataResult | None:
        """Find an exact request snapshot for ``prefer_cache`` mode.

        The index is deliberately derived from immutable manifests.  A missing
        or malformed directory is ignored here and will still fail closed when
        explicitly requested by snapshot ID.
        """
        request_payload = _canonical(request.model_dump(mode="json"))
        if not self.root.is_dir():
            return None
        for manifest_path in self.root.glob("*/*/manifest.json"):
            try:
                directory = manifest_path.parent
                stored = json.loads((directory / "request.json").read_text(encoding="utf-8"))
                if _canonical(stored) == request_payload:
                    return self.load(json.loads(manifest_path.read_text(encoding="utf-8")).get("snapshot_id", ""))
            except Exception:
                continue
        return None

    def save(
        self,
        result: MarketDataResult,
        *,
        raw_responses: dict[str, Any] | None = None,
        contract_version: str = "market-data-v1",
        normalizer_version: str = "normalizer-v1",
        quality_rule_version: str = "quality-v1",
    ) -> str:
        payload = {
            "request": result.request.model_dump(mode="json"),
            "bars": [bar.model_dump(mode="json") for bar in result.bars],
            "attempts": [attempt.model_dump(mode="json") for attempt in result.attempts],
            "quality": result.quality.model_dump(mode="json"),
            "contract_version": contract_version,
            "normalizer_version": normalizer_version,
            "quality_rule_version": quality_rule_version,
        }
        digest = _sha256(_canonical(payload))
        snapshot_id = f"sha256:{digest}"
        target = self.snapshot_path(snapshot_id)
        if target.exists():
            if self.exists(snapshot_id):
                return snapshot_id
            raise SnapshotCorrupt("snapshot directory exists but is incomplete or corrupt")
        target.parent.mkdir(parents=True, exist_ok=True)
        # A unique sibling avoids collisions between concurrent identical
        # writers and makes a staging directory left by a crashed process
        # harmless to later saves.
        temp = target.parent / f".{digest}.{uuid4().hex}.tmp"
        temp.mkdir(parents=False)
        try:
            files: dict[str, bytes] = {
                "request.json": _canonical(result.request.model_dump(mode="json")),
                "attempts.json": _canonical([a.model_dump(mode="json") for a in result.attempts]),
                "normalized.json": _canonical([b.model_dump(mode="json") for b in result.bars]),
                "quality.json": _canonical(result.quality.model_dump(mode="json")),
            }
            for name, content in files.items():
                (temp / name).write_bytes(content)
            raw = raw_responses if raw_responses is not None else result.raw_responses
            if raw:
                raw_dir = temp / "raw"
                raw_dir.mkdir()
                for source, response in raw.items():
                    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(source))[:80] or "source"
                    (raw_dir / f"{safe_name}.json").write_bytes(_canonical(response))
            manifest = {
                "snapshot_id": snapshot_id,
                "contract_version": contract_version,
                "normalizer_version": normalizer_version,
                "quality_rule_version": quality_rule_version,
                "files": {},
            }
            for path in sorted(temp.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(temp).as_posix()
                    content = path.read_bytes()
                    manifest["files"][relative] = {"sha256": _sha256(content), "size": len(content)}
            (temp / "manifest.json").write_bytes(_canonical(manifest))
            # Manifest itself is deliberately not listed in its own file map.
            try:
                os.replace(str(temp), str(target))
            except OSError:
                # Another writer may have atomically published the identical
                # content after our initial existence check.
                if self.exists(snapshot_id):
                    shutil.rmtree(temp, ignore_errors=True)
                    return snapshot_id
                raise
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
        return snapshot_id

    def load(self, snapshot_id: str) -> MarketDataResult:
        target = self.snapshot_path(snapshot_id)
        if not target.is_dir():
            raise SnapshotNotFound(snapshot_id)
        try:
            manifest = self._verify_manifest(target, snapshot_id)
            request = json.loads((target / "request.json").read_text(encoding="utf-8"))
            attempts = json.loads((target / "attempts.json").read_text(encoding="utf-8"))
            bars = json.loads((target / "normalized.json").read_text(encoding="utf-8"))
            quality = json.loads((target / "quality.json").read_text(encoding="utf-8"))
            return MarketDataResult(
                request=request,
                bars=bars,
                attempts=attempts,
                quality=quality,
                snapshot_id=snapshot_id,
            )
        except SnapshotError:
            raise
        except Exception as exc:
            raise SnapshotCorrupt(f"unable to load snapshot: {type(exc).__name__}") from exc

    @staticmethod
    def _verify_manifest(target: Path, snapshot_id: str) -> dict:
        try:
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        except Exception as exc:
            raise SnapshotCorrupt("manifest is unreadable") from exc
        if manifest.get("snapshot_id") != snapshot_id:
            raise SnapshotCorrupt("snapshot id does not match manifest")
        required = {"request.json", "attempts.json", "normalized.json", "quality.json"}
        if not required.issubset(manifest.get("files", {})):
            raise SnapshotCorrupt("snapshot manifest is incomplete")
        for relative, metadata in manifest.get("files", {}).items():
            path = target / relative
            if not path.is_file() or _sha256(path.read_bytes()) != metadata.get("sha256"):
                raise SnapshotCorrupt(f"file hash mismatch: {relative}")
        return manifest

    read = load
