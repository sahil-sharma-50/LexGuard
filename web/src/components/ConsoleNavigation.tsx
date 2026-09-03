"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

export function ConsoleNavigation() {
  const currentPath = usePathname() ?? undefined
  const links = [
    { href: "/console", label: "Operations overview", match: "/console" },
    { href: "/console/decision-room", label: "Decision room", match: "/console/decision-room" },
    { href: "/console/cases", label: "Case queue", match: "/console/cases" },
  ] as const

  return (
    <nav aria-label="Console navigation">
      {links.map((link) => {
        const active = currentPath === link.match || (link.match !== "/console" && currentPath?.startsWith(`${link.match}/`))
        return (
          <Link key={link.href} href={link.href} prefetch={false} aria-current={active ? "page" : undefined}>
            {link.label}
          </Link>
        )
      })}
    </nav>
  )
}
