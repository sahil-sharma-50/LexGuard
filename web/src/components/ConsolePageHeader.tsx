import type { ReactNode } from "react"

export function ConsolePageHeader({ title, description, children }: {
  title: string
  description: string
  children?: ReactNode
}) {
  return (
    <header className="console-page-heading">
      <div>
        <h1>{title}</h1>
        <p className="subpage-lede">{description}</p>
      </div>
      {children ? <div className="console-page-heading-meta">{children}</div> : null}
    </header>
  )
}
