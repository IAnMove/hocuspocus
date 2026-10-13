import { useEffect, useRef, useState } from 'react'
import { ModalShell } from '../../components/common/ModalShell'
import { useUiTranslation } from '../../i18n'
import type { Scene } from '../../types'
import { COMPOSER_SCENE_TEMPLATES, getCandidateSceneTemplate, requiredSlots, type ControlSpec, type ControlValue, type SceneTemplateDefinition, type TemplateSlotName } from './catalog'
import { catalogBindingIssue, resolveCatalogBindings, type CatalogSelections } from './catalogBindings'
import { compileCandidateScene } from './compile'
import { TemplateAssetPicker } from './TemplateAssetPicker'
import { importApprovedReference } from './referenceImport'
import { TemplateReferencePanel } from './TemplateReferencePanel'
import { TemplateComponentHelp } from './TemplateComponentHelp'
import { animationDef, controlsForCard, findKitAnimationBySheet, localized, type Localized } from '../../lib/characterAnimations'
import { useCharacterKitLibrary } from '../characters/useCharacterKitLibrary'

const SLOT_COPY = {
  subject_1: 'composer.slot.subject_1',
  subject_2: 'composer.slot.subject_2',
  background: 'composer.slot.background',
  prop_1: 'composer.slot.prop_1',
  prop_2: 'composer.slot.prop_2',
  foreground: 'composer.slot.foreground',
} as const

/** Controls with their own fixed inputs; every other exposed control is drawn from its spec. */
const FIXED_CONTROLS = new Set(['duration', 'bpm', 'intensity'])
/** The cards that play a sheet from Characters › Animaciones: picking one fills the card's controls. */
const SHEET_CARDS: ReadonlySet<string> = new Set(['walk-cycle-sheet', 'character-reaction'])
const animationTitle = (id: string): Localized => animationDef(id)?.title ?? { es: id, en: id }
const CONTROL_NAMES = ['drift', 'camera', 'atmosphere', 'bounce', 'bouncer', 'outcome', 'mood', 'entrance', 'caption', 'yearFrom', 'yearTo', 'yearLabel', 'banner'] as const
const OPTION_NAMES = ['push', 'sweep', 'open', 'beat', 'fireflies', 'confetti', 'bokeh', 'on', 'off', 'subject', 'prop', 'miss', 'shield', 'explode', 'calm', 'lonely', 'leaves', 'streaks', 'rise', 'left', 'right'] as const
const isControlName = (name: string): name is (typeof CONTROL_NAMES)[number] => (CONTROL_NAMES as readonly string[]).includes(name)
const isOptionName = (name: string): name is (typeof OPTION_NAMES)[number] => (OPTION_NAMES as readonly string[]).includes(name)
const inputClass = 'mt-1 w-full rounded border border-border bg-bg-primary p-2 text-xs'

interface Props {
  workspace: string
  onClose: () => void
  onApply: (scene: Scene) => boolean
}

/** Mounted only while open: changing template/workspace discards stale bindings
 * and cancels pending catalog lookups, never a background generation request. */
export function TemplateComposerDialog({ workspace, onClose, onApply }: Props) {
  const { t } = useUiTranslation('scene3d')
  const [id, setId] = useState(COMPOSER_SCENE_TEMPLATES[0].id)
  const template = getCandidateSceneTemplate(id)
  return <ModalShell open title={t('composer.title')} onClose={onClose} className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-4">
    <div className="max-h-[90vh] w-[880px] max-w-full space-y-4 overflow-y-auto rounded-xl border border-border bg-bg-secondary p-4 text-text-primary">
      <header className="flex items-center justify-between gap-4"><h2 className="font-semibold">{t('composer.heading')}</h2><button type="button" onClick={onClose} className="rounded border border-border px-3 py-1">{t('composer.close')}</button></header>
      <p className="text-xs text-text-secondary">{t('composer.intro', { count: COMPOSER_SCENE_TEMPLATES.length })}</p>
      <label className="block text-xs">{t('composer.action')}
        <select aria-label={t('composer.action')} value={id} onChange={event => setId(event.target.value)} className={inputClass}>
          {COMPOSER_SCENE_TEMPLATES.map(item => <option key={item.id} value={item.id}>{item.family} · {item.title}</option>)}
        </select>
      </label>
      <TemplateComposerForm key={`${workspace}:${id}`} template={template} workspace={workspace} onClose={onClose} onApply={onApply} />
    </div>
  </ModalShell>
}

