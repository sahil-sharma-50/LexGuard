---
name: Lexguard
description: AI argues. Risk decides. A filed court record for autonomous options decisions, printed on warm bond paper.
colors:
  paper: "#f4f0e9"
  paper2: "#ece7de"
  paper3: "#e0dad0"
  sheet: "#fbf9f5"
  ink: "#2a231a"
  textSoft: "#595044"
  textFaint: "#6b6153"
  lineFaint: "#d8d1c5"
  line: "#c4bcae"
  lineStrong: "#9c9384"
  accent: "#96233a"
  accentStrong: "#7f1c31"
  accentSubtle: "#f0dcdd"
  accentInk: "#fbf9f5"
  success: "#1f6b45"
  danger: "#96233a"
  warning: "#7d5312"
  info: "#23507f"
typography:
  display:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(2.9rem, 6.6vw, 5.4rem)"
    fontWeight: 800
    lineHeight: 0.94
    letterSpacing: "-0.045em"
  headline:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(1.9rem, 3.8vw, 3rem)"
    fontWeight: 800
    lineHeight: 1.04
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.08rem"
    fontWeight: 800
    lineHeight: 1.04
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Archivo, Helvetica Neue, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.62
  kicker:
    fontFamily: "Azeret Mono, ui-monospace, monospace"
    fontSize: "0.655rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.17em"
  data:
    fontFamily: "Azeret Mono, ui-monospace, monospace"
    fontSize: "0.585rem–0.72rem"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "0.06em–0.13em"
rounded:
  sm: ".125rem"
  md: ".1875rem"
  lg: ".25rem"
  xl: ".3125rem"
spacing:
  panel: "20px 22px"
  gap: "18px"
  section: "clamp(56px, 7vw, 100px)"
motion:
  ease: "cubic-bezier(.22, 1, .36, 1)"
  duration: ".22s"
  durationFast: ".14s"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accentInk}"
    typography: "{typography.data} at 0.715rem, weight 700, uppercase"
    rounded: "{rounded.sm}"
    height: "46px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    border: "1px solid {colors.ink}"
    rounded: "{rounded.sm}"
    height: "46px"
    hover: "inverts to ink fill, sheet text"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.danger}"
    border: "1px solid {colors.danger}"
    rounded: "{rounded.sm}"
    height: "44px"
  panel:
    backgroundColor: "{colors.sheet}"
    border: "1px solid {colors.line}"
    rounded: "{rounded.sm}"
    head: "first .section-heading becomes a full-bleed {colors.paper2} strip with a 1px ink underline"
  chip:
    backgroundColor: "{colors.sheet}"
    border: "1px solid {colors.line}"
    rounded: "{rounded.sm}"
    typography: "{typography.data}"
---

# Design System: Lexguard

> The product was renamed from Volatility Court to Lexguard. The courtroom domain
> language (court, docket, verdict, certificate) is deliberate and stays.

## Overview

**Creative North Star: "Court Record"**

Lexguard reads as a document that was filed, not an app that was launched: warm bond paper, one oxblood seal, hairline rules, running heads, marginalia, leader dots, tabular figures. Archivo carries every authored word in heavy, tightly-tracked cuts; Azeret Mono is the clerk that sets the machine record. The landing is a filed brief. The command center, training room, and case files are ledger forms printed on the same paper: each panel carries a tinted head strip, tables zebra-rule, every figure is monospace and tabular.

The system is one global stylesheet (`web/src/app/globals.css`) of semantic classes over CSS custom properties. No Tailwind, no CSS-in-JS, no animation library.

**Key characteristics:**
- Light warm paper `#f4f0e9` with a near-white `#fbf9f5` sheet for panels; corners are near-square (2–5px) and there are no decorative shadows.
- One committed oxblood accent `#96233a`; green, blue, and ochre only report state, always beside a text label.
- Print grammar instead of cards: ruled procedure tables, three-column powers with vertical hairlines, a hand-drawn system schematic on filed paper.
- Command surfaces are ledger forms: head-strip panels, zebra rows, mono figures, thin ruled meters.
- Deliberately not the category reflex. No dark terminal, no navy-and-gold, no neon; a light filing surface is the point, and it survives a judge reading it in a bright room beside a dozen other tabs.

