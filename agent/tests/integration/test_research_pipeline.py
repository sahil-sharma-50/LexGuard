"""Research manifest and artifact reproducibility tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lexguard.research import cli, dataset
from lexguard.research.dataset import (
    build_manifest,
    verify_artifacts,
    write_research_contract,
)

FROZEN_STRATEGY_PARAMETERS = {
    "version": "point_in_time_condor_v1",
    "candidate_selection": "only observations at or before signal timestamp",
    "structures": ["iron_condor", "reverse_iron_condor"],
    "dte": [1, 3],
    "signal_timing": "completed five-minute bar",
    "exit_timing": "next completed five-minute bar",
    "option_fee_schedule_revision": "2026-07-20",
}


def _write_frozen_evaluation_fixture(
    output: Path,
    *,
    symbols: tuple[str, ...] = ("SPY",),
    strategy_parameters: dict[str, object] | None = None,
    code_tree_hash: str | None = None,
) -> dataset.DevelopmentFreeze:
    source = output / "dataset"
    raw_file = source / "raw" / "bars.json"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text('{"bars": {}}\n', encoding="utf-8")
    source_manifest = build_manifest(
        run_id="dataset",
        start=date(2024, 3, 1),
        end=date(2026, 8, 21),
        symbols=symbols,
        unseal_oos=True,
    )
    write_research_contract(source, source_manifest, {"symbols": symbols})
    source_hashes = {
        path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source.rglob("*"))
        if path.is_file()
    }

    development = output / "development"
    development_manifest = build_manifest(
        run_id="development",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=symbols,
        unseal_oos=False,
        code_tree_hash=code_tree_hash,
        code_state="PENDING_COMMIT" if code_tree_hash is not None else None,
    )
    write_research_contract(
        development,
        development_manifest,
        {
            "symbols": symbols,
            "phase": "DEVELOPMENT",
            "dataset_run_id": "dataset",
            "strategy_parameters": strategy_parameters or FROZEN_STRATEGY_PARAMETERS,
            "oos_registration": None,
        },
    )
    (development / "data_fingerprint.json").write_text(
        json.dumps({"source_run": "dataset", "raw_hashes": source_hashes}) + "\n",
        encoding="utf-8",
    )
    dataset.refresh_artifact_hashes(development, development_manifest)
    return dataset.freeze_development_run(output)


def test_oos_is_sealed_until_explicit_acknowledgement() -> None:
    with pytest.raises(ValueError, match="out-of-sample"):
        build_manifest(
            run_id="fixture",
            start=date(2024, 3, 1),
            end=date(2026, 8, 21),
            symbols=("SPY", "QQQ", "IWM"),
            unseal_oos=False,
        )

    manifest = build_manifest(
        run_id="fixture",
        start=date(2024, 3, 1),
        end=date(2026, 8, 21),
        symbols=("SPY", "QQQ", "IWM"),
        unseal_oos=True,
    )
    assert manifest.oos_unsealed is True
    assert manifest.oos_start == date(2026, 1, 2)


def test_contract_writes_hashable_compact_artifacts(tmp_path: Path) -> None:
    manifest = build_manifest(
        run_id="fixture",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
    )

    root = tmp_path / "research-contract-fixture"
    root.mkdir(parents=True, exist_ok=True)
    write_research_contract(root, manifest, {"strategy": "quant-only"})

    fee_source = json.loads((root / "fee_source.json").read_text(encoding="utf-8"))
    assert fee_source["revision_date"] == "2026-07-20"
    assert fee_source["rates"]["orf_per_contract"] == "0.015"
    assert fee_source["rates"]["occ_per_contract"] == "0.025"
    assert verify_artifacts(root) == ()


def test_manifest_records_the_exact_code_commit() -> None:
    manifest = build_manifest(
        run_id="fixture",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
        code_commit="6a913d9f90389ef62b5c39684d34402d07773a87",
    )

    assert manifest.code_commit == "6a913d9f90389ef62b5c39684d34402d07773a87"


def test_manifest_distinguishes_the_base_commit_from_the_pending_code_tree() -> None:
    """Dropping the tree hash/state would again mislabel dirty code as Git HEAD."""

    manifest = build_manifest(
        run_id="fixture",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
        code_commit="6a913d9f90389ef62b5c39684d34402d07773a87",
        code_tree_hash="a" * 64,
        code_state="PENDING_COMMIT",
        code_scope=("agent/src/lexguard", "agent/pyproject.toml"),
    )

    assert manifest.code_commit == "6a913d9f90389ef62b5c39684d34402d07773a87"
    assert manifest.code_tree_hash == "a" * 64
    assert manifest.code_state == "PENDING_COMMIT"
    assert manifest.code_scope == (
        "agent/src/lexguard",
        "agent/pyproject.toml",
    )


def test_code_tree_fingerprint_is_verifiable_after_the_worktree_changes(tmp_path: Path) -> None:
    code_root = tmp_path / "code-tree"
    code_file = code_root / "research" / "strategy.py"
    code_file.parent.mkdir(parents=True)
    code_file.write_text("RULE = 1\n", encoding="utf-8")

    tree_hash = dataset.compute_code_tree_hash(code_root, ("research",))
    manifest = build_manifest(
        run_id="fixture",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
        code_commit="6a913d9f90389ef62b5c39684d34402d07773a87",
        code_tree_hash=tree_hash,
        code_state="PENDING_COMMIT",
        code_scope=("research",),
    )

    assert dataset.verify_code_provenance(manifest, repository_root=code_root) == ()
    code_file.write_text("RULE = 2\n", encoding="utf-8")
    assert dataset.verify_code_provenance(manifest, repository_root=code_root) == (
        "CODE_TREE_HASH_MISMATCH",
    )


def test_artifact_verification_is_exact_recursive_but_excludes_raw_data(tmp_path: Path) -> None:
    manifest = build_manifest(
        run_id="fixture",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
    )
    root = tmp_path / "integrity-exact"
    write_research_contract(root, manifest, {"strategy": "quant-only"})
    (root / "normalized" / "unexpected.json").write_text("{}\n", encoding="utf-8")
    (root / "raw" / "untracked.json").write_text("{}\n", encoding="utf-8")

    assert verify_artifacts(root) == ("UNEXPECTED:normalized/unexpected.json",)


def test_dataset_verification_checks_the_exact_recursive_raw_file_set(tmp_path: Path) -> None:
    root = tmp_path / "dataset-exact"
    raw_path = root / "raw" / "nested" / "bars.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text('{"bars": []}\n', encoding="utf-8")
    expected_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    manifest = build_manifest(
        run_id="fixture",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
        raw_hashes={"raw/nested/bars.json": expected_hash},
    )
    write_research_contract(root, manifest, {"strategy": "quant-only"})

    assert dataset.verify_dataset(root) == ()
    (root / "raw" / "unexpected.json").write_text("{}\n", encoding="utf-8")
    assert dataset.verify_dataset(root) == ("UNEXPECTED:raw/unexpected.json",)


def test_verify_dataset_cli_fails_closed_on_raw_tampering(tmp_path: Path) -> None:
    output = tmp_path / "verify-dataset"
    root = output / "dataset"
    raw_path = root / "raw" / "bars.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text('{"bars": []}\n', encoding="utf-8")
    manifest = build_manifest(
        run_id="dataset",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
        raw_hashes={"raw/bars.json": hashlib.sha256(raw_path.read_bytes()).hexdigest()},
    )
    write_research_contract(root, manifest, {"strategy": "quant-only"})
    raw_path.write_text('{"bars": ["tampered"]}\n', encoding="utf-8")

    result = CliRunner().invoke(
        cli.app,
        ["verify-dataset", "--run-id", "dataset", "--output", str(output)],
    )

    assert result.exit_code == 1
    assert "HASH_MISMATCH:raw/bars.json" in result.output


def test_raw_research_data_is_ignored_by_git() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "artifacts/research/dataset/raw/option-bars.json",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


def test_development_freeze_is_immutable_and_oos_is_registered_once(tmp_path: Path) -> None:
    output = tmp_path / "freeze"
    development = output / "development"
    manifest = build_manifest(
        run_id="development",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
    )
    write_research_contract(
        development,
        manifest,
        {"strategy_parameters": {"candidate_rule": "point_in_time_v1"}},
    )

    freeze = dataset.freeze_development_run(output, development_run_id="development")
    assert freeze.code_commit == manifest.code_commit
    assert freeze.code_tree_hash == manifest.code_tree_hash
    assert freeze.code_state == manifest.code_state
    assert len(freeze.parameters_hash) == 64
    assert len(freeze.artifact_hash) == 64
    with pytest.raises(FileExistsError, match="immutable"):
        dataset.freeze_development_run(output, development_run_id="development")

    registration = dataset.register_oos_evaluation(
        output,
        evaluation_run_id="evaluation",
    )
    assert registration.freeze_id == freeze.freeze_id
    assert registration.parameters_hash == freeze.parameters_hash
    assert registration.development_artifact_hash == freeze.artifact_hash
    with pytest.raises(FileExistsError, match="already been consumed"):
        dataset.register_oos_evaluation(output, evaluation_run_id="evaluation-2")


def test_freeze_development_cli_writes_the_immutable_registry(tmp_path: Path) -> None:
    output = tmp_path / "freeze-cli"
    development = output / "development"
    manifest = build_manifest(
        run_id="development",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
    )
    write_research_contract(development, manifest, {"strategy_parameters": {"version": 1}})

    result = CliRunner().invoke(
        cli.app,
        ["freeze-development", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    assert (output / "development-freeze.json").exists()


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        (("--symbols", "QQQ"), "symbols"),
        (("--start", "2026-01-03"), "date range"),
        (("--dataset-run-id", "different-dataset"), "dataset run"),
    ],
)
def test_evaluate_rejects_requests_that_do_not_match_the_frozen_development_contract(
    arguments: tuple[str, str], reason: str, tmp_path: Path
) -> None:
    output = tmp_path / "evaluate-contract"
    _write_frozen_evaluation_fixture(output)
    command = [
        "evaluate",
        "--start",
        "2026-01-02",
        "--end",
        "2026-08-21",
        "--symbols",
        "SPY",
        "--dataset-run-id",
        "dataset",
        "--unseal-oos",
        "--output",
        str(output),
    ]
    flag = arguments[0]
    existing = command.index(flag)
    command[existing + 1] = arguments[1]

    result = CliRunner().invoke(cli.app, command)

    assert result.exit_code != 0
    assert reason in result.output.lower()
    assert not (output / ".oos-registry").exists()


def test_evaluate_rejects_changed_dataset_fingerprint_before_consuming_oos(
    tmp_path: Path,
) -> None:
    output = tmp_path / "evaluate-fingerprint"
    _write_frozen_evaluation_fixture(output)
    (output / "dataset" / "raw" / "bars.json").write_text(
        '{"bars": {"SPY": []}}\n', encoding="utf-8"
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "evaluate",
            "--start",
            "2026-01-02",
            "--end",
            "2026-08-21",
            "--symbols",
            "SPY",
            "--dataset-run-id",
            "dataset",
            "--unseal-oos",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code != 0
    assert "dataset fingerprint" in result.output.lower()
    assert not (output / ".oos-registry").exists()


def test_evaluate_rejects_frozen_strategy_or_code_provenance_mismatch(tmp_path: Path) -> None:
    bad_parameters_output = tmp_path / "evaluate-parameters"
    _write_frozen_evaluation_fixture(
        bad_parameters_output,
        strategy_parameters={**FROZEN_STRATEGY_PARAMETERS, "dte": [7, 14]},
    )
    bad_code_output = tmp_path / "evaluate-code"
    _write_frozen_evaluation_fixture(bad_code_output, code_tree_hash="b" * 64)

    results = [
        CliRunner().invoke(
            cli.app,
            [
                "evaluate",
                "--start",
                "2026-01-02",
                "--end",
                "2026-08-21",
                "--symbols",
                "SPY",
                "--dataset-run-id",
                "dataset",
                "--unseal-oos",
                "--output",
                str(output),
            ],
        )
        for output in (bad_parameters_output, bad_code_output)
    ]

    assert results[0].exit_code != 0
    assert "strategy parameters" in results[0].output.lower()
    assert results[1].exit_code != 0
    assert "code provenance" in results[1].output.lower()
    assert not (bad_parameters_output / ".oos-registry").exists()
    assert not (bad_code_output / ".oos-registry").exists()


def test_verify_latest_ignores_freeze_registry_directories(tmp_path: Path) -> None:
    output = tmp_path / "verify-latest"
    run_root = output / "development"
    manifest = build_manifest(
        run_id="development",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
    )
    write_research_contract(run_root, manifest, {"strategy_parameters": {"version": 1}})
    registry = output / ".oos-registry"
    registry.mkdir(parents=True)
    (registry / "entry.json").write_text("{}\n", encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["verify-latest", "--output", str(output)])

    assert result.exit_code == 0, result.output


def test_fetch_records_cli_option_inputs_and_fingerprints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Removing option-data acquisition must make this fail, not merely a mock assertion."""

    def fake_cli(command: list[str]) -> str:
        if command == ["alpaca", "version"]:
            return "alpaca version 1.2.3\n"
        if command[:2] == ["alpaca", "calendar"]:
            return '[{"date":"2025-12-31","open":"09:30","close":"16:00"}]\n'
        if command[:3] == ["alpaca", "data", "multi-bars"]:
            return '{"bars":{"SPY":[{"t":"2025-12-31T14:30:00Z","o":100,"c":101,"v":10}]}}\n'
        if command[:3] == ["alpaca", "option", "contracts"]:
            return (
                '{"option_contracts":[{"id":"contract-1","symbol":"SPY260102C00600000",'
                '"underlying_symbol":"SPY","expiration_date":"2026-01-02"}]}\n'
            )
        if command[:4] == ["alpaca", "data", "option", "bars"]:
            return '{"bars":{"SPY260102C00600000":[{"t":"2025-12-31T14:30:00Z","o":1.00}]}}\n'
        raise AssertionError(command)

    monkeypatch.setattr(cli.shutil, "which", lambda _: "alpaca")
    monkeypatch.setattr(cli, "_run_cli", fake_cli)

    output = tmp_path / "research-cli-fetch"
    result = CliRunner().invoke(
        cli.app,
        [
            "fetch",
            "--run-id",
            "fixture",
            "--start",
            "2024-03-01",
            "--end",
            "2025-12-31",
            "--symbols",
            "SPY",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    root = output / "fixture"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    fingerprint = json.loads((root / "data_fingerprint.json").read_text(encoding="utf-8"))
    assert manifest["contract_ids"] == ["contract-1"]
    assert any("alpaca option contracts" in command for command in manifest["commands"])
    assert (root / "raw" / "option_contracts_SPY_page_001.json").exists()
    assert (root / "raw" / "option_bars_batch_001_page_001.json").exists()
    assert fingerprint["raw_file_count"] == 4
    assert verify_artifacts(root) == ()


def test_develop_executes_raw_dataset_and_writes_gate_artifacts(tmp_path: Path) -> None:
    """Replacing execution with a contract-only summary must make this fail."""

    output = tmp_path / "research-cli-develop"
    run_root = output / "dataset"
    raw_root = run_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    (raw_root / "calendar.json").write_text("[]\n", encoding="utf-8")
    (raw_root / "bars_multi_page_001.json").write_text(
        '{"bars":{"SPY":[{"t":"2025-12-30T14:30:00Z","o":100,"c":101,"v":10},'
        '{"t":"2025-12-31T14:30:00Z","o":101,"c":102,"v":11}]}}\n',
        encoding="utf-8",
    )
    contracts = [
        {
            "id": f"contract-{index}",
            "symbol": symbol,
            "underlying_symbol": "SPY",
            "expiration_date": "2026-01-02",
            "type": right,
            "strike_price": strike,
            "multiplier": "100",
            "size": "100",
            "deliverables": [],
        }
        for index, (symbol, right, strike) in enumerate(
            (
                ("SPY260102P00500000", "put", "500"),
                ("SPY260102P00505000", "put", "505"),
                ("SPY260102C00550000", "call", "550"),
                ("SPY260102C00555000", "call", "555"),
            ),
            start=1,
        )
    ]
    (raw_root / "option_contracts_SPY_page_001.json").write_text(
        json.dumps({"option_contracts": contracts}) + "\n", encoding="utf-8"
    )
    option_bars = {
        contract["symbol"]: [
            {"t": "2025-12-30T14:30:00Z", "o": 1.00},
            {"t": "2025-12-30T14:35:00Z", "o": 1.05 if index in {1, 4} else 0.95},
            {"t": "2025-12-30T14:40:00Z", "o": 0.80 if index in {1, 4} else 1.20},
        ]
        for index, contract in enumerate(contracts, start=1)
    }
    (raw_root / "option_bars_batch_001_page_001.json").write_text(
        json.dumps({"bars": option_bars}) + "\n", encoding="utf-8"
    )
    manifest = build_manifest(
        run_id="dataset",
        start=date(2024, 3, 1),
        end=date(2025, 12, 31),
        symbols=("SPY",),
        unseal_oos=False,
    )
    write_research_contract(run_root, manifest, {"symbols": ["SPY"]})

    result = CliRunner().invoke(
        cli.app,
        [
            "develop",
            "--start",
            "2024-03-01",
            "--end",
            "2025-12-31",
            "--dataset-run-id",
            "dataset",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    development = output / "development"
    assert (development / "trades.csv").exists()
    assert (development / "equity.csv").exists()
    assert (development / "metrics.json").exists()
    assert (development / "diagnostics.json").exists()
    assert (development / "gate.json").exists()
    assert (development / "benchmarks.json").exists()
    assert (development / "ablations.json").exists()
    summary = json.loads((development / "summary.json").read_text(encoding="utf-8"))
    assert summary["execution_status"] == "COMPLETED"
    assert summary["gate_decision"] in {
        "BOTH",
        "LONG_ONLY",
        "SHORT_ONLY",
        "STOP_REDESIGN",
    }
    assert "contract_only_run_no_results" not in summary["warnings"]
    assert Decimal(summary["metrics"]["total_return"]) != Decimal("0")
    assert set(summary["benchmarks"]) == {"SPY", "QQQ", "IWM", "EQUAL_WEIGHT"}
    assert set(summary["ablations"]) == {
        "quant_only",
        "always_long_vol",
        "always_short_vol",
        "hybrid",
    }
    assert summary["gate_decision"] in {"BOTH", "LONG_ONLY", "SHORT_ONLY", "STOP_REDESIGN"}


def test_evaluate_does_not_consume_oos_registration_when_simulation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "evaluate-simulation-failure"
    _write_frozen_evaluation_fixture(output)

    def fail_simulation(*args: object, **kwargs: object) -> object:
        raise RuntimeError("simulation failed")

    monkeypatch.setattr(cli, "_run_local_simulation", fail_simulation)
    result = CliRunner().invoke(
        cli.app,
        [
            "evaluate",
            "--start",
            "2026-01-02",
            "--end",
            "2026-08-21",
            "--symbols",
            "SPY",
            "--dataset-run-id",
            "dataset",
            "--unseal-oos",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code != 0
    assert not (output / ".oos-registry").exists()
