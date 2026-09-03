import { CaseQueue } from "../../../components/CaseQueue"

export default function CasesPage() {
  return <main className="console-cases-page" aria-labelledby="console-cases-title"><header className="console-page-heading"><p className="section-label">Synthetic workbench</p><h1 id="console-cases-title">Case queue</h1><p className="subpage-lede">Select an authored fixture or replay a completed browser-local run.</p></header><CaseQueue /></main>
}
