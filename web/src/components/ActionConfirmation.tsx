"use client"

import { createPortal } from "react-dom"
import { useEffect, useId, useRef } from "react"
import type { DemoActionType } from "../lib/simulator/types"

interface ActionCopy {
  label: string
  result: string
}

const ACTION_COPY: Partial<Record<DemoActionType, ActionCopy>> = {
  APPROVE_PROPOSAL: {
    label: "Approve proposal",
    result: "move the run to certified and issue the deterministic certificate",
  },
  VETO_PROPOSAL: {
    label: "Veto proposal",
    result: "record an abstention with no certificate or simulated order",
  },
  CLOSE_POSITION: {
    label: "Close position",
    result: "request a synthetic position close; no P&L claim will be recorded",
  },
  EMERGENCY_STOP: {
    label: "Emergency stop",
    result: "activate the stop and disable new entry while safe close and reset remain available",
  },
  RESET_SCENARIO: {
    label: "Reset demo",
    result: "clear the active run and run history and return to the authored observing seed",
  },
}

export interface ActionConfirmationProps {
  open: boolean
  action?: DemoActionType
  actionLabel?: string
  title?: string
  description?: string
  onConfirm: () => void
  onCancel: () => void
  invokingElement?: HTMLElement | null
}

export function ActionConfirmation({
  open,
  action = "APPROVE_PROPOSAL",
  actionLabel,
  title,
  description,
  onConfirm,
  onCancel,
  invokingElement = null,
}: ActionConfirmationProps) {
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef<HTMLElement>(null)
  const restoreFocusRef = useRef<HTMLElement | null>(null)
  const previousInertRef = useRef<Map<HTMLElement, boolean> | null>(null)
  const onConfirmRef = useRef(onConfirm)
  const onCancelRef = useRef(onCancel)
  onConfirmRef.current = onConfirm
  onCancelRef.current = onCancel

  const copy = ACTION_COPY[action] ?? {
    label: action.replaceAll("_", " ").toLowerCase(),
    result: "apply the selected action to the synthetic browser-local scenario",
  }
  const resolvedLabel = actionLabel ?? copy.label
  const resolvedTitle = title ?? resolvedLabel
  const resolvedDescription = description ?? (action === "RESET_SCENARIO"
    ? "This action changes only the synthetic and browser-local scenario. The active run and run history will be cleared, returning to the authored observing seed."
    : `This action changes only the synthetic and browser-local scenario. It will ${copy.result}.`)

  useEffect(() => {
    if (!open || typeof document === "undefined") return

    const active = document.activeElement
    restoreFocusRef.current = invokingElement ?? (active instanceof HTMLElement ? active : null)

    const markedBackgrounds = Array.from(document.querySelectorAll<HTMLElement>("[data-simulator-background]"))
    const backgrounds = markedBackgrounds.length > 0
      ? markedBackgrounds
      : Array.from(document.body.children).filter((element) => !element.hasAttribute("data-dialog-backdrop")) as HTMLElement[]
    previousInertRef.current = new Map(backgrounds.map((element) => [element, element.inert === true]))
    backgrounds.forEach((element) => {
      element.inert = true
    })

    const focusable = getFocusable(dialogRef.current)
    ;(focusable[0] ?? dialogRef.current)?.focus()
    document.addEventListener("keydown", handleKeyDown)

    return () => {
      document.removeEventListener("keydown", handleKeyDown)
      previousInertRef.current?.forEach((wasInert, element) => {
        element.inert = wasInert
      })
      previousInertRef.current = null

      const target = restoreFocusRef.current
      restoreFocusRef.current = null
      if (canReceiveFocus(target)) {
        target.focus()
      } else {
        document.querySelector<HTMLElement>("[data-dialog-focus-fallback]")?.focus()
      }
    }
  }, [open, invokingElement])

  if (!open) return null

  const dialog = (
    <div className="dialog-backdrop" data-dialog-backdrop>
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
      >
        <h2 id={titleId}>{resolvedTitle}</h2>
        <p id={descriptionId}>{resolvedDescription}</p>
        <div className="dialog-actions">
          <button className="dialog-action-cancel" type="button" onClick={() => onCancelRef.current()}>Cancel</button>
          <button className="dialog-action-confirm" type="button" onClick={() => onConfirmRef.current()}>Confirm {resolvedLabel}</button>
        </div>
      </section>
    </div>
  )

  return typeof document === "undefined" ? dialog : createPortal(dialog, document.body)

  function handleKeyDown(event: globalThis.KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault()
      onCancelRef.current()
      return
    }

    if (event.key !== "Tab") return

    const focusable = getFocusable(dialogRef.current)
    if (focusable.length === 0) {
      event.preventDefault()
      dialogRef.current?.focus()
      return
    }

    const current = document.activeElement
    const currentIndex = focusable.indexOf(current as HTMLElement)
    const nextIndex = event.shiftKey
      ? (currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1)
      : (currentIndex === focusable.length - 1 ? 0 : currentIndex + 1)
    event.preventDefault()
    focusable[nextIndex].focus()
  }
}

function getFocusable(dialog: HTMLElement | null): HTMLElement[] {
  if (dialog === null) return []
  return Array.from(dialog.querySelectorAll<HTMLElement>(
    FOCUSABLE_SELECTOR,
  )).filter((element) => !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true")
}

const FOCUSABLE_SELECTOR = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"

function canReceiveFocus(element: HTMLElement | null): element is HTMLElement {
  return element !== null &&
    element.isConnected &&
    element.tabIndex >= 0 &&
    element.matches(FOCUSABLE_SELECTOR) &&
    !element.matches(":disabled") &&
    !element.hasAttribute("hidden") &&
    element.getAttribute("aria-hidden") !== "true" &&
    element.closest("[hidden], [inert], [aria-hidden='true']") === null &&
    !isVisuallyHidden(element)
}

function isVisuallyHidden(element: HTMLElement): boolean {
  if (typeof window === "undefined") return false
  const style = window.getComputedStyle(element)
  return style.display === "none" || style.visibility === "hidden"
}
