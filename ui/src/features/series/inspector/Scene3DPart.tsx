import type { TFunction } from 'i18next'
import { useState } from 'react'
import { Box, ExternalLink, Loader2 } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import type { SeriesShotScript } from '../../../api/seriesShotInspector'
import { secondaryButton, textareaClass } from '../styles'
import type { SeriesShotScene3D } from '../types'
import { sectionId, type PartContext } from './context'
import { CheckInput, NumberInput, SelectInput } from './fields'
import type { SectionDraft } from './inspectorStore'
import { InspectorSection, type DraftProps } from './InspectorSection'
import { grid, stableJson, withField } from './model'

type Object3D = Record<string, unknown> & { objectId: string }
const EDITED = ['objects', 'quality', 'renderLook'] as const
const ADVANCED = ['clips', 'hold', 'motion', 'appearance'] as const

function clipNames(value: unknown): string[] {
  const clip = (item: unknown) => typeof item === 'string' ? item : item && typeof item === 'object' ? String((item as { name?: unknown }).name || '') : ''
  return Array.isArray(value) ? value.map(cue => clip((cue as { clip?: unknown }).clip)).filter(Boolean) : []
}

/** One object in words: its file, what it plays, who carries it, where it moves. */
const hand = (value: unknown) => value === 'left' ? 'left' as const : 'right' as const

function describe(t: TFunction<'seriesLab'>, object: Object3D): string {
  const hold = object.hold as { carrier?: string; hand?: string } | undefined
  const motion = object.motion as { to?: number[] } | undefined
  const clips = [...clipNames(object.clips), ...(object.clip ? clipNames([{ clip: object.clip }]) : [])]
  return [object.file ? String(object.file) : t('inspector.scene3d.templateObject'),
    clips.length ? t('inspector.scene3d.plays', { clips: clips.join(' → ') }) : '',
    hold?.carrier ? t('inspector.scene3d.held', { carrier: hold.carrier, hand: t(`inspector.scene3d.hands.${hand(hold.hand)}`) }) : '',
    motion?.to ? t('inspector.scene3d.moves', { to: motion.to.map(value => Math.round(value * 10) / 10).join(', ') }) : '',
    object.appearance ? t('inspector.scene3d.appears') : ''].filter(Boolean).join(' · ')
}

function slice(script: SeriesShotScript | undefined): SectionDraft {
  const scene = script?.scene3d || {}
  return Object.fromEntries(EDITED.filter(key => scene[key] !== undefined).map(key => [key, structuredClone(scene[key])]))
}

/** The scene3d with this part's fields from the draft; the cast stays as saved (its own part edits it). */
function diff(draft: SectionDraft, script: SeriesShotScript | undefined) {
  const before = script?.scene3d || {}
  const after: SeriesShotScene3D = { ...before }
  for (const key of EDITED) { if (draft[key] === undefined) delete after[key]; else after[key] = draft[key] as never }
  return stableJson(after) === stableJson(before) ? null : { scene3d: after }
}

function ObjectEditor({ object, change }: { object: Object3D; change: (object: Object3D) => void }) {
  const { t } = useUiTranslation('seriesLab')
  const position = Array.isArray(object.position) ? object.position as number[] : [0, 0, 0]
  const advanced = Object.fromEntries(ADVANCED.filter(key => object[key] !== undefined).map(key => [key, object[key]]))
  const [text, setText] = useState(() => JSON.stringify(advanced, null, 1))
  const [error, setError] = useState('')
  const setAxis = (axis: number, value: number | undefined) => change({ ...object, position: position.map((item, index) => index === axis ? value ?? 0 : item) })
  return <fieldset className="min-w-0 space-y-2 rounded-lg border border-border bg-bg-primary p-2">
    <legend className="px-1 text-[10px] font-semibold text-text-secondary">{object.objectId}</legend>
    <div className={grid}>
      {['x', 'y', 'z'].map((axis, index) => <NumberInput key={axis} title={`${axis} (m)`} value={position[index]} min={-1000} max={1000} step={0.1}
        onChange={value => setAxis(index, value)} />)}
      <NumberInput title={t('inspector.scene3d.rotation')} value={object.rotationY} min={-20} max={20} step={0.05} onChange={value => change(withField(object, 'rotationY', value))} />
      <NumberInput title={t('inspector.scene3d.scale')} value={object.scale} min={0.01} max={100} step={0.05} onChange={value => change(withField(object, 'scale', value))} />
      <CheckInput title={t('inspector.scene3d.grounded')} value={object.grounded} onChange={value => change({ ...object, grounded: value })} />
    </div>
    <label className="block text-[10px] text-text-muted">{t('inspector.scene3d.advanced')}
      <textarea className={`${textareaClass} mt-0.5 min-h-20 font-mono text-[11px]`} spellCheck={false} value={text} onChange={event => {
        setText(event.target.value)
        try {
          const parsed = event.target.value.trim() ? JSON.parse(event.target.value) : {}
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(t('approval.edit.jsonObject'))
          const base = Object.fromEntries(Object.entries(object).filter(([key]) => !(ADVANCED as readonly string[]).includes(key)))
          setError(''); change({ ...base, ...parsed, objectId: object.objectId } as Object3D)
        } catch (reason) { setError((reason as Error).message) }
      }} /></label>
    {error && <p role="alert" className="text-[10px] text-red-300">{error}</p>}
  </fieldset>
}

