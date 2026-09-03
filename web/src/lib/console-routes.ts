export const CONSOLE_HUB_ROUTES = [
  { href: "/command", label: "Command center" },
  { href: "/cases/current", label: "Live case" },
  { href: "/cases", label: "Case archive" },
  { href: "/research", label: "Research" },
] as const

export type ConsoleHubRoute = (typeof CONSOLE_HUB_ROUTES)[number]

export function resolveConsoleRoute(pathname: string): string | null {
  if (pathname.startsWith("/console")) return "/console"
  if (pathname === "/cases/current") return "/cases/current"
  if (pathname.startsWith("/cases")) return "/cases"
  if (pathname === "/command") return "/command"
  if (pathname === "/research") return "/research"
  return null
}