## Colors

### Semantic jobs

- **Seal `#96233a` / `#7f1c31`**: brand accent, primary action, argument, active route, focus ring, refusal and veto.
- **Green `#1f6b45`**: certified, verified, filled, gains, connected.
- **Blue `#23507f`**: observed evidence, live/in-flight order state, info.
- **Ochre `#7d5312`**: pending, warning, not-evaluated.
- **Paper stack**: paper `#f4f0e9` (canvas), paper-2 `#ece7de` (head strips, tinted rows), paper-3 `#e0dad0` (meter tracks, bar fills), sheet `#fbf9f5` (panels, inputs).
- **Ink**: ink `#2a231a`, soft `#595044`, faint/ghost `#6b6153`; rules `#d8d1c5` / `#c4bcae` / `#9c9384`.

### Named rules

**The Seal Rule.** The seal is the only colour allowed to advertise. Green, blue, and ochre may only report state, and every state colour is paired with a text label so colour is never the sole carrier.

**The Contrast Floor.** All copy, including faint mono annotations, stays at or above 4.5:1 against *its own* surface, including the paper-2 head strips (`--text-faint` is tuned to clear 4.5:1 there, not just on paper). The e2e suite enforces this with axe plus computed-contrast gates on body, `.landing-lede`, `.section-label`, `.landing-primary-action`, `h1`, the focus ring, and the primary action border.

## Typography

**Display + body:** Archivo (variable, via `next/font/google`, `--font-sans`; `--font-display` aliases it).
**Record:** Azeret Mono (`--font-mono`) for kickers, indices, statuses, IDs, provenance, timestamps, button and control labels.

- **Display** (800, `clamp(2.9rem, 6.6vw, 5.4rem)`, `.94`, `-.045em`): the hero thesis; the accent phrase sits on its own line in seal.
- **Headline** (800, `clamp(1.9rem, 3.8vw, 3rem)`): chapter and route headings.
- **Title** (800, `1.08rem`): panel headings.
- **Body** (400, 16px, 1.62): reading copy, 58–70ch.
- **Kicker** (mono 600, `.655rem`, `.17em`, uppercase, seal): section labels; landing chapters pair it with a `1.05rem` mono seal index (`01`) above a full-width ink rule.
- **Data** (mono, `.585–.72rem`, uppercase where status-like): machine record only, never prose. Buttons are mono uppercase: they are instruments, not sentences.

Numerals are tabular globally (`font-variant-numeric: tabular-nums`) so ledger columns align.

## Layout

The landing shell is a 1280px centred column (56px gutters). **Every console-family shell shares one geometry: 1400px, 48px gutters, `--shell-max: 1400px`,** so the masthead, tab bar, and content column never shift when a tab changes; subpages keep their reading measure with a 960px content column inside that shell rather than a narrower shell. The masthead is a sticky full-bleed paper bar with a 1px ink underline, achieved with `margin-inline: calc(50% - 50vw)` plus shell-aware padding.

