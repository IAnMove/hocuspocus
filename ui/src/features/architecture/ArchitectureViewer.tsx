import { useEffect, useMemo, useState } from 'react'
import type { TFunction } from 'i18next'
import { AlertTriangle, ChevronDown, GitBranch, Loader2, RefreshCw, Search } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { loadArchitectureGraph } from './architectureLoader'
import type {
  ArchitectureEdge,
  ArchitectureEvidence,
  ArchitectureGraph,
  ArchitectureNode,
} from './architectureSchema'

type Selection =
  | { kind: 'node'; id: string }
  | { kind: 'edge'; id: string }
  | null

type Position = { x: number; y: number }

const NODE_WIDTH = 194
const NODE_HEIGHT = 58
const COLUMN_GAP = 42
const ROW_GAP = 22
const PADDING = 28
const LOAD_TIMEOUT_MS = 10_000

function shortText(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value
}

function graphLayout(nodes: ArchitectureNode[]): {
  layers: string[]
  positions: Map<string, Position>
  width: number
  height: number
} {
  const layerOrder = ['ui', 'controller', 'store', 'api', 'route', 'service']
  const layers = [...new Set(nodes.map(node => node.layer))].sort((left, right) => {
    const leftIndex = layerOrder.indexOf(left)
    const rightIndex = layerOrder.indexOf(right)
    if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right)
    if (leftIndex === -1) return 1
    if (rightIndex === -1) return -1
    return leftIndex - rightIndex
  })
  const positions = new Map<string, Position>()
  const byLayer = new Map<string, ArchitectureNode[]>()
  for (const layer of layers) byLayer.set(layer, [])
  for (const node of nodes) byLayer.get(node.layer)?.push(node)

  let maxRows = 0
  for (const [layerIndex, layer] of layers.entries()) {
    const layerNodes = byLayer.get(layer) || []
    maxRows = Math.max(maxRows, layerNodes.length)
    layerNodes.forEach((node, rowIndex) => {
      positions.set(node.id, {
        x: PADDING + layerIndex * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING + rowIndex * (NODE_HEIGHT + ROW_GAP),
      })
    })
  }
  return {
    layers,
    positions,
    width: Math.max(620, PADDING * 2 + layers.length * NODE_WIDTH + Math.max(0, layers.length - 1) * COLUMN_GAP),
    height: Math.max(180, PADDING * 2 + maxRows * NODE_HEIGHT + Math.max(0, maxRows - 1) * ROW_GAP),
  }
}

function sourceLink(evidence: ArchitectureEvidence, graph: ArchitectureGraph): string | null {
  const commit = graph.meta.source_commit
  if (graph.meta.dirty || !commit) return null
  const encodedPath = evidence.file.split('/').map(segment => encodeURIComponent(segment)).join('/')
  return `https://github.com/IAnMove/hocuspocus/blob/${commit}/${encodedPath}#L${evidence.line}`
}