/** Template or saved scene, quality and look, in words. */
function sceneSummary(t: TFunction<'seriesLab'>, scene: SeriesShotScene3D | undefined): string {
  // A scene saved back from the editor is named after the shot (…-<shot>-plan-<uuid>.world3d.scene.json): say so instead.
  const edited = scene?.scene && /-plan-[0-9a-f]+\.world3d\.scene\.json$/.test(scene.scene)
  const source = scene?.template ? t('inspector.scene3d.template', { id: scene.template })
    : edited ? t('inspector.scene3d.editedScene') : scene?.scene ? t('inspector.scene3d.scene', { file: scene.scene }) : '—'
  return [source, t(`inspector.scene3d.qualities.${scene?.quality === 'final' ? 'final' : 'draft'}`),
    scene?.renderLook ? t('inspector.scene3d.look', { look: scene.renderLook }) : ''].filter(Boolean).join(' · ')
}

function ObjectList({ objects }: { objects: Object3D[] }) {
  const { t } = useUiTranslation('seriesLab')
  if (!objects.length) return null
  return <ul className="mt-2 space-y-1">{objects.map(object => <li key={object.objectId} className="rounded-lg border border-border bg-bg-primary px-2 py-1 text-[11px]">
    <span className="font-semibold text-text-primary">{object.objectId}</span> <span className="text-text-muted">{describe(t, object)}</span>
  </li>)}</ul>
}

function SceneEditor({ draft, change }: DraftProps) {
  const { t } = useUiTranslation('seriesLab')
  const objects = (draft.objects || []) as Object3D[]
  return <div className="space-y-2">
    <div className={grid}>
      <SelectInput title={t('inspector.scene3d.quality')} value={draft.quality || 'draft'} onChange={value => change({ ...draft, quality: value })}
        options={(['draft', 'final'] as const).map(value => ({ value, label: t(`inspector.scene3d.qualities.${value}`) }))} />
      <SelectInput title={t('inspector.scene3d.lookTitle')} value={draft.renderLook} empty={t('inspector.scene3d.looks.none')}
        onChange={value => change(withField(draft, 'renderLook', value))} options={(['toon', 'n64'] as const).map(value => ({ value, label: t(`inspector.scene3d.looks.${value}`) }))} />
    </div>
    {objects.map((object, index) => <ObjectEditor key={object.objectId} object={object}
      change={next => change({ ...draft, objects: objects.map((item, position) => position === index ? next : item) })} />)}
  </div>
}

/** A Video 3D shot's scene: its template or saved scene, look, quality and objects; it opens in the Video 3D editor. */
export function Scene3DPart({ context, onOpenEditor }: { context: PartContext; onOpenEditor: () => Promise<void> }) {
  const { t } = useUiTranslation('seriesLab')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const scene = context.script?.scene3d
  const open = async () => {
    setBusy(true); setError('')
    try { await onOpenEditor() } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) }
  }
  return <InspectorSection id={sectionId(context.shot.id, 'scene3d')} inspector={context.inspector} shotId={context.shot.id} section="scene3d"
    script={context.script} draft={context.drafts.scene3d} save={context.save} icon={<Box size={14} />} title={t('inspector.scene3d.title')}
    slice={slice} diff={diff} editable={Boolean(scene)} summary={sceneSummary(t, scene)}
    actions={scene && <button type="button" className={`${secondaryButton} min-h-10 sm:min-h-0 sm:py-1.5`} disabled={busy} onClick={() => void open()}>
      {busy ? <Loader2 size={13} className="animate-spin" /> : <ExternalLink size={13} />}{t('inspector.scene3d.openEditor')}</button>}
    view={<>
      <ObjectList objects={(scene?.objects || []) as Object3D[]} />
      <p className="mt-2 text-[10px] text-text-muted">{t('inspector.scene3d.hint')}</p>
      {error && <p role="alert" className="mt-1 text-[11px] text-red-300">{error}</p>}
    </>}
    editor={props => <SceneEditor {...props} />} />
}
