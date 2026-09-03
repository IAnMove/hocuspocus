import { Loader2, Trash2 } from 'lucide-react'
import type { CharacterKit, CharacterKitAlphaStatus, CharacterKitLibrary, CharacterMouthState } from '../../lib/characterKit'
import { useUiTranslation } from '../../i18n'
import { CharacterKitFaceRigPanel } from './CharacterKitFaceRigPanel'
import {
  characterKitNextStep,
  characterKitOpeningTab,
  characterKitPoseLabel,
  characterKitPoseOptions,
  type CharacterKitEditorTab,
} from './characterKitGuide'

type Props = {
  library: CharacterKitLibrary
  draft: CharacterKit | null
  poseId: string
  tab: CharacterKitEditorTab
  busy: boolean
  error: string | null
  newName: string
  alphaStatus: CharacterKitAlphaStatus
  mouthState: CharacterMouthState
  hasSelectedLayer: boolean
  selectedIsFace: boolean
  disabled?: boolean
  onSelectKit: (kit: CharacterKit, tab: CharacterKitEditorTab) => void
  onNewNameChange: (value: string) => void
  onCreateFromSelected: () => void
  onDraftChange: (kit: CharacterKit) => void
  onPoseIdChange: (poseId: string) => void
  onTabChange: (tab: CharacterKitEditorTab) => void
  onAlphaStatusChange: (status: CharacterKitAlphaStatus) => void
  onMouthStateChange: (state: CharacterMouthState) => void
  onAssignSelected: (slot: 'base' | 'pose' | 'mouth' | 'blink') => void
  onCaptureAnchor: () => void
  onSave: () => void
  onPutOnScene: () => void
  onDelete: () => void
  onClose: () => void
  onCommit?: (kit: CharacterKit) => void
  onStatus?: (message: string) => void
}

