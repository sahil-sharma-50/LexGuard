import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import HomePage from "../src/app/page"

function renderHome() {
  return render(<HomePage />)
}

describe("landing page (Night Bench)", () => {
  it("communicates the thesis and routes to the command center and live case", () => {
    renderHome()

    expect(screen.getByRole("heading", { name: /AI argues\.\s*Risk decides\./ })).toBeVisible()
    expect(screen.getAllByRole("link", { name: "Enter the command center" })[0]).toHaveAttribute("href", "/command")
    expect(screen.getByRole("link", { name: "Follow the live case" })).toHaveAttribute("href", "/cases/current")

    const sectionNav = screen.getByRole("navigation", { name: "Page sections" })
    expect(sectionNav).toBeVisible()
    expect(within(sectionNav).getByRole("link", { name: "Procedure" })).toHaveAttribute("href", "#procedure")

      expect(screen.getByRole("link", { name: "Open console" })).toHaveAttribute("href", "/command")
  })

  it("keeps the hero free of the state instrument, which belongs to the console", () => {
    renderHome()

    expect(screen.queryByRole("heading", { name: "Calibration instrument" })).not.toBeInTheDocument()
    expect(screen.queryByText("ABSTAIN · CLOSED")).not.toBeInTheDocument()
  })

  it("shows the system schematic with the authority boundary named in text", () => {
    renderHome()

    expect(screen.getByRole("heading", { name: "How the court is wired" })).toBeVisible()
    expect(screen.getByRole("img", { name: /Three-part Lexguard decision flow/ })).toBeInTheDocument()
    // The drawing is never the only carrier: each stage is also a text row.
    for (const stage of ["OBSERVE", "FORECAST", "ARGUE", "CERTIFY", "EXECUTE", "VERIFY"]) {
      expect(screen.getAllByText(stage, { exact: false }).length).toBeGreaterThan(0)
    }
    expect(screen.getAllByText(/advisory only/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/One tamper-evident certificate, or nothing/i)).toBeInTheDocument()
  })

  it("routes into the console from the masthead", () => {
    renderHome()

    expect(screen.getByRole("link", { name: "Open console" })).toHaveAttribute("href", "/command")
  })

  it("puts the constitution before the system record and credits its partners", () => {
    renderHome()

    const constitution = screen.getByRole("heading", { name: "Separation of powers" })
    const system = screen.getByRole("heading", { name: "How the court is wired" })
    expect(constitution.compareDocumentPosition(system) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Review the record." })).toBeVisible()
    expect(screen.queryByRole("img", { name: /Seal of the court/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/Every console route is a read-only projection/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Lexguard · Alpaca · LabLab/i)).toBeVisible()
  })

  it("renders the session docket with the four fixed decision windows", () => {
    renderHome()

    const docket = screen.getByRole("complementary", { name: "Session docket" })
    for (const window of ["10:05", "11:35", "13:05", "14:20"]) {
      expect(docket).toHaveTextContent(window)
    }
    expect(docket).toHaveTextContent(/SPY · QQQ · IWM/)
  })

  it("keeps the authored court procedure in ledger-event order", () => {
    renderHome()

    const events = ["OBSERVED", "FORECASTED", "ARGUED", "CERTIFIED / REFUSED", "SUBMITTED / FILLED", "RECONCILED / CLOSED"]
      .map((name) => screen.getByText(name, { exact: true }))
    for (let index = 1; index < events.length; index += 1) {
      expect(events[index - 1].compareDocumentPosition(events[index]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
  })

  it("states the separation of powers, including stop-only human control", () => {
    renderHome()

    expect(screen.getByRole("heading", { name: "Separation of powers" })).toBeVisible()
    expect(screen.getByRole("heading", { name: "The advocate" })).toBeVisible()
    expect(screen.getByRole("heading", { name: "The risk gate" })).toBeVisible()
    expect(screen.getByRole("heading", { name: "The operator" })).toBeVisible()
    expect(screen.getByText(/Cannot size, price, submit, or cancel an order\./)).toBeVisible()
    expect(screen.getByText(/Can never initiate, edit, or force a trade\./)).toBeVisible()
  })

  it("keeps the standing orders as the constitutional summary", () => {
    renderHome()

    const orders = screen.getByRole("complementary", { name: "Standing orders" })
    expect(orders).toHaveTextContent(/The advocate may argue or refuse\./)
    expect(orders).toHaveTextContent(/Only a risk certificate authorizes a trade/)
    expect(orders).toHaveTextContent(/The operator can only stop\./)
  })

  it("does not imply unsupported proof or commercial outcomes", () => {
    renderHome()

    const narrative = document.body.textContent ?? ""
    expect(narrative).not.toMatch(/customer|testimonial|deployment|completed research/i)
    expect(narrative).not.toMatch(/guaranteed|profit guarantee/i)
    expect(narrative).toMatch(/paper endpoint/i)
    expect(narrative).toMatch(/no live-money controls/i)
  })

  it("keeps training-room disclosure out of the landing footer", () => {
    renderHome()

    expect(screen.queryByRole("link", { name: "training room" })).not.toBeInTheDocument()
    expect(screen.queryByText(/synthetic replay in your browser, no market data, no broker calls/i)).not.toBeInTheDocument()
  })

  it("keeps the landing hero and system figure free of redundant explanatory notes", () => {
    renderHome()

    expect(screen.queryByText(/Paper endpoint only\. The command center shows live equity/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/The simple flow makes the authority boundary explicit/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/AI ARGuES\. RISK DECIDES\. EVERY EVENT ENTERS THE RECORD\./i)).not.toBeInTheDocument()
  })
})
