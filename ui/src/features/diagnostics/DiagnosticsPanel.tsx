import { useEffect, useState } from 'react'
import { fetchReportPack, fetchSnapshot } from './api.ts'
import { explainAvailability, modelsOf, operationsOf } from './availability.ts'
import { diagnosticsCopy, type DiagnosticsCopy } from './copy.ts'
import { triggerDownload } from './report.ts'
import type { AvailabilityItem, ReportCorrelation, ReportPack } from './types.ts'

type LoadState = 'loading' | 'ready' | 'error'

function FactList({ item }: { item: AvailabilityItem }) {
  return (
    <li className="rounded-md border border-border bg-bg-tertiary/40 px-3 py-2 text-[11px] leading-snug text-text-secondary">
      <p className="font-medium text-text-primary">
        {item.id}
        {' · '}
        {item.available ? 'available' : 'unavailable'}
      </p>
      <pre className="mt-1 whitespace-pre-wrap font-sans text-[11px] text-text-muted">{explainAvailability(item)}</pre>
    </li>
  )
}

export function DiagnosticsView({
  pack,
  copy,
  status,
  onExport,
}: {
  pack: ReportPack | null
  copy: DiagnosticsCopy
  status: LoadState
  onExport: () => void
}) {
  if (status !== 'ready' || !pack) {
    return <p className="text-xs text-text-muted">{status === 'loading' ? copy.loading : copy.failed}</p>
  }
  const errorLabel = pack.error
    ? `${pack.error.operation || 'task'} ${pack.error.task_id || ''} ${pack.error.code || pack.error.status || ''}`.trim()
    : copy.noError
  return (
    <section className="space-y-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-sm">{copy.title}</h3>
        <button
          type="button"
          onClick={onExport}
          className="rounded-md border border-border px-2.5 py-1 text-xs text-text-secondary hover:bg-bg-hover hover:text-text-primary"
        >
          {copy.export}
        </button>
      </div>
      <p className="text-[11px] text-text-muted">
        {copy.build}: {pack.build.app_version || 'n/a'} / {pack.build.git_revision || 'n/a'}
        {' · '}
        {copy.platform}: {pack.platform.os} {pack.platform.architecture} / {pack.platform.backend}
        {' · '}
        RAM {pack.observed.ram_gb ?? 'n/a'} GB / VRAM {pack.observed.vram_gb ?? 'n/a'} GB
      </p>
      <p className="text-[11px] text-text-secondary">{copy.error}: {errorLabel}</p>
      <div>
        <h4 className="mb-1 text-xs uppercase tracking-wide text-text-muted">{copy.operations}</h4>
        <ul className="space-y-2">{operationsOf(pack.availability).map(item => <FactList key={item.id} item={item} />)}</ul>
      </div>
      <div>
        <h4 className="mb-1 text-xs uppercase tracking-wide text-text-muted">{copy.models}</h4>
        <ul className="space-y-2">{modelsOf(pack.availability).map(item => <FactList key={item.id} item={item} />)}</ul>
      </div>
    </section>
  )
}

export function DiagnosticsPanel({
  fetcher = fetch,
  correlation,
}: {
  fetcher?: typeof fetch
  correlation?: ReportCorrelation
}) {
  const copy = diagnosticsCopy()
  const [pack, setPack] = useState<ReportPack | null>(null)
  const [status, setStatus] = useState<LoadState>('loading')
  useEffect(() => {
    let cancelled = false
    fetchSnapshot(fetcher)
      .then(value => {
        if (!cancelled) {
          setPack(value)
          setStatus('ready')
        }
      })
      .catch(() => {
        if (!cancelled) setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [fetcher])
  const onExport = () => {
    const run = pack
      ? Promise.resolve(pack)
      : fetchReportPack(correlation || {}, fetcher)
    void run.then(value => triggerDownload(value)).catch(() => setStatus('error'))
  }
  return <DiagnosticsView pack={pack} copy={copy} status={status} onExport={onExport} />
}