export function CharacterKitLibraryPanel({
  library,
  draft,
  poseId,
  tab,
  busy,
  error,
  newName,
  alphaStatus,
  mouthState,
  hasSelectedLayer,
  selectedIsFace,
  disabled = false,
  onSelectKit,
  onNewNameChange,
  onCreateFromSelected,
  onDraftChange,
  onPoseIdChange,
  onTabChange,
  onAlphaStatusChange,
  onMouthStateChange,
  onAssignSelected,
  onCaptureAnchor,
  onSave,
  onPutOnScene,
  onDelete,
  onClose,
  onCommit,
  onStatus,
}: Props) {
  const { t } = useUiTranslation('characters')
  const { t: tCommon } = useUiTranslation('common')
  const kits = Object.values(library.kits)
  const next = characterKitNextStep(draft, poseId)
  const poses = draft ? characterKitPoseOptions(draft) : []
  const locked = busy || disabled
  const nextTabLabel = next.tab === 'face-rig' ? t('library.tabs.mouthsEyes') : t('library.tabs.bodies')

  return (
    <div className="space-y-1.5 rounded border border-emerald-400/30 bg-emerald-400/[.04] p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-emerald-100">{t('library.title')}</span>
        <span className="text-[8px] text-emerald-200/75">{t('library.savedCount', { count: kits.length })}</span>
      </div>
      <p className="text-[10px] leading-relaxed text-text-secondary">
        {t('library.subtitle')}
      </p>
      {kits.length > 0 && (
        <div className="grid grid-cols-2 gap-1">
          {kits.map(kit => (
            <button
              key={kit.id}
              type="button"
              disabled={busy}
              onClick={() => onSelectKit(structuredClone(kit), characterKitOpeningTab(kit))}
              className={`overflow-hidden rounded border p-1 text-left ${draft?.id === kit.id ? 'border-emerald-300 bg-emerald-400/10' : 'border-border bg-black/10'}`}
            >
              {kit.base?.source && <img src={kit.base.source} alt="" className="mb-1 aspect-square w-full rounded bg-bg-active object-contain" />}
              <span className="block truncate text-[10px] text-emerald-100">{kit.name}</span>
              <span className="block text-[8px] text-text-muted">{t('library.bodyCount', { count: characterKitPoseOptions(kit).length })}</span>
            </button>
          ))}
        </div>
      )}
      {!draft && (
        <div className="space-y-1 rounded border border-border/70 bg-black/10 p-1.5">
          <p className="text-[9px] text-text-secondary">{t('library.newHint')}</p>
          <input value={newName} onChange={event => onNewNameChange(event.target.value)} placeholder={t('library.namePlaceholder')} className="w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]" />
          <button type="button" disabled={!hasSelectedLayer || busy} onClick={onCreateFromSelected} className="w-full rounded border border-emerald-300/40 bg-emerald-400/10 px-2 py-1 text-[10px] text-emerald-100 disabled:opacity-40">{t('library.createFromSelected')}</button>
        </div>
      )}
      {draft && (
        <div className="space-y-1.5 rounded border border-emerald-300/20 bg-black/10 p-1.5">
          <div className="rounded border border-amber-300/30 bg-amber-400/10 p-1.5">
            <p className="text-[10px] font-medium text-amber-100">{t('library.now', { title: next.title })}</p>
            <p className="mt-0.5 text-[9px] leading-relaxed text-amber-50/90">{next.detail}</p>
            {next.tab !== tab && (
              <button type="button" onClick={() => onTabChange(next.tab)} className="mt-1 w-full rounded border border-amber-200/50 px-1 py-1 text-[9px] text-amber-100">
                {t('library.goToTab', { tab: nextTabLabel })}
              </button>
            )}
          </div>
          <div className="grid grid-cols-[1fr_84px] gap-1">
            <input aria-label={t('library.nameAria')} value={draft.name} onChange={event => onDraftChange({ ...draft, name: event.target.value })} className="rounded border border-border bg-bg-primary px-1.5 py-1 text-[10px]" />
            <select aria-label={t('library.styleAria')} value={draft.style} onChange={event => onDraftChange({ ...draft, style: event.target.value as CharacterKit['style'] })} className="rounded border border-border bg-bg-primary px-1 py-1 text-[9px]">
              <option value="cutout">{t('library.styles.cutout')}</option>
              <option value="children-illustration">{t('library.styles.childrenIllustration')}</option>
              <option value="anime-2d">{t('library.styles.anime2d')}</option>
            </select>
          </div>
          {poses.length > 0 && (
            <div className="space-y-1">
              <p className="text-[9px] text-text-secondary">{t('library.editingBody')}</p>
              <div className="grid grid-cols-3 gap-1">
                {poses.map(pose => (
                  <button
                    key={pose.id}
                    type="button"
                    onClick={() => onPoseIdChange(pose.id)}
                    className={`overflow-hidden rounded border p-1 text-left ${poseId === pose.id ? 'border-emerald-300 bg-emerald-400/10' : 'border-border bg-black/10'}`}
                  >
                    {pose.source && <img src={pose.source} alt="" className="mb-0.5 aspect-square w-full rounded bg-bg-active object-contain" />}
                    <span className="block truncate text-[8px] text-emerald-100">{pose.label}</span>
                    <span className="block text-[7px] text-text-muted">{pose.approved ? t('library.ready') : t('library.pending')}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-1">
            <button type="button" onClick={() => onTabChange('kit')} className={`rounded border px-1 py-1 text-[9px] ${tab === 'kit' ? 'border-emerald-300 bg-emerald-400/10 text-emerald-100' : 'border-border text-text-muted'}`}>{t('library.tabs.bodies')}</button>
            <button type="button" onClick={() => onTabChange('face-rig')} className={`rounded border px-1 py-1 text-[9px] ${tab === 'face-rig' ? 'border-emerald-300 bg-emerald-400/10 text-emerald-100' : 'border-border text-text-muted'}`}>{t('library.tabs.mouthsEyes')}</button>
          </div>
          {tab === 'kit' ? (
            <details className="rounded border border-border/70 bg-black/10 px-1.5 py-1">
              <summary className="cursor-pointer text-[9px] text-text-muted">{t('library.advanced.summary')}</summary>
              <p className="mt-1 text-[8px] leading-relaxed text-text-secondary">{t('library.advanced.hint')}</p>
              <div className="mt-1 grid grid-cols-2 gap-1">
                <button type="button" disabled={!hasSelectedLayer} onClick={() => onAssignSelected('base')} className="rounded border border-border px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{t('library.advanced.mainBody')}</button>
                <button type="button" disabled={!hasSelectedLayer} onClick={() => onAssignSelected('pose')} className="rounded border border-border px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{t('library.advanced.otherPose', { pose: characterKitPoseLabel(poseId) })}</button>
                <select aria-label={t('library.advanced.mouthTypeAria')} value={mouthState} onChange={event => onMouthStateChange(event.target.value as CharacterMouthState)} className="rounded border border-border bg-bg-primary px-1 py-1 text-[8px]">
                  <option value="closed">{t('mouths.closed')}</option>
                  <option value="small">{t('mouths.small')}</option>
                  <option value="wide">{t('mouths.wide')}</option>
                  <option value="round">{t('mouths.round')}</option>
                </select>
                <button type="button" disabled={!hasSelectedLayer} onClick={() => onAssignSelected('mouth')} className="rounded border border-border px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{t('library.advanced.thisLayerMouth')}</button>
                <button type="button" disabled={!hasSelectedLayer} onClick={() => onAssignSelected('blink')} className="rounded border border-border px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{t('library.advanced.thisLayerBlink')}</button>
                <button type="button" disabled={!selectedIsFace} onClick={onCaptureAnchor} className="rounded border border-border px-1 py-1 text-[8px] text-emerald-100 disabled:opacity-40">{t('library.advanced.saveLayerPosition')}</button>
              </div>
              <label className="mt-1 block text-[8px] text-text-muted">{t('library.advanced.alphaWhenAssigning')}
                <select value={alphaStatus} onChange={event => onAlphaStatusChange(event.target.value as CharacterKitAlphaStatus)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-1 py-1 text-[8px]">
                  <option value="transparent">{t('alpha.transparent')}</option>
                  <option value="unknown">{t('alpha.unknown')}</option>
                  <option value="opaque">{t('alpha.opaque')}</option>
                </select>
              </label>
            </details>
          ) : (
            <CharacterKitFaceRigPanel kit={draft} poseId={poseId} disabled={locked} onChange={onDraftChange} onCommit={onCommit} onStatus={onStatus} />
          )}
          <div className="grid grid-cols-[1fr_1fr_24px] gap-1">
            <button type="button" disabled={locked || !draft.base} onClick={onSave} className="rounded border border-emerald-300/50 bg-emerald-400/10 px-1 py-1.5 text-[10px] text-emerald-100 disabled:opacity-40">{busy ? t('library.saving') : tCommon('actions.save')}</button>
            <button type="button" disabled={locked || !draft.base} onClick={onPutOnScene} className="rounded border border-emerald-300/50 bg-emerald-400/10 px-1 py-1.5 text-[10px] text-emerald-100 disabled:opacity-40">{t('library.putOnScene')}</button>
            <button type="button" title={t('library.deleteTitle')} disabled={locked || !library.kits[draft.id]} onClick={onDelete} className="rounded border border-red-400/30 text-red-300 disabled:opacity-30"><Trash2 size={11} className="mx-auto" /></button>
          </div>
          <button type="button" onClick={onClose} className="w-full text-[9px] text-text-muted">{tCommon('actions.close')}</button>
        </div>
      )}
      {busy && !draft && <p className="text-[9px] text-emerald-100"><Loader2 size={9} className="mr-1 inline animate-spin" />{t('library.loading')}</p>}
      {error && <p className="text-[9px] text-red-300">{error}</p>}
    </div>
  )
}
