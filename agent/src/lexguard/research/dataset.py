"""Immutable research-run contracts and compact artifact hashing."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from lexguard.domain.hashing import canonical_sha256
from lexguard.domain.models import ImmutableModel

RESEARCH_START = date(2024, 3, 1)
RESEARCH_END = date(2026, 8, 21)
OOS_START = date(2026, 1, 2)
OOS_END = RESEARCH_END
DEFAULT_CODE_SCOPE = (
    "agent/pyproject.toml",
    "agent/src/lexguard/domain/hashing.py",
    "agent/src/lexguard/domain/models.py",
    "agent/src/lexguard/research",
)


class DatasetManifest(ImmutableModel):
    run_id: str
    start: date
    end: date
    oos_start: date
    oos_end: date
    symbols: tuple[str, ...]
    timeframe: str = "5Min"
    feed: str = "sip"
    adjustment: str = "raw"
    timezone: str = "America/New_York"
    provider: str = "alpaca_cli"
    commands: tuple[str, ...] = ()
    cli_version: str = "unknown"
    contract_ids: tuple[str, ...] = ()
    raw_hashes: dict[str, str] = {}
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_tree_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_state: Literal["COMMITTED", "PENDING_COMMIT"]
    code_scope: tuple[str, ...]
    generated_at: datetime
    oos_unsealed: bool


class DevelopmentFreeze(ImmutableModel):
    freeze_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_run_id: str
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_tree_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_state: Literal["COMMITTED", "PENDING_COMMIT"]
    code_scope: tuple[str, ...]
    parameters_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_at: datetime


class OOSRegistration(ImmutableModel):
    freeze_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_run_id: str
    parameters_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    registered_at: datetime


def build_manifest(
    *,
    run_id: str,
    start: date,
    end: date,
    symbols: tuple[str, ...],
    unseal_oos: bool,
    generated_at: datetime | None = None,
    commands: tuple[str, ...] = (),
    cli_version: str = "unknown",
    contract_ids: tuple[str, ...] = (),
    raw_hashes: dict[str, str] | None = None,
    code_commit: str | None = None,
    code_tree_hash: str | None = None,
    code_state: Literal["COMMITTED", "PENDING_COMMIT"] | None = None,
    code_scope: tuple[str, ...] = DEFAULT_CODE_SCOPE,
    allow_sealed_oos_collection: bool = False,
) -> DatasetManifest:
    if not run_id or not symbols:
        raise ValueError("research manifest requires run_id and symbols")
    if start < RESEARCH_START or end > RESEARCH_END or start > end:
        raise ValueError("research range must stay within the frozen dataset interval")
    if end >= OOS_START and not unseal_oos and not allow_sealed_oos_collection:
        raise ValueError("out-of-sample data is sealed; pass unseal_oos acknowledgement")
    normalized_symbols = tuple(
        sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    )
    if len(normalized_symbols) != len(symbols):
        raise ValueError("manifest symbols must be non-empty and unique")
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("manifest generated_at must be timezone-aware")
    repository_root = Path(__file__).resolve().parents[4]
    return DatasetManifest(
        run_id=run_id,
        start=start,
        end=end,
        oos_start=OOS_START,
        oos_end=OOS_END,
        symbols=normalized_symbols,
        generated_at=timestamp,
        oos_unsealed=unseal_oos and end >= OOS_START,
        commands=commands,
        cli_version=cli_version,
        contract_ids=contract_ids,
        raw_hashes=raw_hashes or {},
        code_commit=code_commit or _current_code_commit(repository_root),
        code_tree_hash=code_tree_hash
        or compute_code_tree_hash(repository_root, code_scope),
        code_state=code_state or _current_code_state(repository_root, code_scope),
        code_scope=code_scope,
    )


def compute_code_tree_hash(repository_root: Path, code_scope: tuple[str, ...]) -> str:
    """Hash the exact contents and relative paths in the research code scope."""

    files: list[Path] = []
    for relative_name in code_scope:
        scoped_path = repository_root / Path(relative_name)
        if not scoped_path.exists():
            raise ValueError(f"research code scope is missing: {relative_name}")
        if scoped_path.is_file():
            files.append(scoped_path)
            continue
        files.extend(
            path
            for path in scoped_path.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
    digest = hashlib.sha256()
    for path in sorted(set(files), key=lambda item: item.relative_to(repository_root).as_posix()):
        relative_name = path.relative_to(repository_root).as_posix()
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def verify_code_provenance(
    manifest: DatasetManifest, *, repository_root: Path | None = None
) -> tuple[str, ...]:
    """Verify that the checked-out research code still matches a manifest."""

    root = repository_root or Path(__file__).resolve().parents[4]
    actual_hash = compute_code_tree_hash(root, manifest.code_scope)
    return () if actual_hash == manifest.code_tree_hash else ("CODE_TREE_HASH_MISMATCH",)


def write_research_contract(
    root: Path,
    manifest: DatasetManifest,
    parameters: dict[str, Any],
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw").mkdir(exist_ok=True)
    (root / "normalized").mkdir(exist_ok=True)
    (root / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    _write_json(root / "parameters.json", parameters)
    _write_json(
        root / "strategy_spec.json",
        {
            "signal_timing": "completed five-minute bar",
            "fill_timing": "next five-minute bar open",
            "atomic_legs": 4,
            "symbols": manifest.symbols,
        },
    )
    _write_json(
        root / "config.json",
        {
            "start": manifest.start,
            "end": manifest.end,
            "oos_start": manifest.oos_start,
            "oos_end": manifest.oos_end,
            "timeframe": manifest.timeframe,
            "feed": manifest.feed,
            "adjustment": manifest.adjustment,
            "timezone": manifest.timezone,
            "oos_unsealed": manifest.oos_unsealed,
        },
    )
    _write_json(root / "warnings.json", {"warnings": []})
    _write_json(
        root / "summary.json",
        {
            "strategy_name": "Lexguard",
            "start": manifest.start,
            "end": manifest.end,
            "symbols": manifest.symbols,
            "timeframe": manifest.timeframe,
            "metrics": {},
            "benchmarks": {},
            "warnings": ["contract_only_run_no_results"],
        },
    )
    _write_json(
        root / "fee_source.json",
        {
            "url": "https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf",
            "title": "Alpaca Securities LLC Brokerage Fee Schedule",
            "revision_date": "2026-07-20",
            "extracted_at": manifest.generated_at,
            "rates": {
                "sec_sell_rate_on_trade_value": "0.0000206",
                "taf_sell_per_contract": "0.00329",
                "cat_per_executed_equivalent_share": "0.000003",
                "orf_per_contract": "0.015",
                "occ_per_contract": "0.025",
            },
            "aggregation": (
                "Simulator records unrounded execution-level accruals; the source says each fee "
                "type is aggregated daily per account and then rounded up to the nearest cent."
            ),
            "excluded_categories": ["index_option_exchange_fees_for_non_index_underlyings"],
        },
    )
    (root / "notes.md").write_text(
        "# Research contract\n\n"
        "This folder records a reproducible research contract. It contains no fabricated "
        "performance results. Signals use completed bars and the custom simulator fills every "
        "leg at the next five-minute bar open.\n\n"
        "This is hypothetical historical research, not investment advice. Paper trading is "
        "simulated and may differ from live trading.\n",
        encoding="utf-8",
    )
    raw_files = tuple(sorted(path for path in (root / "raw").rglob("*") if path.is_file()))
    _write_json(
        root / "data_fingerprint.json",
        {
            "provider": manifest.provider,
            "access_method": "alpaca_cli",
            "raw_file_count": len(raw_files),
            "raw_hashes": {path.relative_to(root).as_posix(): _sha256(path) for path in raw_files},
            "feed": manifest.feed,
            "adjustment": manifest.adjustment,
            "timeframe": manifest.timeframe,
        },
    )
    refresh_artifact_hashes(root, manifest)


def refresh_artifact_hashes(root: Path, manifest: DatasetManifest | None = None) -> None:
    """Hash every artifact recursively after its producer has finished writing."""

    resolved_manifest = manifest
    if resolved_manifest is None:
        resolved_manifest = DatasetManifest.model_validate_json(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
    hashes = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in _integrity_files(root)
    }
    (root / "hashes.json").write_text(
        json.dumps(
            {"manifest_hash": canonical_sha256(resolved_manifest), "files": hashes},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def verify_artifacts(root: Path) -> tuple[str, ...]:
    hashes_path = root / "hashes.json"
    if not hashes_path.exists():
        return ("MISSING_HASHES",)
    payload = json.loads(hashes_path.read_text(encoding="utf-8"))
    reasons: list[str] = []
    expected_files = payload.get("files", {})
    if not isinstance(expected_files, dict):
        return ("INVALID_HASHES",)
    actual_names = {path.relative_to(root).as_posix() for path in _integrity_files(root)}
    expected_names = set(expected_files)
    reasons.extend(f"UNEXPECTED:{name}" for name in actual_names - expected_names)
    for name, expected in expected_files.items():
        path = root / Path(name)
        if not path.exists():
            reasons.append(f"MISSING:{name}")
        elif _sha256(path) != expected:
            reasons.append(f"HASH_MISMATCH:{name}")
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if canonical_sha256(manifest) != payload.get("manifest_hash"):
            reasons.append("MANIFEST_HASH_MISMATCH")
    return tuple(sorted(reasons))


def verify_dataset(root: Path) -> tuple[str, ...]:
    """Verify the manifest's exact recursive raw-data fingerprint."""

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return ("MISSING_MANIFEST",)
    manifest = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.raw_hashes
    raw_root = root / "raw"
    actual_paths = tuple(sorted(path for path in raw_root.rglob("*") if path.is_file()))
    actual_names = {path.relative_to(root).as_posix() for path in actual_paths}
    expected_names = set(expected)
    reasons = [f"UNEXPECTED:{name}" for name in actual_names - expected_names]
    for name, expected_hash in expected.items():
        path = root / Path(name)
        if not path.exists():
            reasons.append(f"MISSING:{name}")
        elif _sha256(path) != expected_hash:
            reasons.append(f"HASH_MISMATCH:{name}")
    return tuple(sorted(reasons))


