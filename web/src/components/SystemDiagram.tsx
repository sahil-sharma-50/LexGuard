/** A simple overview; the accessible stage list below is the detailed record. */
const STAGES = [
  { index: "01", event: "OBSERVE", actor: "Alpaca MCP server", copy: "Clock, account, bars, option chains, and the news tape are collected through the official MCP server, then frozen into a content-hashed snapshot.", crosses: "A sealed snapshot" },
  { index: "02", event: "FORECAST", actor: "Quant artifact", copy: "A distribution over close-to-close returns is recorded as an artifact with its uncertainty stated in text.", crosses: "A recorded distribution" },
  { index: "03", event: "ARGUE", actor: "OpenAI catalyst · advisory only", copy: "The model classifies the snapshot or vetoes, citing only supplied Alpaca news IDs. It cannot pick strikes, size, price, or broker actions.", crosses: "An argument, or a veto" },
  { index: "04", event: "CERTIFY", actor: "Deterministic judge", copy: "Code recomputes exact max loss and applies independent risk gates. Without a certificate, nothing can trade.", crosses: "One tamper-evident certificate, or nothing" },
  { index: "05", event: "EXECUTE", actor: "Alpaca Trading API · paper", copy: "One atomic four-leg paper order is submitted with deterministic identifiers and fail-closed verification.", crosses: "Broker order IDs and fills" },
  { index: "06", event: "VERIFY", actor: "Reconciliation · ledger", copy: "Broker truth is reconciled against the append-only, hash-chained ledger every tick. A mismatch halts entries.", crosses: "A replayable case file" },
] as const

function DiagramBox({ x, y, title, detail, accent = false }: { x: number; y: number; title: string; detail: string; accent?: boolean }) {
  return <g><rect className={accent ? "sd-simple-box sd-simple-box-accent" : "sd-simple-box"} x={x} y={y} width="300" height="72" rx="3" /><text className={accent ? "sd-simple-title sd-title-seal" : "sd-simple-title"} x={x + 18} y={y + 29}>{title}</text><text className="sd-simple-detail" x={x + 18} y={y + 51}>{detail}</text></g>
}

export function SystemDiagram() {
  return (
    <figure className="system-diagram">
      <svg className="system-diagram-svg" viewBox="0 0 1160 410" role="img" aria-labelledby="system-diagram-title system-diagram-desc">
        <title id="system-diagram-title">Three-part Lexguard decision flow</title>
        <desc id="system-diagram-desc">Evidence is observed, hashed, forecast, and argued without trading authority. A deterministic risk certificate alone crosses the decision boundary. Certified paper execution is reconciled into the public read-only case file.</desc>
        <defs><marker id="sd-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path className="sd-head" d="M0 1 L9 5 L0 9 z" /></marker><marker id="sd-head-seal" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path className="sd-head-seal" d="M0 1 L9 5 L0 9 z" /></marker></defs>
        <text className="sd-band" x="20" y="30">EVIDENCE</text><text className="sd-band" x="430" y="30">DECISION ROOM</text><text className="sd-band" x="840" y="30">EXECUTION RECORD</text>
        <DiagramBox x={20} y={52} title="ALPACA MCP" detail="market evidence · news tape" /><DiagramBox x={20} y={144} title="OBSERVE + FORECAST" detail="hashed snapshot · recorded distribution" /><DiagramBox x={20} y={236} title="AI ARGUES OR VETOES" detail="advisory only · cannot trade" />
        <DiagramBox x={430} y={144} title="DETERMINISTIC RISK GATE" detail="exact max loss · independent checks" accent /><text className="sd-boundary-label" x="420" y="122">DECISION BOUNDARY · CERTIFICATE REQUIRED</text><line className="sd-boundary" x1="420" y1="132" x2="730" y2="132" /><text className="sd-edge sd-edge-seal" x="580" y="236" textAnchor="middle">CERTIFICATE OR REFUSAL</text>
        <DiagramBox x={840} y={52} title="PAPER EXECUTION" detail="one defined-risk order" /><DiagramBox x={840} y={144} title="RECONCILE" detail="broker truth · halt on mismatch" /><DiagramBox x={840} y={236} title="PUBLIC CASE FILE" detail="read-only · replayable record" />
        <line className="sd-simple-arrow" x1="170" y1="124" x2="170" y2="138" markerEnd="url(#sd-head)" /><line className="sd-simple-arrow" x1="170" y1="216" x2="170" y2="230" markerEnd="url(#sd-head)" /><line className="sd-simple-arrow" x1="320" y1="272" x2="424" y2="180" markerEnd="url(#sd-head)" /><line className="sd-simple-arrow-seal" x1="730" y1="180" x2="834" y2="88" markerEnd="url(#sd-head-seal)" /><line className="sd-simple-arrow" x1="990" y1="124" x2="990" y2="138" markerEnd="url(#sd-head)" /><line className="sd-simple-arrow" x1="990" y1="216" x2="990" y2="230" markerEnd="url(#sd-head)" />
        <rect className="sd-simple-operator" x="430" y="300" width="300" height="56" rx="3" /><text className="sd-simple-title sd-title-seal" x="448" y="327">OPERATOR: STOP ONLY</text><text className="sd-simple-detail" x="448" y="346">pause · veto · emergency halt: never initiates</text>
      </svg>
      <ol className="system-stages">{STAGES.map((stage) => <li key={stage.index}><span className="system-stage-index">{stage.index}</span><div><p className="system-stage-event">{stage.event} <span>{stage.actor}</span></p><p className="system-stage-copy">{stage.copy}</p></div><p className="system-stage-crosses"><span>hands on</span>{stage.crosses}</p></li>)}</ol>
    </figure>
  )
}