const defaults = (template: SceneTemplateDefinition) => Object.fromEntries(Object.entries(template.controls).map(([key, spec]) => [key, spec.default])) as Record<string, ControlValue>

function ControlField({ name, spec, value, onChange }: { name: string; spec: ControlSpec; value: ControlValue; onChange: (value: ControlValue) => void }) {
  const { t } = useUiTranslation('scene3d')
  const label = isControlName(name) ? t(`composer.control.${name}`) : name
  const option = (choice: string) => isOptionName(choice) ? t(`composer.option.${choice}`) : choice
  if (spec.kind === 'choice') {
    return <label className="text-xs">{label}<select aria-label={label} value={String(value)} onChange={event => onChange(event.target.value)} className={inputClass}>
      {spec.options.map(choice => <option key={choice} value={choice}>{option(choice)}</option>)}
    </select></label>
  }
  if (spec.kind === 'text') {
    return <label className="text-xs">{label}<input aria-label={label} type="text" maxLength={spec.maxLength} value={String(value)} onChange={event => onChange(event.target.value)} className={inputClass} /></label>
  }
  return <label className="text-xs">{label}<input aria-label={label} type="number" min={spec.min} max={spec.max} step={.1} value={Number(value)} onChange={event => onChange(Number(event.target.value))} className={inputClass} /></label>
}

