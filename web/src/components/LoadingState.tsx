export function LoadingState({ label = "case file" }: { label?: string }) {
  const message = `Loading ${label}…`
  return (
    <main className="subpage-shell loading-state" aria-busy="true" aria-live="polite">
      <p className="section-label">Lexguard</p>
      <h1>Loading</h1>
      <p className="subpage-lede" role="status" aria-label={message}>{message}</p>
    </main>
  )
}
