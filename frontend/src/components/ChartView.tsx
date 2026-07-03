'use client'

import dynamic from 'next/dynamic'
import type { PlotlyFigure } from '@/lib/api'

// Static export (`output: 'export'`) cannot server-render Plotly, so we load the
// component client-side only. We build the React component from the lightweight
// `plotly.js-dist-min` bundle via `react-plotly.js/factory` — this avoids pulling
// the full (huge, source-map-heavy) `plotly.js` into the client bundle.
const Plot = dynamic(
  async () => {
    const Plotly = (await import('plotly.js-dist-min')).default
    const createPlotlyComponent = (await import('react-plotly.js/factory')).default
    return createPlotlyComponent(Plotly)
  },
  {
    ssr: false,
    loading: () => (
      <div className="flex h-72 items-center justify-center text-sm text-slate-400">
        Rendering chart…
      </div>
    ),
  },
)

export default function ChartView({ figure }: { figure: PlotlyFigure }) {
  return (
    <div className="w-full" data-testid="chart">
      <Plot
        data={figure.data}
        layout={{
          autosize: true,
          margin: { t: 48, r: 16, b: 48, l: 56 },
          font: { family: 'ui-sans-serif, system-ui, sans-serif', size: 13 },
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
          ...(figure.layout ?? {}),
        }}
        config={{ responsive: true, displaylogo: false }}
        useResizeHandler
        style={{ width: '100%', height: '360px' }}
        className="w-full"
      />
    </div>
  )
}
