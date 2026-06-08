import React from 'react'

type Props = {
  title?: string
  children?: React.ReactNode
  onClose?: () => void
  onConfirm?: () => void
  cancelLabel?: string
  confirmLabel?: string
}

export default function Modal({ title, children, onClose, onConfirm, cancelLabel, confirmLabel }: Props) {
  return (
    <div className="modal-overlay" role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <h3>{title}</h3>
        </header>
        <div className="modal-body">{children}</div>
        <footer>
          {onClose ? (
            <button onClick={onClose}>{cancelLabel || 'Abbrechen'}</button>
          ) : null}
          {onConfirm ? (
            <button className="confirm" onClick={onConfirm}>
              {confirmLabel || 'Bestatigen'}
            </button>
          ) : null}
        </footer>
      </div>
    </div>
  )
}
