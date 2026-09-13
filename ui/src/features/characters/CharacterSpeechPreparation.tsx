import { useState } from 'react'
import { LabsLibraryPick } from '../../lib/LabsLibraryPick'
import { useUiTranslation } from '../../i18n'
import { speechPreparationReadiness } from '../../lib/characterSpeechPreparation'
import type { CharacterKit, CharacterKitLibrary } from '../../lib/characterKit'
import { CharacterKitFaceRigPanel } from './CharacterKitFaceRigPanel'
import { characterKitPoseOptions } from './characterKitGuide'
import { speechLibraryServices, useCharacterSpeechLibrary, type SpeechLibraryServices } from './useCharacterSpeechLibrary'

type Props = { workspace: string; services?: SpeechLibraryServices; initialKitId?: string; onSaved?: (library: CharacterKitLibrary) => void }
type Controller = ReturnType<typeof useCharacterSpeechLibrary>
const button = 'rounded border border-border px-3 py-2 text-xs text-text-primary disabled:opacity-40'

export function CharacterSpeechPreparation(props: Props) {
  return <SpeechWorkspace key={props.workspace + '/' + (props.initialKitId ?? '')} {...props} />
}

function SpeechWorkspace({ workspace, services = speechLibraryServices, initialKitId, onSaved }: Props) {
  const { t } = useUiTranslation('characters')
  const controller = useCharacterSpeechLibrary(workspace, services, initialKitId, onSaved)
  const { library, draft, busy, dirty } = controller

  return <section aria-label={t('speechWorkshop.title')} className="space-y-3 rounded-lg border border-violet-400/30 bg-bg-secondary p-3">
    <h3 className="text-sm font-semibold text-text-primary">{t('speechWorkshop.title')}</h3>
    <p className="text-xs text-text-secondary">{t('speechWorkshop.intro')}</p>
    <details className="rounded border border-border p-2">
    <summary className="cursor-pointer text-xs text-text-secondary">{t('speechWorkshop.alternatives')}</summary>
    <div className="mt-2 grid gap-2 text-xs" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 180px), 1fr))' }}>
      {(['sprites', 'patches', 'software'] as const).map(method => <div key={method} className="rounded border border-border p-2">
        <h4 className="font-medium text-text-primary">{t(`speechWorkshop.methods.${method}.title`)}</h4>
        <p className="mt-1 text-text-secondary">{t(`speechWorkshop.methods.${method}.detail`)}</p>
      </div>)}
    </div>
    </details>
    <p className="text-xs text-amber-200">{t('speechWorkshop.manualOnly')}</p>
    <label className="block text-xs text-text-secondary">{t('speechWorkshop.character')}
      <select aria-label={t('speechWorkshop.character')} disabled={Boolean(initialKitId) || busy || dirty || !library} value={draft?.id ?? ''} onChange={event => controller.select(event.target.value)} className="mt-1 w-full rounded border border-border bg-bg-primary p-2">
        <option value="">{t('speechWorkshop.choose')}</option>
        {Object.values(library?.kits ?? {}).map(kit => <option key={kit.id} value={kit.id}>{kit.name}</option>)}
        {draft && !library?.kits[draft.id] && <option value={draft.id}>{draft.name}</option>}
      </select>
    </label>
    {!initialKitId && <ImportSpeechBase workspace={workspace} controller={controller} />}
    {draft && <SpeechDraftEditor key={draft.id} kit={draft} workspace={workspace} controller={controller} />}
    <div className="flex flex-wrap gap-2">
      <button type="button" className={button} disabled={busy || !dirty || !draft?.base} onClick={controller.save}>{t('speechWorkshop.save')}</button>
      <button type="button" className={button} disabled={busy} onClick={controller.reload}>{t(dirty ? 'speechWorkshop.discardReload' : 'speechWorkshop.reload')}</button>
    </div>
    {dirty && <p className="text-xs text-amber-200">{t('speechWorkshop.unsaved')}</p>}
    {busy && <p role="status" className="text-xs text-text-secondary">{t('speechWorkshop.busy')}</p>}
    {controller.status && <p role="status" className="text-xs text-emerald-200">{controller.status}</p>}
    {controller.error && <p role="alert" className="text-xs text-red-300">{controller.error} {t('speechWorkshop.errorHint')}</p>}
  </section>
}

