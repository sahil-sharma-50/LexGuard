import Link from "next/link"
import { Reveal } from "../components/Reveal"
import { SessionDocket } from "../components/SessionDocket"
import { SystemDiagram } from "../components/SystemDiagram"
import { SiteHeader } from "../components/SiteHeader"

const PROCEDURE = [
  {
    index: "01",
    event: "OBSERVED",
    holder: "Instruments",
    copy: "Market evidence is sealed: quotes, chains, and the news tape are snapshotted and content-hashed before anyone argues.",
  },
  {
    index: "02",
    event: "FORECASTED",
    holder: "Quant model",
    copy: "A distribution over close-to-close returns is recorded as an artifact: a testable claim, not a vibe.",
  },
  {
    index: "03",
    event: "ARGUED",
    holder: "The advocate",
    copy: "The LLM files its catalyst assessment: scenario, confidence, verbatim rationale, and the news IDs it cites. It may also refuse.",
  },
  {
    index: "04",
    event: "CERTIFIED / REFUSED",
    holder: "The risk gate",
    copy: "Deterministic code rules on the argument. Only a certificate (max loss, robust EV, expiry) authorizes an order. No certificate, no trade.",
  },
  {
    index: "05",
    event: "SUBMITTED / FILLED",
    holder: "Alpaca paper",
    copy: "A four-leg iron condor on SPY, QQQ, or IWM goes to the paper broker via MCP. Order IDs and fills are recorded as broker truth.",
  },
  {
    index: "06",
    event: "RECONCILED / CLOSED",
    holder: "The ledger",
    copy: "Positions are managed to close and every divergence between ledger and broker halts the court until it is explained.",
  },
] as const

const POWERS = [
  {
    index: "01",
    title: "The advocate",
    role: "LLM · argues the case",
    grants: [
      "Files catalyst assessments with scenario, confidence, verbatim rationale, and cited news IDs.",
      "May refuse when the evidence carries no defensible edge.",
    ],
    limit: "Cannot size, price, submit, or cancel an order.",
  },
  {
    index: "02",
    title: "The risk gate",
    role: "Deterministic code · decides",
    grants: [
      "Certifies condor structures against a versioned risk constitution: max loss, robust EV, expiry.",
      "Executes and manages under a $4,000 competition drawdown cap.",
    ],
    limit: "Cannot be argued past. No certificate, no order.",
  },
  {
    index: "03",
    title: "The operator",
    role: "Human · stop-only",
    grants: [
      "Pause, resume, emergency stop: service-level brakes behind an operator token.",
      "Per-case veto while a case still awaits its certificate.",
    ],
    limit: "Can never initiate, edit, or force a trade.",
  },
] as const

