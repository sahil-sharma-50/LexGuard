"""Compact reproducibility report rendering for research artifacts."""

from __future__ import annotations

from lexguard.research.metrics import GateResult

DISCLOSURE = (
    "**Important disclosure**  \n"
    "This backtest is a hypothetical historical simulation and does not represent actual trading "
    "performance. Backtested results do not guarantee future results. Results depend on "
    "market-data "
    "quality, data feed selection, corporate-action handling, fees, slippage, liquidity, taxes, "
    "execution assumptions, and implementation details. This material is for research and "
    "educational purposes only and is not investment advice, a recommendation, an offer, or a "
    "solicitation to buy or sell securities, options, cryptocurrencies, or any other financial "
    "product. All investments involve risk and may lose value. Review Alpaca's disclosures at "
    "[alpaca.markets/disclosures](https://alpaca.markets/disclosures)."
)

PAPER_DISCLOSURE = (
    "Paper trading is a simulated environment. It does not involve real money or actual securities "
    "transactions. Paper results may differ from live trading because of fill assumptions, market "
    "impact, liquidity, latency, data differences, order handling, fees, and other market "
    "conditions."
)


def render_gate_report(result: GateResult) -> str:
    metrics = result.metrics
    return "\n".join(
        (
            "# Lexguard research gate",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Total return | {metrics.total_return} |",
            f"| Daily Sharpe | {metrics.daily_sharpe} |",
            f"| Max drawdown | {metrics.max_drawdown} |",
            f"| Profit factor | {metrics.profit_factor} |",
            f"| Completed trades | {metrics.completed_trades} |",
            f"| Gate | {'PASS' if result.passed else 'STOP/REDESIGN'} |",
            f"| Reasons | {', '.join(result.reason_codes) or 'none'} |",
            "",
            DISCLOSURE,
            "",
            PAPER_DISCLOSURE,
            "",
            "Fee source: https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf",
        )
    )
