import { useCallback, useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { BASE } from '../../api/http'
import type { Scene3DSlot } from './types'

export type LibraryProp = { id: string; name: string; description: string; heightM: number; file: string; style: string; approved: boolean }
export const PROP_DRAG_TYPE = 'application/x-hocus-prop'
export function filterProps(props: LibraryProp[], text: string, style: string) {
  return props.filter(prop => (!style || prop.style === style) && `${prop.name} ${prop.description}`.toLowerCase().includes(text.toLowerCase()))
}
export function propSlot(prop: LibraryProp, workspace: string, id = prop.id): Scene3DSlot {
  return { id, slot: 'prop', media: 'image', sourceUrl: `${BASE}/api/v1/file/${encodeURIComponent(prop.file)}?workspace=${encodeURIComponent(workspace)}`,
    surface: 'cutout', grounded: true, position: [0, 0, 0], rotationY: 0, scale: prop.heightM / 2, clip: null }
}
export async function propsCommand(operation: string, input: Record<string, unknown>, intent?: string) {
  const response = await fetch(`${BASE}/api/v1/props/commands`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operation, version: 1, input, ...(intent ? { intent_id: intent } : {}) }) })
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  return body.result
}

export function PropLibraryPanel({ workspace, disabled = false, onAdd }: { workspace: string; disabled?: boolean; onAdd: (prop: LibraryProp) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  const [props, setProps] = useState<LibraryProp[]>([]), [revision, setRevision] = useState(0)
  const [query, setQuery] = useState(''), [filter, setFilter] = useState(''), [style, setStyle] = useState('paper-cutout')
  const [description, setDescription] = useState(''), [height, setHeight] = useState(.5)
  const [job, setJob] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const load = useCallback(async () => {
    const result = await propsCommand('props.list', { workspace }); setProps(result.props); setRevision(result.revision)
  }, [workspace])
  useEffect(() => { void load().catch(e => setError(String(e))) }, [load])
  useEffect(() => {
    if (!job) return
    const timer = setInterval(() => { void propsCommand('props.status', { workspace, job_id: job }).then(result => {
      if (result.status === 'completed' || result.status === 'failed') { setJob(''); setBusy(false); if (result.error) setError(result.error); void load().catch(e => setError(String(e))) }
    }).catch(e => { setError(String(e)); setJob(''); setBusy(false) }) }, 1500)
    return () => clearInterval(timer)
  }, [job, workspace, load])
  const mutate = async (action: string, input: Record<string, unknown>) => {
    setBusy(true); setError('')
    try {
      const result = await propsCommand(`props.${action}`, { workspace, ...input }, `prop-ui-${crypto.randomUUID()}`)
      if (action === 'create') setJob(result.job_id)
      else { await load(); setBusy(false) }
    } catch (e) { setError(String(e)); setBusy(false) }
  }
  return <section className="space-y-2 rounded-xl border border-border p-3" aria-label={t('props.title')}>
    <h3>{t('props.title')}</h3>
    <input aria-label={t('props.search')} placeholder={t('props.search')} value={query} onChange={e => setQuery(e.target.value)} />
    <select aria-label={t('props.filterStyle')} value={filter} onChange={e => setFilter(e.target.value)}>
      <option value="">{t('props.allStyles')}</option>{[...new Set(props.map(p => p.style))].map(s => <option key={s}>{s}</option>)}
    </select>
    <ul className="max-h-64 overflow-y-auto">{filterProps(props, query, filter).map(prop => <li key={prop.id} className="flex items-center gap-2 py-1"
      draggable={prop.approved && !disabled} onDragStart={e => e.dataTransfer.setData(PROP_DRAG_TYPE, JSON.stringify(prop))}>
      <img alt="" className="h-12 w-12 object-contain" src={propSlot(prop, workspace).sourceUrl} />
      <span>{prop.name} · {prop.heightM} m</span>
      {prop.approved ? <button disabled={disabled} onClick={() => onAdd(prop)}>{t('props.add')}</button>
        : <><button disabled={disabled || busy} onClick={() => void mutate('approve', { id: prop.id, base_revision: revision })}>{t('props.approve')}</button>
          <button disabled={disabled || busy} onClick={() => void mutate('reject', { id: prop.id, base_revision: revision })}>{t('props.reject')}</button></>}
    </li>)}</ul>
    <details><summary>{t('props.new')}</summary><form onSubmit={e => { e.preventDefault(); void mutate('create', { name: description.slice(0, 80), description, heightM: height, style }) }}>
      <label>{t('props.description')}<input required value={description} onChange={e => setDescription(e.target.value)} /></label>
      <label>{t('props.height')}<input type="number" min="0.01" max="30" step="0.01" required value={height} onChange={e => setHeight(Number(e.target.value))} /></label>
      <label>{t('props.style')}<input value={style} onChange={e => setStyle(e.target.value)} /></label>
      <button disabled={disabled || busy}>{t('props.generate')}</button>
    </form></details>
    {busy && <p role="status">{t('props.generating')}</p>}{error && <p role="alert">{error}</p>}
  </section>
}
