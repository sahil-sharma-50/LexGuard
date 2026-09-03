import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, resolve } from "node:path"
import { describe, expect, it } from "vitest"

const simulatorRoot = resolve(process.cwd(), "src/lib/simulator")
const forbidden = /\bapi\b|LiveCaseUpdates|\bfetch\b|XMLHttpRequest|EventSource|sendBeacon|NEXT_PUBLIC_API_BASE_URL|\/api\/|\bbroker\b|\badapter\b/i

function hasForbiddenBoundary(source: string): boolean {
  const imports = source.match(/^\s*import\b[\s\S]*?(?:\bfrom\s+)?["'][^"']+["'];?/gm)?.join("\n") ?? ""
  const executableBoundary = /\bfetch\s*\(|\bXMLHttpRequest\b|\bEventSource\b|\bsendBeacon\s*\(|\bimport\s*\(|\brequire\s*\(|\/api\//i
  return forbidden.test(imports) || executableBoundary.test(source)
}

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry)
    return statSync(path).isDirectory() ? sourceFiles(path) : path.endsWith(".ts") || path.endsWith(".tsx") ? [path] : []
  })
}

describe("simulator import boundary", () => {
  it("keeps the simulator independent of network and broker adapters", () => {
    const provider = resolve(process.cwd(), "src/components/SimulatorProvider.tsx")
    const files = [...sourceFiles(simulatorRoot)]
    try {
      if (statSync(provider).isFile()) files.push(provider)
    } catch {
      // Task 5 adds the provider; the boundary still covers the simulator in Task 4.
    }
    for (const file of files) {
      const contents = readFileSync(file, "utf8")
      // Domain labels such as broker_unknown are part of the local state model.
      // The boundary applies to module dependencies and executable global calls.
      expect(hasForbiddenBoundary(contents), file).toBe(false)
    }
  })

  it.each([
    "fetch('/api/demo')",
    "new XMLHttpRequest()",
    "new EventSource('/events')",
    "navigator.sendBeacon('/api/demo', body)",
    "import('./api')",
    "require('./adapter')",
  ])("catches executable boundary %s", (source) => {
    expect(hasForbiddenBoundary(source)).toBe(true)
  })

  it("does not mistake a legitimate local lifecycle label for a boundary", () => {
    expect(hasForbiddenBoundary('const lifecycle = "broker_unknown"')).toBe(false)
  })
})
