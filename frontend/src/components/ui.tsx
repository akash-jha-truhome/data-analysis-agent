'use client'

import type { ReactNode } from 'react'

/** An accessible spinner with a visible, contextual label. */
export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-600" role="status" aria-live="polite">
      <span
        aria-hidden
        className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600 motion-reduce:animate-none"
      />
      {label && <span>{label}</span>}
    </span>
  )
}

/** A titled surface used for each workbench section. */
export function Card({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {children}
    </section>
  )
}
