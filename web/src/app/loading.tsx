import { LoadingState } from "../components/LoadingState"

export default function Loading() {
  return (
    <>
      <LoadingState />
      <noscript>
        <main className="subpage-shell" aria-labelledby="no-script-landing-title">
          <p className="section-label">Lexguard</p>
          <h1 id="no-script-landing-title">AI argues. Risk decides.</h1>
          <p className="subpage-lede">The public record remains available without JavaScript.</p>
          <nav aria-label="No-script landing navigation" className="noscript-nav">
            <a href="#procedure">Due process of a trade</a>
            <a href="#powers">Separation of powers</a>
            <a href="#architecture">How the court is wired</a>
          </nav>
          {/* The streamed page arrives inside a hidden container without
              JavaScript, so this fallback carries the console routes itself
              under the same accessible name the live page uses. */}
          <nav aria-label="Console routes" className="noscript-nav">
            <a href="/command">Command center</a>
            <a href="/cases/current">Live case</a>
            <a href="/cases">Case archive</a>
            <a href="/research">Research gate</a>
            <a href="/console">Training room</a>
          </nav>
          <section id="procedure"><h2>Due process of a trade</h2></section>
          <section id="powers"><h2>Separation of powers</h2></section>
          <section id="architecture"><h2>How the court is wired</h2></section>
        </main>
      </noscript>
    </>
  )
}
