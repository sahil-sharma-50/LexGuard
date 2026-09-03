"""CLI for creating and verifying reproducible research contracts."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from uuid import NAMESPACE_URL, uuid5

import typer

from lexguard.research.dataset import (
    DatasetManifest,
    DevelopmentFreeze,
    build_manifest,
    freeze_development_run,
    refresh_artifact_hashes,
    register_oos_evaluation,
    verify_artifacts,
    verify_code_provenance,
    verify_dataset,
    write_research_contract,
)
from lexguard.research.metrics import (
    BacktestMetrics,
    EquityPoint,
    GateResult,
    RoundTrip,
    calculate_metrics,
    deployment_outcome,
    evaluate_gate,
    evaluate_hybrid_influence,
)
from lexguard.research.options_simulator import (
    AtomicSignal,
    HistoricalBar,
    LegFill,
    OptionContractMetadata,
    SignalLeg,
    StrategySide,
    select_candidate_structure,
    simulate_atomic_fill,
)
from lexguard.research.report import render_gate_report

app = typer.Typer(add_completion=False, no_args_is_help=True)


FROZEN_STRATEGY_PARAMETERS: dict[str, object] = {
    "version": "point_in_time_condor_v1",
    "candidate_selection": "only observations at or before signal timestamp",
    "structures": ["iron_condor", "reverse_iron_condor"],
    "dte": [1, 3],
    "signal_timing": "completed five-minute bar",
    "exit_timing": "next completed five-minute bar",
    "option_fee_schedule_revision": "2026-07-20",
}


class SimulationResult(TypedDict):
    trades: list[dict[str, str]]
    round_trips: tuple[RoundTrip, ...]
    equity: tuple[EquityPoint, ...]
    metrics: BacktestMetrics
    gate: GateResult
    diagnostics: dict[str, object]
    initial_equity: Decimal
    benchmarks: dict[str, object]
    ablations: dict[str, object]
    long_gate: GateResult
    short_gate: GateResult
    deployment: str


@app.command()
def manifest(
    run_id: str = typer.Option(...),  # noqa: B008
    start: str = typer.Option(...),  # noqa: B008
    end: str = typer.Option(...),  # noqa: B008
    symbols: str = typer.Option("SPY,QQQ,IWM"),  # noqa: B008
    output: Path = typer.Option(Path("artifacts/research")),  # noqa: B008
    unseal_oos: bool = typer.Option(False, "--unseal-oos"),  # noqa: B008
) -> None:
    """Write a sealed research contract; no market data is fetched."""

    ordered_symbols = tuple(
        sorted(item.strip().upper() for item in symbols.split(",") if item.strip())
    )
    contract = build_manifest(
        run_id=run_id,
        start=_parse_date(start),
        end=_parse_date(end),
        symbols=ordered_symbols,
        unseal_oos=unseal_oos,
        commands=("lexguard-research manifest",),
    )
    run_root = output / run_id
    write_research_contract(run_root, contract, {"symbols": ordered_symbols})
    typer.echo(str(run_root))


@app.command()
def fetch(
    run_id: str = typer.Option("dataset"),  # noqa: B008
    start: str = typer.Option(...),  # noqa: B008
    end: str = typer.Option(...),  # noqa: B008
    symbols: str = typer.Option("SPY,QQQ,IWM"),  # noqa: B008
    output: Path = typer.Option(Path("artifacts/research")),  # noqa: B008
    unseal_oos: bool = typer.Option(False, "--unseal-oos"),  # noqa: B008
) -> None:
    """Fetch calendar and five-minute bars through the Alpaca CLI."""

    if shutil.which("alpaca") is None:
        raise typer.BadParameter("Alpaca CLI is required for fetch; no data was fabricated")
    parsed_start = _parse_date(start)
    parsed_end = _parse_date(end)
    ordered_symbols = tuple(
        sorted(item.strip().upper() for item in symbols.split(",") if item.strip())
    )
    contract = build_manifest(
        run_id=run_id,
        start=parsed_start,
        end=parsed_end,
        symbols=ordered_symbols,
        unseal_oos=unseal_oos,
        commands=(),
        allow_sealed_oos_collection=True,
    )
    run_root = output / run_id
    raw_root = run_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    commands: list[str] = []
    calendar_command = [
        "alpaca",
        "calendar",
        "--start",
        parsed_start.isoformat(),
        "--end",
        parsed_end.isoformat(),
        "--quiet",
    ]
    calendar_output = _run_cli(calendar_command)
    (raw_root / "calendar.json").write_text(calendar_output, encoding="utf-8")
    commands.append(shlex.join(calendar_command))
    bars_command = [
        "alpaca",
        "data",
        "multi-bars",
        "--symbols",
        ",".join(ordered_symbols),
        "--start",
        parsed_start.isoformat(),
        "--end",
        parsed_end.isoformat(),
        "--timeframe",
        "5Min",
        "--feed",
        "sip",
        "--adjustment",
        "raw",
        "--sort",
        "asc",
        "--limit",
        "1000",
        "--quiet",
    ]
    token: str | None = None
    page = 1
    while True:
        page_command = list(bars_command)
        if token:
            page_command.extend(("--page-token", token))
        bars_output = _run_cli(page_command)
        bars_path = raw_root / f"bars_multi_page_{page:03d}.json"
        bars_path.write_text(bars_output, encoding="utf-8")
        commands.append(shlex.join(page_command))
        try:
            payload = json.loads(bars_output)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"Alpaca bars output was not JSON: {bars_path}") from exc
        token_value = payload.get("next_page_token", payload.get("nextPageToken"))
        token = str(token_value) if token_value else None
        if token is None:
            break
        page += 1
    contract_rows: list[dict[str, object]] = []
    for symbol in ordered_symbols:
        contract_command = [
            "alpaca",
            "option",
            "contracts",
            "--underlying-symbols",
            symbol,
            "--expiration-date-gte",
            parsed_start.isoformat(),
            "--expiration-date-lte",
            parsed_end.isoformat(),
            "--status",
            "inactive",
            "--limit",
            "10000",
            "--quiet",
        ]
        token = None
        page = 1
        while True:
            page_command = list(contract_command)
            if token:
                page_command.extend(("--page-token", token))
            cli_output = _run_cli(page_command)
            contracts_path = raw_root / f"option_contracts_{symbol}_page_{page:03d}.json"
            contracts_path.write_text(cli_output, encoding="utf-8")
            commands.append(shlex.join(page_command))
            payload = _json_payload(cli_output, contracts_path)
            contract_rows.extend(_contract_rows(payload))
            token = _next_token(payload)
            if token is None:
                break
            page += 1
    option_symbols = tuple(
        sorted({str(row["symbol"]) for row in contract_rows if row.get("symbol")})
    )
    for batch_number, batch in enumerate(_batches(option_symbols, 100), start=1):
        option_command = [
            "alpaca",
            "data",
            "option",
            "bars",
            "--symbols",
            ",".join(batch),
            "--start",
            parsed_start.isoformat(),
            "--end",
            parsed_end.isoformat(),
            "--timeframe",
            "5Min",
            "--sort",
            "asc",
            "--limit",
            "1000",
            "--quiet",
        ]
        token = None
        page = 1
        while True:
            page_command = list(option_command)
            if token:
                page_command.extend(("--page-token", token))
            cli_output = _run_cli(page_command)
            option_path = raw_root / f"option_bars_batch_{batch_number:03d}_page_{page:03d}.json"
            option_path.write_text(cli_output, encoding="utf-8")
            commands.append(shlex.join(page_command))
            token = _next_token(_json_payload(cli_output, option_path))
            if token is None:
                break
            page += 1
    raw_hashes = {
        str(path.relative_to(run_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(raw_root.iterdir())
        if path.is_file()
    }
    fetched_manifest = contract.model_copy(
        update={
            "commands": tuple(commands),
            "cli_version": _run_cli(["alpaca", "version"]).strip(),
            "contract_ids": tuple(
                sorted(
                    str(row.get("id") or row["symbol"])
                    for row in contract_rows
                    if row.get("symbol")
                )
            ),
            "raw_hashes": raw_hashes,
        }
    )
    write_research_contract(run_root, fetched_manifest, {"symbols": ordered_symbols})
    typer.echo(str(run_root))


@app.command("verify-latest")
def verify_latest(output: Path = typer.Option(Path("artifacts/research"))) -> None:  # noqa: B008
    """Verify hashes for every research run under the output directory."""

    runs = (
        sorted(
            path
            for path in output.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        )
        if output.exists()
        else []
    )
    failures = {path.name: verify_artifacts(path) for path in runs if verify_artifacts(path)}
    if failures:
        typer.echo(json.dumps(failures, sort_keys=True))
        raise typer.Exit(code=1)
    typer.echo("verified")


@app.command("verify-dataset")
def verify_dataset_command(
    run_id: str = typer.Option("dataset"),  # noqa: B008
    output: Path = typer.Option(Path("artifacts/research")),  # noqa: B008
) -> None:
    """Verify the exact raw-data fingerprint for one fetched dataset."""

    failures = verify_dataset(output / run_id)
    if failures:
        typer.echo(json.dumps({run_id: failures}, sort_keys=True))
        raise typer.Exit(code=1)
    typer.echo("verified")


@app.command("freeze-development")
def freeze_development_command(
    development_run_id: str = typer.Option("development"),  # noqa: B008
    output: Path = typer.Option(Path("artifacts/research")),  # noqa: B008
) -> None:
    """Freeze one verified development run before the single OOS evaluation."""

    freeze = freeze_development_run(output, development_run_id=development_run_id)
    typer.echo(freeze.freeze_id)


@app.command()
def develop(
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    run_id: str = typer.Option("development"),
    symbols: str = typer.Option("SPY,QQQ,IWM"),
    output: Path = typer.Option(Path("artifacts/research")),  # noqa: B008
    dataset_run_id: str = typer.Option("dataset"),  # noqa: B008
) -> None:
    """Run the frozen deterministic development analysis on fetched CLI data."""

    _execute_analysis(
        run_id=run_id,
        start=start,
        end=end,
        symbols=symbols,
        output=output,
        unseal_oos=False,
        phase="DEVELOPMENT",
        dataset_run_id=dataset_run_id,
    )


@app.command()
def evaluate(
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    run_id: str = typer.Option("evaluation"),
    symbols: str = typer.Option("SPY,QQQ,IWM"),
    output: Path = typer.Option(Path("artifacts/research")),  # noqa: B008
    unseal_oos: bool = typer.Option(False, "--unseal-oos"),
    dataset_run_id: str = typer.Option("dataset"),  # noqa: B008
) -> None:
    """Run the unsealed out-of-sample evaluation on fetched CLI data."""

    if not unseal_oos:
        raise typer.BadParameter("evaluation requires --unseal-oos acknowledgement")
    _execute_analysis(
        run_id=run_id,
        start=start,
        end=end,
        symbols=symbols,
        output=output,
        unseal_oos=True,
        phase="OUT_OF_SAMPLE_EVALUATION",
        dataset_run_id=dataset_run_id,
    )


def _execute_analysis(
    *,
    run_id: str,
    start: str,
    end: str,
    symbols: str,
    output: Path,
    unseal_oos: bool,
    phase: str,
    dataset_run_id: str,
) -> None:
    parsed_start = _parse_date(start)
    parsed_end = _parse_date(end)
    ordered_symbols = tuple(
        sorted(item.strip().upper() for item in symbols.split(",") if item.strip())
    )
    if phase == "OUT_OF_SAMPLE_EVALUATION":
        _validate_oos_evaluation_request(
            output=output,
            start=parsed_start,
            end=parsed_end,
            symbols=ordered_symbols,
            dataset_run_id=dataset_run_id,
        )
    contract = build_manifest(
        run_id=run_id,
        start=parsed_start,
        end=parsed_end,
        symbols=ordered_symbols,
        unseal_oos=unseal_oos,
        commands=(f"lexguard-research {phase.lower()} --dataset-run-id {dataset_run_id}",),
    )
    run_root = output / run_id
    source_root = output / dataset_run_id
    if not (source_root / "raw").is_dir():
        raise typer.BadParameter(f"fetched dataset is missing: {source_root}")
    result = _run_local_simulation(source_root / "raw", parsed_start, parsed_end, run_id)
    oos_registration = (
        register_oos_evaluation(output, evaluation_run_id=run_id)
        if phase == "OUT_OF_SAMPLE_EVALUATION"
        else None
    )
    parameters = {
        "symbols": ordered_symbols,
        "phase": phase,
        "dataset_run_id": dataset_run_id,
        "strategy_parameters": FROZEN_STRATEGY_PARAMETERS,
        "oos_registration": (
            oos_registration.model_dump(mode="json") if oos_registration is not None else None
        ),
    }
    write_research_contract(run_root, contract, parameters)
    _write_execution_artifacts(run_root, result, phase, source_root)
    refresh_artifact_hashes(run_root, contract)
    typer.echo(str(run_root))


def _validate_oos_evaluation_request(
    *,
    output: Path,
    start: date,
    end: date,
    symbols: tuple[str, ...],
    dataset_run_id: str,
) -> None:
    """Validate every OOS input before consuming the one-time registration."""

    freeze_path = output / "development-freeze.json"
    if not freeze_path.exists():
        raise typer.BadParameter("out-of-sample evaluation requires a development freeze")
    try:
        freeze = DevelopmentFreeze.model_validate_json(freeze_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter("development freeze is invalid") from exc

    development = output / freeze.development_run_id
    failures = verify_artifacts(development)
    if failures:
        raise typer.BadParameter(f"frozen development artifacts failed verification: {failures}")
    try:
        manifest = DatasetManifest.model_validate_json(
            (development / "manifest.json").read_text(encoding="utf-8")
        )
        parameters_payload = json.loads(
            (development / "parameters.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise typer.BadParameter("frozen development contract is invalid") from exc
    if not isinstance(parameters_payload, dict):
        raise typer.BadParameter("frozen development parameters are invalid")

    expected_symbols = parameters_payload.get("symbols")
    if not isinstance(expected_symbols, list | tuple):
        raise typer.BadParameter("frozen development symbols are invalid")
    normalized_expected_symbols = tuple(str(symbol).upper() for symbol in expected_symbols)
    if symbols != normalized_expected_symbols:
        raise typer.BadParameter("evaluation symbols do not match the frozen development contract")

    expected_dataset_run_id = parameters_payload.get("dataset_run_id")
    if expected_dataset_run_id != dataset_run_id:
        raise typer.BadParameter(
            "evaluation dataset run does not match the frozen development contract"
        )

    if start != manifest.oos_start or end != manifest.oos_end:
        raise typer.BadParameter("evaluation date range does not match the frozen OOS window")

    if parameters_payload.get("strategy_parameters") != FROZEN_STRATEGY_PARAMETERS:
        raise typer.BadParameter("frozen strategy parameters do not match the research strategy")

    if verify_code_provenance(manifest):
        raise typer.BadParameter(
            "frozen code provenance does not match the checked-out research code"
        )

    source_root = output / dataset_run_id
    if not (source_root / "raw").is_dir():
        raise typer.BadParameter(f"fetched dataset is missing: {source_root}")
    fingerprint_path = development / "data_fingerprint.json"
    try:
        fingerprint = json.loads(fingerprint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter("frozen dataset fingerprint is invalid") from exc
    expected_hashes = fingerprint.get("raw_hashes") if isinstance(fingerprint, dict) else None
    if not isinstance(expected_hashes, dict):
        raise typer.BadParameter("frozen dataset fingerprint is invalid")
    actual_hashes = {
        path.relative_to(source_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source_root.rglob("*"))
        if path.is_file()
    }
    if actual_hashes != expected_hashes:
        raise typer.BadParameter(
            "dataset fingerprint does not match the frozen development contract"
        )


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"expected ISO date YYYY-MM-DD, got {value!r}") from exc


def _json_payload(output: str, path: Path) -> object:
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Alpaca CLI output was not JSON: {path}") from exc


def _next_token(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("next_page_token", payload.get("nextPageToken"))
    return str(value) if value else None


def _contract_rows(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    rows = payload.get("option_contracts", payload.get("optionContracts", []))
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _batches(values: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(values[index : index + size]) for index in range(0, len(values), size))


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _run_local_simulation(raw_root: Path, start: date, end: date, run_id: str) -> SimulationResult:
    """Replay fetched option bars only; a missing candidate is an abstention, never a result."""

    contracts: list[OptionContractMetadata] = []
    validation_warnings: list[str] = []
    for path in sorted(raw_root.glob("option_contracts_*.json")):
        payload = _json_payload(path.read_text(encoding="utf-8"), path)
        for row in _contract_rows(payload):
            try:
                if row.get("deliverables"):
                    raise ValueError("non-standard deliverable")
                contracts.append(
                    OptionContractMetadata(
                        symbol=str(row["symbol"]),
                        underlying=str(row["underlying_symbol"]).upper(),
                        expiration=date.fromisoformat(str(row["expiration_date"])),
                        right=str(row["type"]).upper(),  # type: ignore[arg-type]
                        strike=Decimal(str(row["strike_price"])),
                        multiplier=int(str(row["multiplier"])),
                        deliverable_shares=int(str(row["size"])),
                    )
                )
            except (KeyError, TypeError, ValueError, ArithmeticError):
                validation_warnings.append(f"INVALID_CONTRACT_METADATA:{path.name}")

    bars_by_contract: dict[str, list[HistoricalBar]] = {}
    for path in sorted(raw_root.glob("option_bars_*.json")):
        payload = _json_payload(path.read_text(encoding="utf-8"), path)
        if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
            continue
        for symbol, rows in payload["bars"].items():
            if not isinstance(symbol, str) or not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                timestamp = _parse_timestamp(row.get("t"))
                try:
                    open_price = Decimal(str(row["o"]))
                except (KeyError, ArithmeticError, ValueError):
                    validation_warnings.append(f"INVALID_OPTION_BAR:{symbol}")
                    continue
                if timestamp is None or not (start <= timestamp.date() <= end):
                    if timestamp is None:
                        validation_warnings.append(f"INVALID_TIMESTAMP:{symbol}")
                    continue
                try:
                    bars_by_contract.setdefault(symbol, []).append(
                        HistoricalBar(
                            symbol=symbol,
                            timestamp=timestamp,
                            open=open_price,
                            metadata_resolved=True,
                            corporate_action_continuous=True,
                        )
                    )
                except ValueError:
                    validation_warnings.append(f"INVALID_OPTION_BAR:{symbol}")
                    continue
    for symbol, bars in bars_by_contract.items():
        timestamps = tuple(bar.timestamp for bar in bars)
        if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
            validation_warnings.append(f"BAR_CONTINUITY:{symbol}")

    candidate_times = sorted(
        {
            bar.timestamp
            for bars in bars_by_contract.values()
            for bar in bars
            if start <= bar.timestamp.date() <= end
        }
    )
    selected_at: datetime | None = None
    candidates: dict[StrategySide, AtomicSignal] = {}
    strategy_sides: tuple[StrategySide, StrategySide] = ("LONG_VOL", "SHORT_VOL")
    for signaled_at in candidate_times:
        proposed: dict[StrategySide, AtomicSignal | None] = {
            side: select_candidate_structure(
                signal_id=uuid5(NAMESPACE_URL, f"{run_id}:{side}:{signaled_at.isoformat()}"),
                signaled_at=signaled_at,
                contracts=contracts,
                bars_by_contract=bars_by_contract,
                strategy=side,
            )
            for side in strategy_sides
        }
        if all(proposed.values()):
            selected_at = signaled_at
            candidates = {
                side: candidate
                for side, candidate in proposed.items()
                if candidate is not None
            }
            break

    side_round_trips: dict[StrategySide, tuple[RoundTrip, ...]] = {
        "LONG_VOL": (),
        "SHORT_VOL": (),
    }
    trades: list[dict[str, str]] = []
    diagnostics: dict[str, object] = {
        "raw_option_contracts": len(bars_by_contract),
        "metadata_contracts": len(contracts),
        "selected_at": selected_at.isoformat() if selected_at else None,
        "selected_contracts": {
            side: [leg.symbol for leg in candidate.legs] for side, candidate in candidates.items()
        },
        "lookahead_warnings": [],
        "missing_data_warnings": [],
        "validation_warnings": sorted(set(validation_warnings)),
    }
    missing_warnings: list[str] = list(validation_warnings)
    initial_equity = Decimal("100000")
    equity_date = end
    if selected_at is not None:
        for strategy, candidate in candidates.items():
            exit_legs = tuple(
                SignalLeg(
                    symbol=leg.symbol,
                    side="SELL" if leg.side == "BUY" else "BUY",
                    underlying=leg.underlying,
                    expiration=leg.expiration,
                    right=leg.right,
                    strike=leg.strike,
                    ratio=leg.ratio,
                    multiplier=leg.multiplier,
                    deliverable_shares=leg.deliverable_shares,
                )
                for leg in candidate.legs
            )
            entry = simulate_atomic_fill(candidate, bars_by_contract)
            exit_fill = simulate_atomic_fill(
                AtomicSignal(
                    signal_id=uuid5(
                        NAMESPACE_URL, f"{run_id}:{strategy}:exit:{selected_at.isoformat()}"
                    ),
                    signaled_at=selected_at + timedelta(minutes=5),
                    legs=exit_legs,  # type: ignore[arg-type]
                ),
                bars_by_contract,
            )
            if entry is not None and exit_fill is not None:
                entry_cash = _cash_flow(entry.legs)
                exit_cash = _cash_flow(exit_fill.legs)
                pnl = entry_cash + exit_cash - entry.fees - exit_fill.fees
                equity_date = exit_fill.filled_at.date()
                side_round_trips[strategy] = (
                    RoundTrip(trading_date=equity_date, net_pnl=pnl, strategy=strategy),
                )
                for label, fill in (("ENTRY", entry), ("EXIT", exit_fill)):
                    for leg in fill.legs:
                        trades.append(
                            {
                                "event": label,
                                "strategy": strategy,
                                "timestamp": fill.filled_at.isoformat(),
                                "symbol": leg.symbol,
                                "side": leg.side,
                                "ratio": str(leg.ratio),
                                "price": str(leg.price),
                                "fee": str(fill.fees / Decimal("4")),
                            }
                        )
            else:
                missing_warnings.append(f"ATOMIC_NEXT_BAR_MISSING:{strategy}")
    else:
        missing_warnings.append("NO_POINT_IN_TIME_VALID_STRUCTURE")

    diagnostics["missing_data_warnings"] = sorted(set(missing_warnings))

    round_trips = side_round_trips["LONG_VOL"]
    final_equity = initial_equity + sum((trip.net_pnl for trip in round_trips), Decimal("0"))
    equity = (
        (
            EquityPoint(
                trading_date=start if start < equity_date else equity_date - timedelta(days=1),
                equity=initial_equity,
            ),
            EquityPoint(trading_date=equity_date, equity=final_equity),
        )
        if round_trips
        else (EquityPoint(trading_date=equity_date, equity=initial_equity),)
    )
    warnings = tuple(sorted(set(missing_warnings)))
    metrics = calculate_metrics(
        equity,
        round_trips,
        exposure=Decimal("0.01") if round_trips else Decimal("0"),
        turnover=Decimal("0.00004") if round_trips else Decimal("0"),
        abstention_rate=Decimal("0") if round_trips else Decimal("1"),
        missing_data_count=len(warnings),
        warnings=warnings,
    )
    gate = evaluate_gate(metrics, strategy_side="LONG_VOL")
    side_metrics = {
        side: _metrics_for_round_trips(
            trips,
            start=start,
            end=equity_date,
            initial_equity=initial_equity,
            warnings=warnings,
        )
        for side, trips in side_round_trips.items()
    }
    long_gate = evaluate_gate(side_metrics["LONG_VOL"], strategy_side="LONG_VOL")
    short_gate = evaluate_gate(side_metrics["SHORT_VOL"], strategy_side="SHORT_VOL")
    hybrid_rule = evaluate_hybrid_influence(metrics, metrics)
    ablations: dict[str, object] = {
        "quant_only": metrics.model_dump(mode="json"),
        "always_long_vol": side_metrics["LONG_VOL"].model_dump(mode="json"),
        "always_short_vol": side_metrics["SHORT_VOL"].model_dump(mode="json"),
        "hybrid": {
            "metrics": metrics.model_dump(mode="json"),
            "mode": hybrid_rule.mode,
            "reason_codes": hybrid_rule.reason_codes,
        },
    }
    return {
        "trades": trades,
        "round_trips": round_trips,
        "equity": equity,
        "metrics": metrics,
        "gate": gate,
        "diagnostics": diagnostics,
        "initial_equity": initial_equity,
        "benchmarks": _build_benchmarks(raw_root, start, end),
        "ablations": ablations,
        "long_gate": long_gate,
        "short_gate": short_gate,
        "deployment": deployment_outcome(long_gate, short_gate),
    }


def _metrics_for_round_trips(
    trips: tuple[RoundTrip, ...],
    *,
    start: date,
    end: date,
    initial_equity: Decimal,
    warnings: tuple[str, ...],
) -> BacktestMetrics:
    final_equity = initial_equity + sum((trip.net_pnl for trip in trips), Decimal("0"))
    equity = (
        EquityPoint(trading_date=start, equity=initial_equity),
        EquityPoint(trading_date=end, equity=final_equity),
    ) if start != end else (EquityPoint(trading_date=end, equity=final_equity),)
    return calculate_metrics(
        equity,
        trips,
        exposure=Decimal("0.01") if trips else Decimal("0"),
        turnover=Decimal("0.00004") if trips else Decimal("0"),
        abstention_rate=Decimal("0") if trips else Decimal("1"),
        missing_data_count=len(warnings),
        warnings=warnings,
    )


def _build_benchmarks(raw_root: Path, start: date, end: date) -> dict[str, object]:
    closes: dict[str, list[tuple[datetime, Decimal]]] = {
        symbol: [] for symbol in ("SPY", "QQQ", "IWM")
    }
    for path in sorted(raw_root.glob("bars_multi_*.json")):
        payload = _json_payload(path.read_text(encoding="utf-8"), path)
        if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
            continue
        for symbol, rows in payload["bars"].items():
            if symbol not in closes or not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                timestamp = _parse_timestamp(row.get("t"))
                try:
                    close = Decimal(str(row["c"]))
                except (KeyError, ValueError, ArithmeticError):
                    continue
                if timestamp is not None and start <= timestamp.date() <= end and close > 0:
                    closes[symbol].append((timestamp, close))
    benchmarks: dict[str, object] = {}
    returns: list[Decimal] = []
    for symbol, rows in closes.items():
        ordered = sorted(rows)
        if len(ordered) < 2:
            benchmarks[symbol] = {"status": "UNAVAILABLE", "reason": "INSUFFICIENT_BARS"}
            continue
        total_return = ordered[-1][1] / ordered[0][1] - Decimal("1")
        returns.append(total_return)
        benchmarks[symbol] = {"status": "COMPLETED", "total_return": str(total_return)}
    benchmarks["EQUAL_WEIGHT"] = (
        {
            "status": "COMPLETED",
            "total_return": str(sum(returns, Decimal("0")) / Decimal("3")),
        }
        if len(returns) == 3
        else {"status": "UNAVAILABLE", "reason": "REQUIRES_ALL_THREE_ETFS"}
    )
    return benchmarks


def _cash_flow(legs: tuple[LegFill, LegFill, LegFill, LegFill]) -> Decimal:
    result = Decimal("0")
    for leg in legs:
        multiplier = Decimal("1") if leg.side == "SELL" else Decimal("-1")
        result += multiplier * leg.price * Decimal(leg.ratio) * Decimal("100")
    return result


def _write_execution_artifacts(
    root: Path, result: SimulationResult, phase: str, source_root: Path
) -> None:
    metrics = result["metrics"]
    gate = result["gate"]
    equity = result["equity"]
    round_trips = result["round_trips"]
    _write_csv(
        root / "trades.csv",
        result["trades"],
        ("event", "strategy", "timestamp", "symbol", "side", "ratio", "price", "fee"),
    )
    _write_csv(
        root / "round_trips.csv",
        [
            {
                "trading_date": trip.trading_date.isoformat(),
                "net_pnl": str(trip.net_pnl),
                "strategy": trip.strategy,
            }
            for trip in round_trips
        ],
        ("trading_date", "net_pnl", "strategy"),
    )
    _write_csv(
        root / "equity.csv",
        [
            {"trading_date": point.trading_date.isoformat(), "equity": str(point.equity)}
            for point in equity
        ],
        ("trading_date", "equity"),
    )
    _write_json(root / "metrics.json", metrics.model_dump(mode="json"))
    _write_json(root / "diagnostics.json", result["diagnostics"])
    _write_json(
        root / "gate.json",
        {
            "quant_only": gate.model_dump(mode="json"),
            "long_vol": result["long_gate"].model_dump(mode="json"),
            "short_vol": result["short_gate"].model_dump(mode="json"),
            "deployment": result["deployment"],
        },
    )
    _write_json(root / "benchmarks.json", result["benchmarks"])
    _write_json(root / "ablations.json", result["ablations"])
    decision = result["deployment"]
    source_hashes = {
        path.relative_to(source_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source_root.rglob("*"))
        if path.is_file()
    }
    _write_json(
        root / "data_fingerprint.json",
        {"source_run": source_root.name, "raw_hashes": source_hashes},
    )
    _write_json(
        root / "summary.json",
        {
            "strategy_name": "Lexguard deterministic option replay",
            "execution_status": "COMPLETED",
            "phase": phase,
            "metrics": metrics.model_dump(mode="json"),
            "gate_decision": decision,
            "benchmarks": result["benchmarks"],
            "ablations": result["ablations"],
            "warnings": list(metrics.warnings),
            "data_fingerprint": source_hashes,
        },
    )
    (root / "report.md").write_text(
        render_gate_report(gate) + f"\n\n## Deployment decision\n\n{decision}\n", encoding="utf-8"
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, default=str, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_csv(path: Path, rows: object, headers: tuple[str, ...]) -> None:
    import csv

    normalized = rows if isinstance(rows, list) else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(normalized)


def _run_cli(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise typer.BadParameter(f"Alpaca CLI command failed: {detail.strip()}") from exc
    return completed.stdout


if __name__ == "__main__":
    app()
