import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

const root = createRoot(document.getElementById('root')!)

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

// E2E readiness signal: tests can wait for this flag.
setTimeout(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).__APP_READY__ = true
}, 0)
