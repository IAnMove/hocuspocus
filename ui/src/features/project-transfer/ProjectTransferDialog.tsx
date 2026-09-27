import { useMemo, useState } from 'react'
import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../asset-picker'
import { ModalShell } from '../../components/common/ModalShell.tsx'
import { interpolate, transferCopy, type TransferCopy } from './copy.ts'
import { collectAssetUses, uniqueAssetUses } from './format.ts'
import { preflightFile, type PackedAsset, type PreflightReport } from './preflight.ts'
import { canImport, pickerToReassign, repairAssets, type ReassignEntry } from './reassign.ts'
import { downloadBlob, exportScenePackage, importScenePackage, preflightScenePackage } from './transferApi.ts'

function packageFilename(title: string) {
  return `${(title || 'scene-package').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-|-$/g, '') || 'scene-package'}.scene-package.zip`
}

function messageOf(caught: unknown, fallback: string) {
  return caught instanceof Error ? caught.message : fallback
}

async function inspectPackageFile(next: File): Promise<PreflightReport> {
  try {
    return await preflightScenePackage(next)
  } catch {
    return preflightFile(next)
  }
}

function isTemplateFailure(report: PreflightReport) {
  return report.issues.some(item => item.code === 'template')
}

function repairCaption(asset: PackedAsset, copy: TransferCopy) {
  const name = asset.filename || asset.sha256.slice(0, 8)
  const template = asset.status === 'tampered' ? copy.tamperedAsset : copy.missingAsset
  return interpolate(template, { name })
}

function ImportStatus({ ready, hasRepairs, copy }: { ready: boolean; hasRepairs: boolean; copy: TransferCopy }) {
  if (ready) return <p role="status">{copy.ready}</p>
  if (hasRepairs) return <p role="status">{copy.repairNeeded}</p>
  return <p role="status">{copy.blocked}</p>
}

function UnknownFieldList({ fields, label }: { fields: string[]; label: string }) {
  if (!fields.length) return null
  return (
    <div>
      <p>{label}</p>
      <ul>{fields.map(field => <li key={field}>{field}</li>)}</ul>
    </div>
  )
}

function RepairFields({
  repairs, copy, catalogItems, workspace, onChoose,
}: {
  repairs: PackedAsset[]
  copy: TransferCopy
  catalogItems: ApiOutput[]
  workspace: string
  onChoose: (sha256: string, item: ApiOutput | null) => void
}) {
  return (
    <>
      {repairs.map(asset => (
        <AssetInput
          key={asset.sha256}
          label={repairCaption(asset, copy)}
          placeholder={interpolate(copy.replaceAsset, { name: asset.filename || asset.sha256.slice(0, 8) })}
          items={catalogItems}
          workspaceId={workspace}
          constraints={{ kinds: ['model3d', 'audio', 'image', 'video'], maxCount: 1, optional: false }}
          onChoose={item => onChoose(asset.sha256, item)}
        />
      ))}
    </>
  )
}

function ExportPane({
  copy, documents, uses, title, busy, onTitle, onExport,
}: {
  copy: TransferCopy
  documents: unknown[]
  uses: number
  title: string
  busy: boolean
  onTitle: (value: string) => void
  onExport: () => void
}) {
  return (
    <div className="space-y-3">
      <p>{copy.exportHelp}</p>
      <p>{interpolate(copy.shots, { count: documents.length })} · {interpolate(copy.assetsUsed, { count: uses })}</p>
      <label className="block">{copy.packageName}
        <input className="mt-1 min-h-10 w-full rounded-lg border border-border bg-bg-secondary px-3" value={title} maxLength={120} onChange={event => onTitle(event.target.value)} />
      </label>
      <button type="button" className="min-h-10 rounded-lg border border-border px-3" disabled={busy || documents.length === 0} onClick={onExport}>
        {busy ? copy.exporting : copy.exportAction}
      </button>
    </div>
  )
}

function ImportReport({
  copy, report, ready, repairs, busy, catalogItems, workspace, onChoose, onImport,
}: {
  copy: TransferCopy
  report: PreflightReport
  ready: boolean
  repairs: PackedAsset[]
  busy: boolean
  catalogItems: ApiOutput[]
  workspace: string
  onChoose: (sha256: string, item: ApiOutput | null) => void
  onImport: () => void
}) {
  return (
    <div className="space-y-2">
      <ImportStatus ready={ready} hasRepairs={repairs.length > 0} copy={copy} />
      <UnknownFieldList fields={report.unknownFields} label={copy.unknownFields} />
      <RepairFields repairs={repairs} copy={copy} catalogItems={catalogItems} workspace={workspace} onChoose={onChoose} />
      <button type="button" className="min-h-10 rounded-lg border border-border px-3" disabled={busy || !ready} onClick={onImport}>
        {busy ? copy.importing : copy.importAction}
      </button>
    </div>
  )
}

