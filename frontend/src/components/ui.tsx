'use client'

import type { ReactNode } from 'react'

/** A clearly-labelled "not built yet" pill so a stub never reads as a bug. */
export function ComingSoon({ label = 'Coming soon' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-slate-300 bg-slate-100 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-slate-400" />
      {label}
    </span>
  )
}

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
