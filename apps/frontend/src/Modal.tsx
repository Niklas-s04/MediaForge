import React from 'react'

import { useEffect, useRef } from 'react'

type Props = {
  title?: string
  children?: React.ReactNode
  onClose?: () => void
  onConfirm?: () => void
  cancelLabel?: string
  confirmLabel?: string
}

export default function Modal({ title, children, onClose, onConfirm, cancelLabel, confirmLabel }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    const previousFocus = document.activeElement as HTMLElement | null
    element.showModal()
    return () => { element.close(); previousFocus?.focus() }
  }, [])
  return (
      <dialog ref={dialog} className="modal" aria-label={title} onCancel={event => { event.preventDefault(); onClose?.() }} onKeyDown={event => {
        if (event.key !== 'Tab') return
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, [tabindex="0"]')).filter(element => !element.hasAttribute('disabled'))
        const first = controls[0]
        const last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }}>
        <header>
          <h3>{title}</h3>
        </header>
        <div className="modal-body">{children}</div>
        <footer>
          {onClose ? (
            <button autoFocus onClick={onClose}>{cancelLabel || 'Abbrechen'}</button>
          ) : null}
          {onConfirm ? (
            <button className="confirm" onClick={onConfirm}>
              {confirmLabel || 'Bestätigen'}
            </button>
          ) : null}
        </footer>
      </dialog>
  )
}