The landing is a filed brief: a two-column hero (left rail argues, right stub carries the engraved seal and the session docket), a facts strip ruled top and bottom, then numbered parts 01–04 (problem as two ruled columns with the court's side tinted seal-subtle; the system schematic; procedure as a ruled six-row table; powers as three hairline-divided columns each ending in a seal limit line), a closing call under a double rule, and a footnote naming the training room as synthetic.

Command keeps the 1.85fr/1fr main/rail grid with a sticky rail; case files keep the verdict banner plus evidence grids. All interactive targets stay at 44px minimum (landing actions 46px).

## Elevation & Depth

There is no elevation. Structure comes from hairline rules, tinted head strips, and the paper/sheet tone difference. `--shadow-sm` and `--shadow-md` are deliberately `none`; only the modal dialog gets a soft ink shadow so it reads as lifted off the page. No glass, no gradients as decoration, no texture.

## Shapes

Radius scale `.125 / .1875 / .25 / .3125rem`: everything is near-square, because print forms are. Chips, badges, and status pills are square-cornered too; the only circles are the engraved seal and the instrument's stage nodes.

## Components

- **Buttons:** mono uppercase labels, 1px ink border, square corners, 44–46px. Primary: seal fill, sheet text. Secondary: transparent, inverts to ink fill on hover. Danger: seal outline, seal-subtle fill on hover.
- **Panel:** sheet surface, hairline border; the first `.section-heading` becomes a full-bleed paper-2 head strip with an ink underline. Used by command panels, case-file `.section-block`, the calibration instrument, and console blocks.
- **Figure tile (`.stat-tile`):** mono label over a hairline, mono figure at `clamp(1.2rem, 1.8vw, 1.5rem)`, note beneath; the drawdown meter is a 7px ruled track filled green/ochre/seal by proximity to the $4,000 cap.
- **Ledger table:** mono uppercase head with an ink underline, zebra `paper` rows, tabular mono cells, first column in ink.
- **Register feed:** three-column rows (kind · detail · time), zebra-ruled, kind coloured by event class and always spelled out.
- **Verdict stamp:** mono 700 uppercase inside a 2px square frame; green certified, seal abstain, red halted.
- **The bench:** a form to be countersigned. Password token field on paper, stacked full-width mono controls, feedback slips tinted by outcome. No submit control exists anywhere.
- **Confirmation dialog:** sheet panel on an ink scrim, real modal semantics (inert background, Escape, focus return), synthetic/browser-local copy.
- **Wordmark:** `Lex` in ink, `guard` in seal, set tight with no gap so it reads as one word; the engraved seal carries an `LG` monogram.
- **System schematic (`.system-diagram`):** an SVG filed on a sheet, with a seal dashed decision boundary; below ~900px it is replaced by the ruled stage list, which is present at every width so the drawing is never the only carrier.
- **Masthead:** on the landing it carries the section index and a single `Open console` link; on every console route it swaps to the console tab bar plus `← Landing`. There is no dropdown: the routes are always visible, since a collapsed `<details>` is invisible to role queries and to keyboard users. The wordmark scrolls to top when you are already on the page.
- **Console tab bar (`.console-hub-tabs`):** six mono uppercase tabs inside the masthead, active route underlined in seal, horizontally scrollable under 1000px.
- **No-script fallback:** `app/loading.tsx` carries ruled section and `Console routes` navigations, because the streamed page arrives inside a hidden container without JavaScript.

## Motion

`cubic-bezier(.22, 1, .36, 1)` everywhere; 140–220ms for hovers and state, ~640ms for entrances. One staggered hero entrance (`docket-rise`) covering the rail, stub, and facts strip; scroll reveals via a JS-gated `.reveal` class (IntersectionObserver adds `.is-visible`; no JS or reduced motion means content is simply visible); the calibration `trace-reveal` draw; a `feed-arrive` tint on the newest event. `prefers-reduced-motion: reduce` collapses all animation to .01ms and shows the full trace statically.

## Do's and Don'ts

### Do:
- **Do** lead with evidence → argument → deterministic risk gate → broker truth, in that order.
- **Do** pair every state colour with a text label and name `NOT RUN`, `UNKNOWN`, `NOT AVAILABLE` honestly.
- **Do** keep the facts strip and any figures verifiable; no invented performance.
- **Do** check new faint text against paper-2, not just paper; the head strips are the tightest surface.
- **Do** preserve static reading order, keyboard focus (2px seal ring), 44px targets, and reduced-motion parity.
- **Do** keep every route reachable from a *visible* nav; collapsed menus do not count for keyboard or assistive-technology users.
- **Do** keep every console route on the shared shell geometry, so switching tabs never moves the chrome or the content column.

### Don't:
- **Don't** use the seal to report state, or green/blue/ochre to decorate.
- **Don't** set prose in Azeret Mono, or headings below 800 weight.
- **Don't** add gradient text, glassmorphism, side-stripe borders, drop shadows on panels, or rounded pill chips.
- **Don't** reach for cards: the default answer here is a ruled table, a hairline-divided column, or nothing.
- **Don't** let copy imply live-money controls, credentials, or unverified research.
- **Don't** reintroduce the previous dark canvas or the amber accent; `--accent` is the seal, and no `--amber` token exists.