function ImportPane({
  copy, busy, report, ready, repairs, catalogItems, workspace, onInspect, onChoose, onImport,
}: {
  copy: TransferCopy
  busy: boolean
  report: PreflightReport | null
  ready: boolean
  repairs: PackedAsset[]
  catalogItems: ApiOutput[]
  workspace: string
  onInspect: (file: File | undefined) => void
  onChoose: (sha256: string, item: ApiOutput | null) => void
  onImport: () => void
}) {
  return (
    <div className="space-y-3">
      <p>{copy.importHelp}</p>
      <label className="block">
        {copy.chooseZip}
        <input type="file" accept=".zip,application/zip" className="mt-1 block w-full" aria-label={copy.chooseZip} disabled={busy}
          onChange={event => { onInspect(event.target.files?.[0]); event.target.value = '' }} />
      </label>
      {busy && !report ? <p role="status">{copy.inspecting}</p> : null}
      {report ? (
        <ImportReport copy={copy} report={report} ready={ready} repairs={repairs} busy={busy}
          catalogItems={catalogItems} workspace={workspace} onChoose={onChoose} onImport={onImport} />
      ) : null}
    </div>
  )
}

export function ProjectTransferDialog({
  open,
  onClose,
  workspace,
  documents,
  catalogItems = [],
  onImported,
}: {
  open: boolean
  onClose: () => void
  workspace: string
  documents: unknown[]
  catalogItems?: ApiOutput[]
  onImported?: (scenes: Array<{ name: string }>) => void
}) {
  const copy = transferCopy()
  const [tab, setTab] = useState<'export' | 'import'>('export')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<PreflightReport | null>(null)
  const [reassign, setReassign] = useState<Record<string, ReassignEntry>>({})
  const uses = useMemo(() => uniqueAssetUses(documents.flatMap((document, index) => collectAssetUses(document, `shot-${index + 1}`))), [documents])
  const repairs = report ? repairAssets(report) : []
  const ready = Boolean(report) && canImport(report!, Object.keys(reassign))

  const runExport = async () => {
    setBusy(true); setError(''); setNote('')
    try {
      downloadBlob(await exportScenePackage({ workspace, documents, title }), packageFilename(title))
    } catch (caught) {
      setError(messageOf(caught, copy.blocked))
    } finally { setBusy(false) }
  }

  const inspect = async (next: File | undefined) => {
    if (!next) return
    setBusy(true); setError(''); setNote(''); setFile(next); setReassign({})
    try {
      const inspected = await inspectPackageFile(next)
      setReport(inspected)
      if (isTemplateFailure(inspected)) setError(copy.templateRejected)
    } catch (caught) {
      setReport(null)
      setError(messageOf(caught, copy.blocked))
    } finally { setBusy(false) }
  }

  const runImport = async () => {
    if (!file || !ready) return
    setBusy(true); setError(''); setNote('')
    try {
      const result = await importScenePackage({ workspace, file, reassign: Object.values(reassign) })
      setNote(interpolate(copy.imported, { count: result.scenes.length }))
      onImported?.(result.scenes)
      setFile(null); setReport(null); setReassign({})
    } catch (caught) {
      setError(messageOf(caught, copy.blocked))
    } finally { setBusy(false) }
  }

  const chooseRepair = (sha256: string, item: ApiOutput | null) => {
    setReassign(current => {
      if (!item) {
        const next = { ...current }
        delete next[sha256]
        return next
      }
      return { ...current, [sha256]: pickerToReassign(sha256, item, workspace) }
    })
  }

  return (
    <ModalShell open={open} title={copy.title} onClose={onClose} className="fixed inset-0 z-[140] flex items-end justify-center bg-black/70 p-3 sm:items-center">
      <div className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-auto rounded-xl border border-border bg-bg-primary p-4 text-sm text-text-primary">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold">{copy.title}</h2>
          <button type="button" className="min-h-10 rounded-lg border border-border px-3" onClick={onClose}>{copy.close}</button>
        </div>
        <div className="mb-3 flex flex-wrap gap-2">
          <button type="button" className="min-h-10 rounded-lg border border-border px-3" aria-pressed={tab === 'export'} onClick={() => setTab('export')}>{copy.exportTab}</button>
          <button type="button" className="min-h-10 rounded-lg border border-border px-3" aria-pressed={tab === 'import'} onClick={() => setTab('import')}>{copy.importTab}</button>
        </div>
        {tab === 'export'
          ? <ExportPane copy={copy} documents={documents} uses={uses.length} title={title} busy={busy} onTitle={setTitle} onExport={() => void runExport()} />
          : <ImportPane copy={copy} busy={busy} report={report} ready={ready} repairs={repairs} catalogItems={catalogItems} workspace={workspace} onInspect={next => void inspect(next)} onChoose={chooseRepair} onImport={() => void runImport()} />}
        {note ? <p role="status" className="mt-3">{note}</p> : null}
        {error ? <p role="alert" className="mt-3">{error}</p> : null}
      </div>
    </ModalShell>
  )
}
