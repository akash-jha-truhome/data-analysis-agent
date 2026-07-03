// Type shims for the Plotly dist-min bundle + the react-plotly.js factory
// subpath, which do not ship their own declarations. We only need loose
// typing here — the strongly-typed surface lives in src/lib/api.ts.
declare module 'plotly.js-dist-min' {
  const Plotly: unknown
  export default Plotly
}

declare module 'react-plotly.js/factory' {
  import type { ComponentType } from 'react'
  const createPlotlyComponent: (plotly: unknown) => ComponentType<{
    data: unknown[]
    layout?: Record<string, unknown>
    config?: Record<string, unknown>
    style?: React.CSSProperties
    useResizeHandler?: boolean
    className?: string
  }>
  export default createPlotlyComponent
}