def freeze_development_run(
    output: Path, *, development_run_id: str = "development"
) -> DevelopmentFreeze:
    """Create one immutable freeze tied to parameters, artifacts, and code."""

    development = output / development_run_id
    failures = verify_artifacts(development)
    if failures:
        raise ValueError(f"development artifacts failed verification: {failures}")
    manifest = DatasetManifest.model_validate_json(
        (development / "manifest.json").read_text(encoding="utf-8")
    )
    parameters_hash = _sha256(development / "parameters.json")
    artifact_hash = _sha256(development / "hashes.json")
    frozen_at = datetime.now(UTC)
    freeze_payload = {
        "development_run_id": development_run_id,
        "code_commit": manifest.code_commit,
        "code_tree_hash": manifest.code_tree_hash,
        "code_state": manifest.code_state,
        "code_scope": manifest.code_scope,
        "parameters_hash": parameters_hash,
        "artifact_hash": artifact_hash,
    }
    freeze = DevelopmentFreeze(
        freeze_id=hashlib.sha256(
            json.dumps(freeze_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        frozen_at=frozen_at,
        development_run_id=development_run_id,
        code_commit=manifest.code_commit,
        code_tree_hash=manifest.code_tree_hash,
        code_state=manifest.code_state,
        code_scope=manifest.code_scope,
        parameters_hash=parameters_hash,
        artifact_hash=artifact_hash,
    )
    output.mkdir(parents=True, exist_ok=True)
    freeze_path = output / "development-freeze.json"
    try:
        with freeze_path.open("x", encoding="utf-8") as handle:
            handle.write(freeze.model_dump_json(indent=2) + "\n")
    except FileExistsError as exc:
        raise FileExistsError("development freeze is immutable and already exists") from exc
    return freeze


def register_oos_evaluation(
    output: Path, *, evaluation_run_id: str
) -> OOSRegistration:
    """Consume a frozen development artifact for OOS exactly once."""

    freeze_path = output / "development-freeze.json"
    if not freeze_path.exists():
        raise ValueError("out-of-sample evaluation requires a development freeze")
    freeze = DevelopmentFreeze.model_validate_json(freeze_path.read_text(encoding="utf-8"))
    development = output / freeze.development_run_id
    if _sha256(development / "parameters.json") != freeze.parameters_hash:
        raise ValueError("frozen development parameters changed")
    if _sha256(development / "hashes.json") != freeze.artifact_hash:
        raise ValueError("frozen development artifact changed")
    registry = output / ".oos-registry"
    registry.mkdir(parents=True, exist_ok=True)
    registration = OOSRegistration(
        freeze_id=freeze.freeze_id,
        evaluation_run_id=evaluation_run_id,
        parameters_hash=freeze.parameters_hash,
        development_artifact_hash=freeze.artifact_hash,
        registered_at=datetime.now(UTC),
    )
    registration_path = registry / f"{freeze.freeze_id}.json"
    try:
        with registration_path.open("x", encoding="utf-8") as handle:
            handle.write(registration.model_dump_json(indent=2) + "\n")
    except FileExistsError as exc:
        raise FileExistsError("frozen out-of-sample evaluation has already been consumed") from exc
    return registration


def _integrity_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name != "hashes.json"
        and path.relative_to(root).parts[0] != "raw"
    )


def _current_code_commit(repository_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("research manifest requires a resolvable Git commit") from exc
    return completed.stdout.strip().lower()


def _current_code_state(
    repository_root: Path, code_scope: tuple[str, ...]
) -> Literal["COMMITTED", "PENDING_COMMIT"]:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                *code_scope,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("research manifest requires verifiable Git worktree state") from exc
    return "PENDING_COMMIT" if completed.stdout.strip() else "COMMITTED"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8"
    )