function TemplateComposerForm({ template, workspace, onClose, onApply }: Props & { template: SceneTemplateDefinition }) {
  const { t, i18n } = useUiTranslation('scene3d')
  const [selections, setSelections] = useState<CatalogSelections>({})
  const [activeSlot, setActiveSlot] = useState<TemplateSlotName>(template.slots[0].id)
  const [values, setValues] = useState(() => defaults(template))
  const [replaceConfirmed, setReplaceConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const slot = template.slots.find(item => item.id === activeSlot)!
  const rhythmic = template.controls.bpm?.exposed === true
  const needed = new Set(requiredSlots(template, values).map(item => item.id))
  const missing = template.slots.some(item => needed.has(item.id) && !selections[item.id])
  const extraControls = Object.entries(template.controls).filter(([name, spec]) => spec.exposed && !FIXED_CONTROLS.has(name))
  const setValue = (name: string) => (value: ControlValue) => setValues(current => ({ ...current, [name]: value }))
  // A sheet made in Characters › Animaciones names how it plays: its poses, columns, pace and the way it looks.
  const { kits } = useCharacterKitLibrary(workspace, false, SHEET_CARDS.has(template.id))
  const made = SHEET_CARDS.has(template.id) ? findKitAnimationBySheet(kits, selections.subject_1?.filename) : undefined
  const madeKey = made ? `${made.kit.id}/${made.id}/${made.animation.sheet.source}` : ''
  useEffect(() => {
    if (made) setValues(current => ({ ...current, ...controlsForCard(made.animation, template.id, template.controls) }))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the sheet picked decides; edits to the controls after it are kept
  }, [madeKey, template.id])

  const apply = async () => {
    if (busy || missing || !replaceConfirmed) return
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    try {
      const bindings = await resolveCatalogBindings(template, selections, workspace, controller.signal, values)
      if (controller.signal.aborted) return
      const scene = compileCandidateScene(template.id, bindings, values)
      if (onApply(scene)) onClose()
      else setError(t('composer.reject'))
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : t('composer.createFailed'))
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  const openOriginal = async (file: File) => {
    if (busy || !replaceConfirmed) return
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    try {
      const scene = await importApprovedReference(file, template)
      if (!controller.signal.aborted && onApply(scene)) onClose()
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : t('composer.openOriginalFailed'))
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <div className="space-y-4">
    <p className="text-xs">{template.description}</p>
    <TemplateReferencePanel templateId={template.id} disabled={busy || !replaceConfirmed} onOpen={file => void openOriginal(file)} />
    <TemplateComponentHelp templateId={template.id} />
    <ul className="list-disc pl-5 text-xs text-text-muted">{template.limits.map(limit => <li key={limit}>{limit}</li>)}</ul>
    <fieldset disabled={busy} className="space-y-3 disabled:opacity-60">
      <legend className="mb-2 text-xs">{t('composer.assetsOf', { workspace })}</legend>
      <div className="grid gap-2 sm:grid-cols-2">{template.slots.map(item => <div key={item.id} className={`rounded border p-2 text-xs ${activeSlot === item.id ? 'border-cyan-400' : 'border-border'}`}>
        <button type="button" aria-pressed={activeSlot === item.id} onClick={() => setActiveSlot(item.id)} className="block w-full text-left font-medium">{t(SLOT_COPY[item.id])} {needed.has(item.id) ? t('composer.required') : t('composer.optional')}</button>
        <p className="mt-1 font-mono text-cyan-200">{item.id} · {item.kinds.join(', ')}</p>
        <p className="mt-1 text-text-muted">{item.description}</p>
        <p className="mt-1 break-all">{selections[item.id]?.filename || t('composer.unassigned')}</p>
        {item.id === 'subject_1' && made && <p className="mt-1 text-emerald-200">{t('composer.fromAnimation', { animation: localized(animationTitle(made.id), i18n.language), character: made.kit.name })}</p>}
        {selections[item.id] && <><p className="break-all text-[10px] text-text-muted">ID: {selections[item.id]!.id}</p><button type="button" aria-label={t('composer.removeAria', { slot: t(SLOT_COPY[item.id]) })} onClick={() => setSelections(current => ({ ...current, [item.id]: undefined }))} className="mt-1 text-rose-200">{t('composer.remove')}</button></>}
      </div>)}</div>
      <p className="text-xs">{t('composer.assignHelp', { slot: t(SLOT_COPY[slot.id]) })}</p>
      <TemplateAssetPicker key={slot.id} workspace={workspace} kinds={slot.kinds} selected={selections[slot.id]} selectedId={selections[slot.id]?.id} optional={!needed.has(slot.id)} disabledReason={item => catalogBindingIssue(item, workspace, slot)} onPick={item => { setSelections(current => ({ ...current, [slot.id]: item })); setError('') }} onClear={() => setSelections(current => ({ ...current, [slot.id]: undefined }))} />
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-xs">{t('composer.duration')}<input aria-label={t('composer.duration')} type="number" min={3} max={12} step={1} value={Number(values.duration)} onChange={event => setValue('duration')(Number(event.target.value))} className={inputClass} /></label>
        <label className="text-xs">{t('composer.visualBpm')} {!rhythmic && '×'}<input aria-label={t('composer.visualBpm')} disabled={!rhythmic} type="number" min={40} max={220} value={Number(values.bpm)} onChange={event => setValue('bpm')(Number(event.target.value))} className={inputClass} /></label>
        <label className="text-xs">{t('composer.pulseIntensity')} {!rhythmic && '×'}<input aria-label={t('composer.pulseIntensity')} disabled={!rhythmic} type="number" min={0} max={1} step={.1} value={Number(values.intensity)} onChange={event => setValue('intensity')(Number(event.target.value))} className={inputClass} /></label>
      </div>
      {extraControls.length > 0 && <div className="grid gap-3 sm:grid-cols-3">{extraControls.map(([name, spec]) => <ControlField key={name} name={name} spec={spec} value={values[name]} onChange={setValue(name)} />)}</div>}
      <p className="text-xs text-text-muted">{rhythmic ? t('composer.pulseHelp') : t('composer.noPulseHelp')}</p>
      <p className="text-xs text-amber-100">{t('composer.stillWarning')}</p>
      <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={replaceConfirmed} onChange={event => setReplaceConfirmed(event.target.checked)} />{t('composer.replaceConfirm')}</label>
    </fieldset>
    {error && <p role="alert" className="text-xs text-rose-200">{error}</p>}
    <button type="button" onClick={() => void apply()} disabled={busy || missing || !replaceConfirmed} className="rounded border border-cyan-300/50 bg-cyan-400/10 px-4 py-2 text-sm disabled:opacity-40">{busy ? t('composer.checking') : t('composer.createOpen')}</button>
  </div>
}