function EvidenceList({ evidence, graph, emptyLabel, sourceUnavailableLabel }: {
  evidence: ArchitectureEvidence[]
  graph: ArchitectureGraph
  emptyLabel: string
  sourceUnavailableLabel: string
}) {
  if (evidence.length === 0) return <p className="text-xs text-text-muted">{emptyLabel}</p>
  return (
    <ul className="space-y-1.5">
      {evidence.map((item, index) => {
        const link = sourceLink(item, graph)
        const location = `${item.file}:${item.line}${item.column ? `:${item.column}` : ''}`
        return (
          <li key={`${location}-${index}`} className="text-xs">
            {link ? (
              <a
                href={link}
                target="_blank"
                rel="noreferrer"
                className="break-all text-accent-blue hover:underline"
              >
                {location}
              </a>
            ) : (
              <span className="break-all text-text-secondary" title={sourceUnavailableLabel}>
                {location}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function ArchitectureGraphCanvas({
  nodes,
  edges,
  selection,
  onSelect,
  ariaLabel,
  t,
}: {
  nodes: ArchitectureNode[]
  edges: Array<ArchitectureEdge & { index: number }>
  selection: Selection
  onSelect: (selection: Selection) => void
  ariaLabel: string
  t: TFunction<'auditDev'>
}) {
  const layout = useMemo(() => graphLayout(nodes), [nodes])
  const positions = layout.positions
  const nodeById = useMemo(() => new Map(nodes.map(node => [node.id, node])), [nodes])
  const canvasHeight = Math.max(320, layout.height)

  return (
    <div className="h-[min(65vh,560px)] min-h-[320px] shrink-0 overflow-auto rounded-lg border border-border bg-bg-secondary/60 p-2">
      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        width={layout.width}
        height={canvasHeight}
        role="img"
        aria-label={ariaLabel}
        className="block max-w-none"
      >
        <defs>
          <marker id="architecture-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L0,6 L7,3 z" fill="currentColor" />
          </marker>
        </defs>
        {edges.map(edge => {
          const source = positions.get(edge.source)
          const target = positions.get(edge.target)
          if (!source || !target) return null
          const selected = selection?.kind === 'edge' && selection.id === `edge-${edge.index}`
          const x1 = source.x + NODE_WIDTH
          const y1 = source.y + NODE_HEIGHT / 2
          const x2 = target.x
          const y2 = target.y + NODE_HEIGHT / 2
          return (
            <line
              key={`edge-${edge.index}`}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={selected || edge.highlight ? 'rgb(96 165 250)' : 'rgb(100 116 139)'}
              strokeWidth={selected ? 4 : Math.min(5, 1 + Math.log2(edge.weight + 1))}
              strokeOpacity={selected ? 1 : 0.72}
              markerEnd="url(#architecture-arrow)"
              role="button"
              tabIndex={0}
              aria-label={`${edge.source} ${edge.kind} ${edge.target}`}
              onClick={() => onSelect({ kind: 'edge', id: `edge-${edge.index}` })}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelect({ kind: 'edge', id: `edge-${edge.index}` })
                }
              }}
            />
          )
        })}
        {layout.layers.map((layer, index) => (
          <text
            key={layer}
            x={PADDING + index * (NODE_WIDTH + COLUMN_GAP)}
            y={16}
            fill="currentColor"
            className="fill-text-muted text-[10px] font-semibold uppercase tracking-wider"
          >
            {shortText(layer, 24)}
          </text>
        ))}
        {nodes.map(node => {
          const position = positions.get(node.id)
          if (!position) return null
          const selected = selection?.kind === 'node' && selection.id === node.id
          return (
            <g
              key={node.id}
              transform={`translate(${position.x}, ${position.y})`}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={`${node.label} (${node.layer})`}
              onClick={() => onSelect({ kind: 'node', id: node.id })}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelect({ kind: 'node', id: node.id })
                }
              }}
              className="cursor-pointer outline-none"
            >
              <title>{node.detail}</title>
              <rect
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                rx="8"
                fill={selected ? 'rgb(30 64 175 / 0.35)' : 'rgb(30 41 59 / 0.9)'}
                stroke={selected ? 'rgb(96 165 250)' : 'rgb(71 85 105)'}
                strokeWidth={selected ? 2 : 1}
              />
              <text x="10" y="22" fill="currentColor" className="fill-text-primary text-[11px] font-medium">
                {shortText(node.label, 29)}
              </text>
              <text x="10" y="42" fill="currentColor" className="fill-text-muted text-[9px]">
                {shortText(node.id, 31)}
              </text>
            </g>
          )
        })}
      </svg>
      <p className="px-1 pb-1 text-[10px] text-text-muted">
        {t('architecture.nodeCount', { count: nodeById.size })} · {t('architecture.connectionCount', { count: edges.length })}
      </p>
    </div>
  )
}

function MetadataSummary({ graph, t }: { graph: ArchitectureGraph; t: TFunction<'auditDev'> }) {
  return (
    <div className="grid gap-2 rounded-lg border border-border bg-bg-secondary/50 p-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
      <div><dt className="text-text-muted">{t('architecture.scope')}</dt><dd className="mt-0.5 break-words text-text-secondary">{graph.meta.scope}</dd></div>
      <div><dt className="text-text-muted">{t('architecture.commit')}</dt><dd className="mt-0.5 break-all font-mono text-text-secondary">{graph.meta.source_commit || t('architecture.notAvailable')}</dd></div>
      <div><dt className="text-text-muted">{t('architecture.sourceHash')}</dt><dd className="mt-0.5 break-all font-mono text-text-secondary">{graph.meta.source_hash}</dd></div>
      <div><dt className="text-text-muted">{t('architecture.generatedBy')}</dt><dd className="mt-0.5 break-words text-text-secondary">{graph.meta.generated_by}</dd></div>
      <div className="sm:col-span-2 lg:col-span-4">
        <dt className="text-text-muted">{t('architecture.workingTree')}</dt>
        <dd className={`mt-0.5 font-medium ${graph.meta.dirty ? 'text-amber-300' : 'text-emerald-300'}`}>
          {graph.meta.dirty ? t('architecture.dirty') : t('architecture.clean')}
        </dd>
      </div>
    </div>
  )
}

export function ArchitectureViewer() {
  const { t } = useUiTranslation('auditDev')
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<{ status: 'loading' } | { status: 'ready'; graph: ArchitectureGraph } | { status: 'error'; message: string }>({ status: 'loading' })
  const [query, setQuery] = useState('')
  const [layer, setLayer] = useState('all')
  const [selection, setSelection] = useState<Selection>(null)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    let timedOut = false
    const timeoutId = window.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, LOAD_TIMEOUT_MS)
    void loadArchitectureGraph((input, init) => fetch(input, { ...init, signal: controller.signal }))
      .then(graph => {
        if (!cancelled) setState({ status: 'ready', graph })
      })
      .catch(error => {
        if (cancelled) return
        if (error instanceof DOMException && error.name === 'AbortError' && !timedOut) return
        setState({ status: 'error', message: timedOut ? t('architecture.timeout') : error instanceof Error ? error.message : t('architecture.loadError') })
      })
    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [attempt, t])

  if (state.status === 'loading') {
    return (
      <div className="flex h-full min-h-[260px] items-center justify-center text-text-muted">
        <Loader2 size={18} className="animate-spin" />
        <span className="ml-2 text-xs">{t('architecture.loading')}</span>
      </div>
    )
  }

  if (state.status === 'error') {
    return (
      <div className="flex h-full min-h-[260px] flex-col items-center justify-center gap-3 text-center">
        <AlertTriangle size={22} className="text-amber-300" />
        <p className="max-w-lg text-xs text-text-secondary">{t('architecture.loadError')}</p>
        <p className="max-w-lg break-words text-[10px] text-text-muted">{state.message}</p>
        <button type="button" onClick={() => { setState({ status: 'loading' }); setAttempt(value => value + 1) }} className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover">
          <RefreshCw size={13} />{t('architecture.retry')}
        </button>
      </div>
    )
  }

  const graph = state.graph
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const layers = [...new Set(graph.nodes.map(node => node.layer))]
  const visibleNodes = graph.nodes.filter(node => {
    const inLayer = layer === 'all' || node.layer === layer
    const haystack = `${node.id} ${node.layer} ${node.label} ${node.detail}`.toLocaleLowerCase()
    return inLayer && (!normalizedQuery || haystack.includes(normalizedQuery))
  })
  const visibleIds = new Set(visibleNodes.map(node => node.id))
  const visibleEdges = graph.edges.flatMap((edge, index) => (
    visibleIds.has(edge.source) && visibleIds.has(edge.target) ? [{ ...edge, index }] : []
  ))
  const selectedNode = selection?.kind === 'node' ? graph.nodes.find(node => node.id === selection.id) : undefined
  const selectedEdge = selection?.kind === 'edge' ? graph.edges[Number(selection.id.replace('edge-', ''))] : undefined

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto pr-1">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary"><GitBranch size={16} className="text-accent-blue" />{t('architecture.title')}</h2>
          <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-text-muted">{t('architecture.description')}</p>
        </div>
        <span className="rounded border border-border bg-bg-secondary px-2 py-1 text-[10px] text-text-muted">v{graph.meta.schema_version}</span>
      </div>

      <div className="grid gap-2 rounded-lg border border-border bg-bg-secondary/40 p-2 sm:grid-cols-[minmax(0,1fr)_180px]">
        <label className="flex items-center gap-2 rounded-md border border-border bg-bg-tertiary px-2 py-1.5">
          <Search size={13} className="shrink-0 text-text-muted" />
          <span className="sr-only">{t('architecture.search')}</span>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder={t('architecture.search')} className="min-w-0 flex-1 bg-transparent text-xs text-text-primary outline-none placeholder:text-text-muted" />
        </label>
        <label className="flex items-center gap-2 rounded-md border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-muted">
          <span className="shrink-0">{t('architecture.layer')}</span>
          <select value={layer} onChange={event => setLayer(event.target.value)} className="min-w-0 flex-1 bg-transparent text-text-secondary outline-none">
            <option value="all">{t('architecture.allLayers')}</option>
            {layers.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
          <ChevronDown size={13} className="shrink-0" />
        </label>
      </div>

      {visibleNodes.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-xs text-text-muted">{t('architecture.empty')}</div>
      ) : (
        <ArchitectureGraphCanvas nodes={visibleNodes} edges={visibleEdges} selection={selection} onSelect={setSelection} ariaLabel={t('architecture.graphAria')} t={t} />
      )}

      <MetadataSummary graph={graph} t={t} />

      {(graph.meta.limitations.length > 0 || graph.meta.warnings.length > 0) && (
        <div className="grid gap-2 md:grid-cols-2">
          {graph.meta.limitations.length > 0 && <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs"><p className="font-medium text-amber-200">{t('architecture.limitations')}</p><ul className="mt-1 list-disc space-y-1 pl-4 text-amber-100/80">{graph.meta.limitations.map(item => <li key={item}>{item}</li>)}</ul></div>}
          {graph.meta.warnings.length > 0 && <div className="rounded-lg border border-orange-500/30 bg-orange-500/10 p-3 text-xs"><p className="font-medium text-orange-200">{t('architecture.warnings')}</p><ul className="mt-1 list-disc space-y-1 pl-4 text-orange-100/80">{graph.meta.warnings.map(item => <li key={item}>{item}</li>)}</ul></div>}
        </div>
      )}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section aria-labelledby="architecture-node-list" className="rounded-lg border border-border bg-bg-secondary/40 p-3">
          <h3 id="architecture-node-list" className="text-xs font-semibold text-text-primary">{t('architecture.nodes')} ({visibleNodes.length})</h3>
          <div className="mt-2 max-h-56 space-y-1 overflow-y-auto">
            {visibleNodes.map(node => <button key={node.id} type="button" aria-pressed={selection?.kind === 'node' && selection.id === node.id} onClick={() => setSelection({ kind: 'node', id: node.id })} className="block w-full rounded-md border border-transparent px-2 py-1.5 text-left text-xs hover:border-border hover:bg-bg-hover aria-pressed:border-accent-blue/60 aria-pressed:bg-accent-blue/10"><span className="font-medium text-text-secondary">{node.label}</span><span className="ml-2 text-[10px] text-text-muted">{node.layer}</span></button>)}
          </div>
        </section>
        <section aria-labelledby="architecture-edge-list" className="rounded-lg border border-border bg-bg-secondary/40 p-3">
          <h3 id="architecture-edge-list" className="text-xs font-semibold text-text-primary">{t('architecture.connections')} ({visibleEdges.length})</h3>
          <div className="mt-2 max-h-56 space-y-1 overflow-y-auto">
            {visibleEdges.map(edge => <button key={`edge-${edge.index}`} type="button" aria-pressed={selection?.kind === 'edge' && selection.id === `edge-${edge.index}`} onClick={() => setSelection({ kind: 'edge', id: `edge-${edge.index}` })} className="block w-full rounded-md border border-transparent px-2 py-1.5 text-left text-[10px] hover:border-border hover:bg-bg-hover aria-pressed:border-accent-blue/60 aria-pressed:bg-accent-blue/10"><span className="text-text-secondary">{edge.source}</span><span className="mx-1 text-text-muted">→</span><span className="text-text-secondary">{edge.target}</span><span className="ml-2 text-text-muted">{edge.kind}{edge.weight > 1 ? ` ${t('architecture.edgeMultiplicity', { count: edge.weight })}` : ''}</span></button>)}
          </div>
        </section>
      </div>

      <section aria-live="polite" className="rounded-lg border border-border bg-bg-secondary/40 p-3">
        <h3 className="text-xs font-semibold text-text-primary">{t('architecture.selection')}</h3>
        {selectedNode ? (
          <div className="mt-2 space-y-2 text-xs">
            <p className="font-medium text-text-secondary">{selectedNode.label} <span className="font-normal text-text-muted">({selectedNode.layer})</span></p>
            <p className="whitespace-pre-wrap break-words text-text-muted">{selectedNode.detail}</p>
            <EvidenceList evidence={selectedNode.evidence} graph={graph} emptyLabel={t('architecture.noEvidence')} sourceUnavailableLabel={t('architecture.sourceUnavailable')} />
          </div>
        ) : selectedEdge ? (
          <div className="mt-2 space-y-2 text-xs">
            <p className="font-medium text-text-secondary">{selectedEdge.source} → {selectedEdge.target}</p>
            <p className="text-text-muted">{selectedEdge.kind}{selectedEdge.label ? ` · ${selectedEdge.label}` : ''}{selectedEdge.weight > 1 ? ` · ${t('architecture.edgeMultiplicity', { count: selectedEdge.weight })}` : ''}</p>
            <EvidenceList evidence={selectedEdge.evidence} graph={graph} emptyLabel={t('architecture.noEvidence')} sourceUnavailableLabel={t('architecture.sourceUnavailable')} />
          </div>
        ) : <p className="mt-2 text-xs text-text-muted">{t('architecture.selectHint')}</p>}
      </section>

      <p className="text-[10px] leading-relaxed text-text-muted">{t('architecture.staticSites')}</p>
    </div>
  )
}
