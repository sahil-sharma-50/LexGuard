"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { ConsoleHubTabs } from "./ConsoleHubTabs"
import { resolveConsoleRoute } from "../lib/console-routes"

const LANDING_SECTIONS = [
  { id: "hero", label: "Thesis" },
  { id: "problem", label: "Problem" },
  { id: "powers", label: "Powers" },
  { id: "architecture", label: "System" },
  { id: "procedure", label: "Procedure" },
] as const

function sectionHref(pathname: string, sectionId: string): string {
  return pathname === "/" ? `#${sectionId}` : `/#${sectionId}`
}

/**
 * The shared filing header.
 *
 * On the landing it carries the section index plus a single link into the
 * console. On every console-family route it carries the console tab bar and a
 * way back to the landing instead: the routes are always visible rather than
 * hidden behind a menu.
 */
export function SiteHeader() {
  const pathname = usePathname() ?? "/"
  const inConsole = resolveConsoleRoute(pathname) !== null

  // On the landing the wordmark is a scroll-to-top control; elsewhere it is a
  // link home, and navigation lands at the top of the page on its own.
  const returnToTop = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (pathname !== "/") return
    event.preventDefault()
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" })
  }

  return (
    <header className={inConsole ? "masthead masthead--console" : "masthead"}>
      <div className="masthead-brand">
        <Link
          className="masthead-wordmark"
          href="/"
          prefetch={false}
          onClick={returnToTop}
          aria-label={pathname === "/" ? "Lexguard: back to top" : "Lexguard home"}
        >
          Lex<span className="wordmark-accent">guard</span>
        </Link>
        {inConsole ? <span className="masthead-console-label">Console</span> : null}
      </div>

      {!inConsole && (
        <nav className="masthead-sections" aria-label="Page sections">
          {LANDING_SECTIONS.map((section) => (
            <a key={section.id} className="masthead-section-link" href={sectionHref(pathname, section.id)}>
              {section.label}
            </a>
          ))}
        </nav>
        )}

      {inConsole ? (
        <Link className="masthead-exit" href="/" prefetch={false}>
          ← Landing
        </Link>
      ) : (
        <Link className="masthead-console-link" href="/command" prefetch={false}>
          Open console
        </Link>
      )}

      {inConsole ? <ConsoleHubTabs /> : null}
    </header>
  )
}
