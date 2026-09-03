"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { CONSOLE_HUB_ROUTES, resolveConsoleRoute } from "../lib/console-routes"

export function ConsoleHubTabs() {
  const pathname = usePathname() ?? "/"
  const activeRoute = resolveConsoleRoute(pathname)

  return (
    <nav className="console-hub-tabs" aria-label="Console routes">
      {CONSOLE_HUB_ROUTES.map((route) => (
        <Link
          key={route.href}
          href={route.href}
          className={"quiet" in route && route.quiet ? "nav-quiet" : undefined}
          // The Training Room promises no network traffic. RSC prefetching
          // would break that promise before the operator navigates anywhere.
          prefetch={false}
          aria-current={activeRoute === route.href ? "page" : undefined}
        >
          {route.label}
        </Link>
      ))}
    </nav>
  )
}
