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

// Validated categorical palette (dataviz skill — light surface). Assigned in
// FIXED order, one hue per series, never cycled. Worst adjacent CVD ΔE 24.2 (well
// clear of the 12 target); the 3 lower-contrast hues are relieved by the always-
// available "Show data table" toggle. See references/palette.md.
const SERIES = [
  '#2a78d6', // blue
  '#1baf7a', // aqua
  '#eda100', // yellow
  '#008300', // green
  '#4a3aa7', // violet
  '#e34948', // red
  '#e87ba4', // magenta
  '#eb6834', // orange
]

// Recessive chrome + ink roles (light surface).
const INK_PRIMARY = '#0b0b0b'
const INK_MUTED = '#898781'
const GRIDLINE = '#e1e0d9'
const BASELINE = '#c3c2b7'
const SURFACE = '#ffffff'

type Trace = Record<string, unknown>

/** Assign palette colors by series, thin the marks, and round bar ends. */
function styleTraces(data: unknown[]): Trace[] {
  return (data as Trace[]).map((raw, i) => {
    const t: Trace = { ...raw }
    const color = SERIES[i % SERIES.length]
    const type = String(t.type ?? 'scatter')

    if (type === 'pie') {
      // One pie trace, many slices — color the slices in palette order.
      const labels = (t.labels as unknown[]) ?? []
      t.marker = {
        ...(t.marker as object),
        colors: labels.map((_, j) => SERIES[j % SERIES.length]),
        line: { color: SURFACE, width: 2 }, // 2px surface gap between slices
      }
      t.textposition = t.textposition ?? 'inside'
      t.hovertemplate = '%{label}: %{value} (%{percent})<extra></extra>'
      return t
    }

    if (type === 'bar') {
      t.marker = {
        ...(t.marker as object),
        color,
        cornerradius: 4, // rounded data-end
        line: { width: 0 },
      }
      t.hovertemplate = '%{x} · %{y}<extra></extra>'
      return t
    }

    // scatter / line
    const mode = String(t.mode ?? 'markers')
    t.line = { ...(t.line as object), color, width: 2 }
    t.marker = { ...(t.marker as object), color, size: 8 }
    t.hovertemplate = mode.includes('lines')
      ? '%{x}: %{y}<extra></extra>'
      : '(%{x}, %{y})<extra></extra>'
    return t
  })
}

export default function ChartView({ figure }: { figure: PlotlyFigure }) {
  const data = styleTraces(figure.data)
  const multiSeries = data.length > 1
  const incoming = (figure.layout ?? {}) as Record<string, unknown>

  const axisStyle = {
    tickfont: { color: INK_MUTED, size: 12 },
    titlefont: { color: INK_MUTED, size: 12 },
    gridcolor: GRIDLINE,
    linecolor: BASELINE,
    zerolinecolor: GRIDLINE,
    automargin: true,
  }

  return (
    <div className="w-full" data-testid="chart">
      <Plot
        data={data}
        layout={{
          autosize: true,
          colorway: SERIES,
          margin: { t: 44, r: 20, b: 52, l: 60 },
          font: {
            family: 'system-ui, -apple-system, "Segoe UI", sans-serif',
            size: 13,
            color: INK_PRIMARY,
          },
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
          // A legend only earns its box when there are ≥2 series; a single series
          // is named by the axis/title, not a swatch.
          showlegend: multiSeries,
          legend: {
            orientation: 'h',
            y: -0.2,
            x: 0,
            font: { color: INK_MUTED, size: 12 },
          },
          bargap: 0.28,
          bargroupgap: 0.12,
          hovermode: 'closest',
          hoverlabel: {
            bgcolor: '#0b0b0b',
            bordercolor: '#0b0b0b',
            font: { color: '#ffffff', size: 12 },
          },
          ...incoming,
          // Merge axis styling on top of any title carried in the incoming layout.
          xaxis: { ...axisStyle, ...((incoming.xaxis as object) ?? {}) },
          yaxis: { ...axisStyle, ...((incoming.yaxis as object) ?? {}) },
          title: {
            text: (incoming.title as { text?: string })?.text ?? (incoming.title as string) ?? '',
            font: { color: INK_PRIMARY, size: 15 },
            x: 0.02,
            xanchor: 'left',
          },
        }}
        config={{ responsive: true, displaylogo: false, displayModeBar: false }}
        useResizeHandler
        style={{ width: '100%', height: '380px' }}
        className="w-full"
      />
    </div>
  )
}