function ImportSpeechBase({ workspace, controller }: { workspace: string; controller: Controller }) {
  const { t } = useUiTranslation('characters')
  const { busy, dirty, library } = controller
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  return <details className="rounded border border-border p-2">
      <summary className="cursor-pointer text-xs text-text-primary">{t('speechWorkshop.newCharacter')}</summary>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <label className="text-xs text-text-secondary">{t('speechWorkshop.name')}<input aria-label={t('speechWorkshop.name')} disabled={busy || dirty} value={name} onChange={event => setName(event.target.value)} className="mt-1 block rounded border border-border bg-bg-primary p-2" /></label>
        <label className="text-xs text-text-secondary">{t('speechWorkshop.baseImage')}<input aria-label={t('speechWorkshop.baseImage')} type="file" accept="image/png,image/jpeg,image/webp" disabled={busy || dirty} onChange={event => setFile(event.target.files?.[0] ?? null)} className="mt-1 block max-w-full" /></label>
        <LabsLibraryPick workspace={workspace} disabled={busy || dirty} onFile={setFile} />
        <button type="button" disabled={busy || dirty || !library || !name.trim() || !file} onClick={() => { if (file) controller.importBase(name, file) }} className={button}>{t('speechWorkshop.importBase')}</button>
      </div>
      <p className="mt-2 text-xs text-text-muted">{t('speechWorkshop.importHint')}</p>
    </details>
}

function SpeechDraftEditor({ kit: draft, workspace, controller }: { kit: CharacterKit; workspace: string; controller: Controller }) {
  const { t } = useUiTranslation('characters')
  const { busy } = controller
  const [poseId, setPoseId] = useState('base')
  const poses = characterKitPoseOptions(draft)
  const currentPoseId = poses.some(pose => pose.id === poseId) ? poseId : poses[0]?.id ?? 'base'
  const pose = currentPoseId === 'base' ? draft.base : draft.poses[currentPoseId]
  const readiness = speechPreparationReadiness(draft, currentPoseId)
  const approvePose = () => {
    if (!pose || busy) return
    const approved = { ...pose, reviewState: 'approved' as const }
    controller.change(currentPoseId === 'base' ? { ...draft, base: approved } : { ...draft, poses: { ...draft.poses, [currentPoseId]: approved } })
  }
  return <>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-text-secondary">{t('speechWorkshop.pose')}<select aria-label={t('speechWorkshop.pose')} disabled={busy} value={currentPoseId} onChange={event => setPoseId(event.target.value)} className="ml-2 rounded border border-border bg-bg-primary p-2">
          {poses.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select></label>
        <button type="button" disabled={busy || !pose?.source || readiness.poseApproved} onClick={approvePose} className={button}>{t('speechWorkshop.approvePose')}</button>
      </div>
      <p className="text-xs text-amber-200">{t('speechWorkshop.singlePack')}</p>
      <ul aria-label={t('speechWorkshop.checklist')} className="flex flex-wrap gap-2 text-xs">
        {readiness.rows.map(row => <li key={row.state} className="rounded border border-border px-2 py-1">{t(`mouths.${row.state}`)}: {t(`speechWorkshop.states.${row.status}`)}</li>)}
      </ul>
      <p className="text-xs text-text-secondary">{t(readiness.previewReady ? 'speechWorkshop.previewReady' : 'speechWorkshop.previewNotReady')}</p>
      <div className="mx-auto max-w-xl rounded border border-border p-2">
        <CharacterKitFaceRigPanel key={`${draft.id}:${currentPoseId}`} kit={draft} poseId={currentPoseId} workspace={workspace} disabled={busy} allowModelActions={false} onChange={controller.change} onStatus={controller.setStatus} />
      </div>
    </>
}
