# Alpaca Integration Findings

This file records verified, reusable Alpaca integration facts. Source paths
that refer to Alpaca documentation or the official MCP repository describe
optional local research checkouts and are not required runtime dependencies of
this repository.

## Options market data through Alpaca MCP
- `get_option_chain` returns contracts for an underlying with latest trade, quote, implied volatility, and Greeks; filters include option type, strike range, expiration, and limit. `get_option_snapshot` provides the same market-state fields for selected contracts.
- Source: `alpaca-mcp-server/src/alpaca_mcp_server/tool_registry.py` - `OptionChain` and `OptionSnapshots` tool definitions.

## Atomic multi-leg options orders
- Alpaca Trading API submits an options strategy through `POST /v2/orders` with `order_class: "mleg"`, a parent strategy quantity, and up to four option legs. The MCP tool is `place_option_order`; its multi-leg limit price is positive for a net debit and negative for a net credit.
- Source: `alpaca-documentation/trading-api.json` - `postOrder`, `CreateOrderRequest`, and `OrderClass`; `alpaca-mcp-server/src/alpaca_mcp_server/overrides.py` - `place_option_order`.

## Multi-leg execution constraints
- Multi-leg orders cannot contain an equity leg, all legs must be covered within the same order, and leg ratios must be in lowest terms. Alpaca supports order-price replacement via `PATCH /v2/orders/{order_id}`, but a successful replace response does not guarantee replacement if the original fills first, so the resulting order state must be reconciled.
- Source: `alpaca-documentation/Trading API/Options Trading/Options_Level_3_Trading.md` - edge scenarios; `alpaca-documentation/trading-api.json` - `patchOrderByOrderId`.

## Read-only observation MCP surface
- The observation gateway may call `get_clock`, `get_account_info`, `get_orders`, `get_all_positions`, `get_stock_bars`, `get_option_chain`, and `get_news`; the MCP toolset documentation classifies these as clock/account/trading/position/stock/options/news tools. It must not expose order-capable MCP calls.
- Source: `alpaca-documentation/Trading_MCP_Server.md` - Toolset Filtering and Available Tools; `alpaca-mcp-server/src/alpaca_mcp_server/tool_registry.py` - `getAccount`, `getAllOrders`, `getAllOpenPositions`, `LegacyClock`, `OptionChain`, and `News`.

## Observation payload fields and options feed
- `get_option_chain` accepts `underlying_symbol` and supports narrowing by option type, strike bounds, expiration date, and limit. Option snapshots contain latest trade, quote, implied volatility, and Greeks. News records carry an integer `id`, `headline`, `created_at`, `updated_at`, `url`, `content`, `symbols`, and `source`.
- Source: `alpaca-mcp-server/src/alpaca_mcp_server/tool_registry.py` - `OptionChain` and `News`; `alpaca-documentation/Market Data API/Real-time_News.md` - news message fields.
- Indicative option prices are derived quotes/trades and trades are delayed by
  15 minutes; OPRA is the consolidated BBO feed and requires a subscription.
  Lexguard accepts either feed only when it is explicitly configured and the
  response provenance matches the configured value.
- Source: `alpaca-documentation/Market Data API/Historical_Option_Data.md` - Data sources.

## Account and clock SDK fields
- The trading account exposes `status`, `equity`, `buying_power`, `options_approved_level`, and effective `options_trading_level`; the clock exposes `timestamp`, `is_open`, `next_open`, and `next_close`. The paper-only TradingClient base URL is `https://paper-api.alpaca.markets`.
- Source: `alpaca-py/Trading_Reference/Models.md` - `TradeAccount` and `Clock`; `alpaca-py/Trading_Reference/TradingClient.md` - `TradingClient(..., paper=True, url_override=...)`; `alpaca-documentation/Trading API/Paper_Trading.md` - paper endpoint configuration.
- `alpaca-py==0.42.2` constructs paper trading with `TradingClient(api_key, secret_key, paper=True, url_override=...)`. The verified sync methods are `submit_order(LimitOrderRequest)`, `get_order_by_id(order_id, filter)`, `replace_order_by_id(order_id, ReplaceOrderRequest)`, `cancel_order_by_id(order_id)`, `get_account()`, and `get_all_positions()`.
- An atomic options order is a `LimitOrderRequest(type=OrderType.LIMIT, time_in_force=TimeInForce.DAY, order_class=OrderClass.MLEG, qty=..., limit_price=..., legs=[OptionLegRequest(...)])`. Each `OptionLegRequest` has `symbol`, positive `ratio_qty`, `side`, and a `PositionIntent`. Opening legs use `BUY_TO_OPEN` or `SELL_TO_OPEN`; closing legs use `BUY_TO_CLOSE` or `SELL_TO_CLOSE`.
- The certified net debit/credit sign is preserved in the request's `limit_price`: a debit is positive and a credit is negative. The four-leg request must remain one `mleg` submission; replacement is a separate `ReplaceOrderRequest` and can race with a fill, so the original and replacement IDs must both be queried before deciding state.
- Source: `alpaca-py/Trading_Reference/TradingClient.md`, `alpaca-py/Trading_Reference/Requests.md`, `alpaca-py/Trading_Reference/Enums.md`, and the installed `alpaca-py==0.42.2` signatures/enums verified offline on 2026-08-23.
- Alpaca calendar checks use `TradingClient.get_calendar(GetCalendarRequest(start=<date>, end=<date>))`; each `Calendar` carries the trading date plus timezone-aware `open` and `close` datetimes. Early closes are therefore broker calendar data, not a hard-coded holiday table.
- Source: `alpaca-py/Trading_Reference/Requests.md` (`GetCalendarRequest`), `alpaca-py/Trading_Reference/Models.md` (`Calendar`), and the installed `alpaca-py==0.42.2` signatures verified offline on 2026-08-23.

## Options regulatory and clearing fees
- Alpaca's July 20, 2026 brokerage fee schedule lists options ORF at $0.015 per contract and OCC clearing at $0.025 per contract on buys and sells, CAT at $0.000003 per executed equivalent share (100 shares for a standard contract), TAF at $0.00329 per sold contract, and the SEC transaction fee on sells at 0.0000206 times trade value. Fee types are aggregated daily per account and rounded up by type to the nearest cent.
- Source: `alpaca-documentation/Trading API/Regulatory_Fees.md` - options fee categories and daily charging behavior; `https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf` - Brokerage Fee Schedule revised July 20, 2026, pages 2–3.
