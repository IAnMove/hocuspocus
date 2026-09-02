import { useRef } from 'react'
import {
  BookOpen, Download, ImagePlus, Loader2, Plus, Sparkles, Trash2, Upload,
} from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { StoryLibraryConflictNotice } from './StoryLibraryConflictNotice'
import { button, input, requiredPreparationButton } from './storyLabChrome'
import { storyProjectTypes } from './storyLabTabs'
import type { StoryLibraryConflict } from './library'
import type { StoryGenerationScope, StoryProject, StoryProjectType } from './types'

const PREPARE_TEXT = {
  full_story: 'library.prepareTextFullStory',
  music_video: 'library.prepareTextMusicVideo',
  trailer: 'library.prepareTextTrailer',
  quick_video: 'library.prepareTextQuickVideo',
} as const

const PREPARE_IMAGES = {
  full_story: 'library.prepareImagesFullStory',
  music_video: 'library.prepareImagesMusicVideo',
  trailer: 'library.prepareImagesTrailer',
  quick_video: 'library.prepareImagesQuickVideo',
} as const

function StoryLabSaveStatus({
  loading, saveError, dirty, hydrated,
}: {
  loading: boolean
  saveError: string | null
  dirty: boolean
  hydrated: boolean
}) {
  const { t } = useUiTranslation('storyLab')
  if (loading) return <span className="text-[9px] text-text-muted">{t('library.saveLoading')}</span>
  if (saveError) return <span className="text-[9px] text-red-300" title={saveError}>{t('library.saveLocalFallback')}</span>
  if (dirty) return <span className="text-[9px] text-amber-300">{t('library.saveSaving')}</span>
  if (hydrated) return <span className="text-[9px] text-emerald-400">{t('library.saveSaved')}</span>
  return <span className="text-[9px] text-text-muted">{t('library.saveCached')}</span>
}