export default function HomePage() {
  return (
    <main id="main-content" className="landing-shell">
      <a className="skip-link" href="#hero">
        Skip to the thesis
      </a>
      <SiteHeader />
      <section className="hero" id="hero" aria-labelledby="hero-title">
        <div className="hero-grid">
          <div className="hero-rail">
            <h1 id="hero-title">
              AI argues. <em>Risk decides.</em>
            </h1>
            <p className="landing-lede">
              Lexguard is an autonomous options-trading agent with a constitution. An LLM advocate may
              argue a scenario or refuse; nothing else. <strong>Deterministic risk code holds the gavel:</strong> it
              alone certifies and executes defined-risk iron condors on SPY, QQQ, and IWM.
            </p>
            <div className="landing-actions">
              <Link className="landing-primary-action" href="/command" prefetch={false}>
                Enter the command center
              </Link>
              <Link className="landing-secondary-action" href="/cases/current" prefetch={false}>
                Follow the live case
              </Link>
            </div>
          </div>

          <div className="hero-stub">
            <SessionDocket title="Session docket" />
          </div>
        </div>
        <div className="stats-strip">
          <div>
            <strong>4 windows</strong>
            <span>10:05 · 11:35 · 13:05 · 14:20 ET</span>
          </div>
          <div>
            <strong>3 tickers</strong>
            <span>SPY · QQQ · IWM</span>
          </div>
          <div>
            <strong>$4,000</strong>
            <span>drawdown cap, enforced in code</span>
          </div>
          <div>
            <strong>Stop-only</strong>
            <span>human powers: pause · veto · halt</span>
          </div>
        </div>
      </section>

      <Reveal>
        <section className="landing-section" id="problem" aria-labelledby="problem-title">
          <div className="chapter-heading">
            <span className="chapter-index">01</span>
            <p className="section-label">The problem</p>
          </div>
          <h2 id="problem-title">Autonomy is easy. Accountability is not.</h2>
          <p className="landing-section-lede">
            Letting a language model trade is a one-line prompt. Knowing why it traded, what it was forbidden to
            do, and which safeguard held is the hard part. Lexguard splits the powers so every decision
            leaves a court record instead of a chat log.
          </p>
          <div className="compare-grid">
            <div className="compare-panel">
              <span className="compare-tag">The usual agent</span>
              <h3>One model holds every power</h3>
              <p>
                It reads the market, picks the strikes, sizes the position, and sends the order. When it loses,
                the only artifact is a transcript, and nobody can say which power failed.
              </p>
            </div>
            <div className="compare-panel compare-panel-accent">
              <span className="compare-tag">Lexguard</span>
              <h3>The advocate argues; the gate rules</h3>
              <p>
                The LLM may only argue a catalyst scenario or refuse. Deterministic code certifies structure,
                size, and price against a versioned risk constitution, and only a certificate can reach the
                paper broker.
              </p>
            </div>
          </div>
        </section>
      </Reveal>

      <Reveal>
        <section className="landing-section" id="powers" aria-labelledby="powers-title">
          <div className="chapter-heading">
            <span className="chapter-index">02</span>
            <p className="section-label">The constitution</p>
          </div>
          <h2 id="powers-title">Separation of powers</h2>
          <p className="landing-section-lede">
            The interesting part is not that an AI trades; it is what the AI is forbidden to do. Three parties,
            three non-overlapping powers.
          </p>
          <ol className="powers-stack">
            {POWERS.map((power) => (
              <li key={power.index} className="power-row">
                <span className="power-index">{power.index}</span>
                <div className="power-body">
                  <h3>{power.title}</h3>
                  <p className="power-role">{power.role}</p>
                  <ul>{power.grants.map((grant) => <li key={grant}>{grant}</li>)}</ul>
                  <p className="power-limit">{power.limit}</p>
                </div>
              </li>
            ))}
          </ol>
          <aside className="standing-orders powers-orders" aria-label="Standing orders">
            <h3>Standing orders</h3>
            <ol>
              <li><span>I.</span><p><strong>The advocate may argue or refuse.</strong> It cannot size, submit, or touch an order.</p></li>
              <li><span>II.</span><p><strong>Only a risk certificate authorizes a trade:</strong> deterministic, versioned, and expiring.</p></li>
              <li><span>III.</span><p><strong>The operator can only stop.</strong> Pause, veto, emergency stop; never initiate.</p></li>
            </ol>
          </aside>
        </section>
      </Reveal>

      <Reveal>
        <section className="landing-section" id="architecture" aria-labelledby="architecture-title">
          <div className="chapter-heading">
            <span className="chapter-index">03</span>
            <p className="section-label">The machine</p>
          </div>
          <h2 id="architecture-title">How the court is wired</h2>
          <p className="landing-section-lede">
            One schematic of the whole system: where evidence enters, what the model is allowed to say, which
            component alone can send an order, and how broker truth comes back into a hash-chained ledger that
            this site only ever reads.
          </p>
          <SystemDiagram />
        </section>
      </Reveal>

      <Reveal>
        <section className="landing-section" id="procedure" aria-labelledby="procedure-title">
          <div className="chapter-heading">
            <span className="chapter-index">04</span>
            <p className="section-label">The record</p>
          </div>
          <h2 id="procedure-title">Due process of a trade</h2>
          <p className="landing-section-lede">
            Every case moves through the same ledger events, in the same order, with the same artifacts. The
            sequence below is the court&rsquo;s procedure: not a diagram of intentions, but the event types you
            will see replayed in the command center feed.
          </p>
          <ol className="flow-grid procedure-list">
            {PROCEDURE.map((step) => (
              <li className="flow-card" key={step.event}>
                <div className="flow-card-head">
                  <span className="flow-index">{step.index}</span>
                  <span className="flow-actor">{step.holder}</span>
                </div>
                <div>
                  <span className="procedure-event">{step.event}</span>
                  <p>{step.copy}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      </Reveal>

      <Reveal>
        <section className="landing-final" aria-labelledby="final-title">
          <h2 id="final-title">Review the record.</h2>
          <div>
            <p>
              Follow the evidence, read the risk ruling, and inspect the paper-broker result. Every action,
              refusal, and safety stop remains on the record.
            </p>
            <div className="landing-actions">
              <Link className="landing-primary-action" href="/command" prefetch={false}>
                Enter the command center
              </Link>
              <Link className="landing-secondary-action" href="/cases" prefetch={false}>
                Browse the case archive
              </Link>
            </div>
          </div>
        </section>
      </Reveal>
      <footer className="landing-footer">
        <span>Lexguard · Alpaca · LabLab</span>
        <span>Paper endpoint only · no live-money controls</span>
      </footer>
    </main>
  )
}