function StoryLabPrepareButtons({
  projectType, needsPrep, busy, referenceBatchBusy, jobProgress, onPrepareText, onPrepareImages,
}: {
  projectType: StoryProjectType
  needsPrep: boolean
  busy: StoryGenerationScope | null
  referenceBatchBusy: boolean
  jobProgress: string
  onPrepareText: () => void
  onPrepareImages: () => void
}) {
  const { t } = useUiTranslation('storyLab')
  const className = `${button} ${needsPrep ? requiredPreparationButton : ''}`
  const preparing = Boolean(busy || referenceBatchBusy)
  return (
    <>
      <button className={className} onClick={onPrepareText} disabled={preparing} title={t('library.prepareTextTitle')}>
        {busy === 'all' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
        {jobProgress || t(PREPARE_TEXT[projectType])}
      </button>
      <button className={className} onClick={onPrepareImages} disabled={preparing} title={t('library.prepareImagesTitle')}>
        {busy === 'all' || referenceBatchBusy ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
        {t(PREPARE_IMAGES[projectType])}
      </button>
    </>
  )
}

function StoryLabNewProjectMenu({
  types, disabled, onNewProject,
}: {
  types: Array<{ id: StoryProjectType; label: string; description: string }>
  disabled: boolean
  onNewProject: (type: StoryProjectType) => void
}) {
  const { t } = useUiTranslation('storyLab')
  return (
    <details className="relative">
      <summary className={`${button} list-none cursor-pointer`}><Plus size={13} /> {t('library.new')}</summary>
      <div className="absolute right-0 z-40 mt-1 w-64 rounded-lg border border-border bg-bg-primary p-1.5 shadow-xl">
        {types.map(item => (
          <button key={item.id} type="button" disabled={disabled}
            className="block w-full rounded-md px-2.5 py-2 text-left hover:bg-bg-hover disabled:opacity-40"
            onClick={event => {
              onNewProject(item.id)
              const details = event.currentTarget.closest('details')
              details?.removeAttribute('open')
            }}>
            <span className="block text-xs font-medium text-text-primary">{item.label}</span>
            <span className="mt-0.5 block text-[9px] text-text-muted">{item.description}</span>
          </button>
        ))}
      </div>
    </details>
  )
}

export function StoryLabLibraryChrome({
  project, projects, activeWorkspace, progress, foundationTotal,
  storyLoading, storySaveError, dirty, storyHydrated, storyLibraryConflicts,
  resolveStoryLibraryConflict, busy, imageBusy, projectOperationBusy, referenceBatchBusy,
  jobProgress, showCancel, showResume, recoveryJobId, smartAssetBusy,
  onOpenProject, onProjectTypeChange, onWorkflowModeChange, onPrepareText, onPrepareImages,
  onCancel, onResume, onExportStorypack, onImport, onSmartAssets, onNewProject, onDuplicate, onDelete,
}: {
  project: StoryProject
  projects: Record<string, StoryProject>
  activeWorkspace: string
  progress: number
  foundationTotal: number
  storyLoading: boolean
  storySaveError: string | null
  dirty: boolean
  storyHydrated: boolean
  storyLibraryConflicts: StoryLibraryConflict[]
  resolveStoryLibraryConflict: (id: string, resolution: 'local' | 'remote') => void
  busy: StoryGenerationScope | null
  imageBusy: string
  projectOperationBusy: boolean
  referenceBatchBusy: boolean
  jobProgress: string
  showCancel: boolean
  showResume: boolean
  recoveryJobId: string
  smartAssetBusy: boolean
  onOpenProject: (id: string) => void
  onProjectTypeChange: (type: StoryProjectType) => void
  onWorkflowModeChange: (mode: StoryProject['workflowMode']) => void
  onPrepareText: () => void
  onPrepareImages: () => void
  onCancel: () => void
  onResume: () => void
  onExportStorypack: () => void
  onImport: (file?: File) => void
  onSmartAssets: () => void
  onNewProject: (type: StoryProjectType) => void
  onDuplicate: () => void
  onDelete: () => void
}) {
  const { t } = useUiTranslation('storyLab')
  const importRef = useRef<HTMLInputElement>(null)
  const types = storyProjectTypes(t)
  const description = types.find(item => item.id === project.projectType)?.description
  const libraryLocked = Boolean(busy || imageBusy || projectOperationBusy)
  const progressUnit = project.projectType === 'full_story' ? t('library.foundations') : t('library.requirements')
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-bg-secondary px-3 py-2">
      <div className="mr-auto">
        <div className="flex items-center gap-2">
          <BookOpen size={16} className="text-accent-blue" />
          <span className="text-sm font-semibold text-text-primary">{t('library.title')}</span>
          <span className="text-[10px] text-text-muted">
            {t('library.revisionProgress', {
              revision: project.revision, progress, total: foundationTotal, unit: progressUnit,
            })}
          </span>
          <StoryLabSaveStatus
            loading={storyLoading}
            saveError={storySaveError}
            dirty={dirty}
            hydrated={storyHydrated}
          />
        </div>
        <p className="text-[9px] text-text-muted mt-0.5">{description}</p>
        <StoryLibraryConflictNotice conflicts={storyLibraryConflicts} onResolve={resolveStoryLibraryConflict} />
        <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[9px]">
          <span className="inline-flex items-center gap-1.5 text-violet-200">
            <span className="h-2 w-2 rounded-full bg-violet-400 shadow-[0_0_8px_rgba(139,92,246,0.8)]" /> {t('library.legendRequired')}
          </span>
          <span className="inline-flex items-center gap-1.5 text-emerald-200">
            <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.8)]" /> {t('library.legendComplete')}
          </span>
        </div>
      </div>
      <select
        className={`${input} w-44`}
        value={project.id}
        disabled={libraryLocked}
        title={t('library.libraryTitle', { workspace: activeWorkspace })}
        onChange={event => onOpenProject(event.target.value)}
      >
        {Object.values(projects)
          .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
          .map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      <select
        className={`${input} w-40`}
        value={project.projectType}
        disabled={libraryLocked}
        title={t('library.projectTypeTitle')}
        onChange={event => onProjectTypeChange(event.target.value as StoryProjectType)}
      >
        {types.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
      <select
        className={`${input} w-auto`}
        value={project.workflowMode}
        onChange={event => onWorkflowModeChange(event.target.value as StoryProject['workflowMode'])}
      >
        <option value="guided">{t('library.workflowGuided')}</option>
        <option value="automatic">{t('library.workflowAutomatic')}</option>
      </select>
      <StoryLabPrepareButtons
        projectType={project.projectType}
        needsPrep={progress < foundationTotal}
        busy={busy}
        referenceBatchBusy={referenceBatchBusy}
        jobProgress={jobProgress}
        onPrepareText={onPrepareText}
        onPrepareImages={onPrepareImages}
      />
      {showCancel && (
        <button className={`${button} border-red-500/50 text-red-300`} onClick={onCancel}>
          {t('library.cancel')}
        </button>
      )}
      {showResume && (
        <button className={button} onClick={onResume} disabled={Boolean(busy)} title={t('library.resumeTitle', { jobId: recoveryJobId })}>
          {t('library.resume')}
        </button>
      )}
      <button className={button} onClick={onExportStorypack}><Download size={13} /> {t('library.storypack')}</button>
      <button className={button} onClick={() => importRef.current?.click()}><Upload size={13} /> {t('library.import')}</button>
      <button className={button} disabled={smartAssetBusy} onClick={onSmartAssets} title={t('library.smartAssetsTitle')}>
        {smartAssetBusy ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />} {t('library.smartAssets')}
      </button>
      <StoryLabNewProjectMenu types={types} disabled={libraryLocked} onNewProject={onNewProject} />
      <button className={button} disabled={libraryLocked} onClick={onDuplicate} title={t('library.duplicateTitle')}>{t('library.duplicate')}</button>
      <button className={button} onClick={() => {
        if (window.confirm(t('library.deleteConfirm', { title: project.title }))) onDelete()
      }} disabled={libraryLocked} title={t('library.deleteTitle')}><Trash2 size={13} /></button>
      <input ref={importRef} type="file" accept=".storypack,.zip,.json" className="hidden"
        onChange={event => {
          onImport(event.target.files?.[0])
          event.target.value = ''
        }} />
    </div>
  )
}
