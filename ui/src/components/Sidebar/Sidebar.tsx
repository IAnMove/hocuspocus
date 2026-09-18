import { lazy, Suspense, useEffect, useRef } from 'react'
import { Globe, BookMarked } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useIsMobile } from '../../lib/useIsMobile'
import { InputsPanel } from './InputsPanel'
import { OmniReferenceSection } from './OmniReferenceSection'
import { PromptInput } from './PromptInput'
import { ImageRefSection } from './ImageRefSection'
import { AudioModeSection } from './AudioModeSection'
import { MusicControls } from './MusicControls'
import { AudioSubModeToggle } from './AudioSubModeToggle'
import { SfxControls } from './SfxControls'
import { MixerControls } from './MixerControls'
import { ModeToggle } from './ModeToggle'
import { DurationSlider } from './DurationSlider'
import { AdvancedSettings } from './AdvancedSettings'
import { GenerateButton } from './GenerateButton'
import { ModelSelector } from './ModelSelector'
import { MultiClipEditor } from './MultiClipEditor'
import { EditSubModeToggle } from './EditSubModeToggle'
import { RestyleControls } from './RestyleControls'
import { InpaintControls } from './InpaintControls'
import { OutpaintControls } from './OutpaintControls'
import { RetakeControls } from './RetakeControls'
import { EditAnythingControls } from './EditAnythingControls'
import { RecastControls } from './RecastControls'
import { WangpModelControls } from './WangpModelControls'
import { BlendControls } from './BlendControls'
import { AnchorReturnBanner } from './AnchorReturnBanner'
import { VoiceRefSection } from './VoiceRefSection'
import { Hunyuan3DPanel } from './Hunyuan3DPanel'
import { HardwareStatusBar } from './HardwareStatusBar'
import { H3PromptControls } from './H3PromptControls'
import { MiniMaxH3TurboToggle } from './MiniMaxH3TurboToggle'
import { PanoramaLoopPanel } from './PanoramaLoopPanel'

import { useUiTranslation } from '../../i18n'
import { StudioCommandPanels } from '../../features/studio/StudioCommandPanels'

const ViggleControls = lazy(() => import('./ViggleControls').then(module => ({ default: module.ViggleControls })))
const ToolsPanel = lazy(() => import('./ToolsPanel').then(module => ({ default: module.ToolsPanel })))

export function DirectGenerationWorkspace() {
  const { t } = useUiTranslation('navigation')
  const { t: tCommon } = useUiTranslation('common')
  const { t: tStudio } = useUiTranslation('studio')
  const generationMode = useStore(s => s.generationMode)
  const imageMode = useStore(s => s.params.image_mode)
  const modelOptions = useStore(s => s.modelOptions)
  const sidebarOpen = useStore(s => s.sidebarOpen)
  const sidebarMode = useStore(s => s.sidebarMode)
  const editSubMode = useStore(s => s.editSubMode)
  const modelType = useStore(s => s.params.model_type)
  const workspace = useStore(s => s.activeWorkspace)
  const studioUnobscured = useStore(s => !s.settingsOpen && !s.dashboardOpen)
  const openLoraBrowser = useStore(s => s.setLoraBrowserOpen)
  const isMobile = useIsMobile()

  const isVideo = generationMode === 'video'
  const isAdvancedH3 = String(modelType).startsWith('h3_advanced')
  const isImage = generationMode === 'image'
  const isAudio = generationMode === 'audio'
  const isModel3d = generationMode === 'model3d'
  const audioSubMode = useStore(s => s.audioSubMode)
  const isEdit = generationMode === 'avatar'
  const isTools = generationMode === 'tools'
  const isDirector = sidebarMode === 'director'
  const isRetake = isEdit && editSubMode === 'retake'
  const isRestyle = isEdit && editSubMode === 'restyle'
  const isInpaint = isEdit && editSubMode === 'inpaint'
  const isOutpaint = isEdit && editSubMode === 'outpaint'
  const isEditAnything = isEdit && editSubMode === 'edit_anything'
  const isRecast = isEdit && editSubMode === 'recast'
  const isOmniReference = isVideo && modelOptions?.omni_reference === true
  const isMultiClip = isVideo && !isOmniReference && imageMode === 2
  const isContinue = isVideo && !isOmniReference && imageMode === 3
  const isBlend = isVideo && !isOmniReference && imageMode === 4
  const isI2vOnly = modelOptions?.i2v_class && !modelOptions?.t2v_class
  const directModeLabel = {
    image: t('directModes.image'),
    video: t('directModes.video'),
    audio: t('directModes.audio'),
    model3d: t('directModes.model3d'),
    avatar: t('directModes.avatar'),
    tools: t('directModes.tools'),
  }[generationMode]
  const panelTitle = isDirector ? t('panel.director') : `${t('panel.directGeneration')} · ${directModeLabel}`
  const previousToolContext = useRef(`${generationMode}:${editSubMode}`)
  const setToolsSidebarCollapsed = (collapsed: boolean) => {
    window.localStorage.setItem('hocuspocus-tools-sidebar-collapsed', String(collapsed))
  }

  useEffect(() => {
    const context = `${generationMode}:${editSubMode}`
    if (context !== previousToolContext.current) setToolsSidebarCollapsed(false)
    previousToolContext.current = context
  }, [editSubMode, generationMode])

  // Edit mode sub-controls based on sub-mode
  const editControls = (
    <>
      {isRetake && (
        <>
          <RetakeControls />
          <PromptInput />
        </>
      )}
      {isInpaint && (
        <>
          <InpaintControls />
          <PromptInput />
        </>
      )}
      {isOutpaint && (
        <>
          <OutpaintControls />
          <PromptInput />
        </>
      )}
      {isRestyle && (
        <>
          <RestyleControls />
          <PromptInput />
        </>
      )}
      {isEditAnything && (
        <>
          <EditAnythingControls />
          <PromptInput />
        </>
      )}
      {isRecast && (
        <>
          {modelType === 'viggle_animate'
            ? <Suspense fallback={<div role="status">Viggle-Animate…</div>}><ViggleControls /></Suspense>
            : <><RecastControls /><PromptInput /></>}
        </>
      )}
    </>
  )

  const studioControls = (
    <>
      {/* Edit Anything/Recast → Image Mode round-trip banner. Visible while
          a boundary anchor or Recast reference is being edited; null otherwise. */}
      <AnchorReturnBanner />

      {/* [&>*]:shrink-0 — keep every section at its natural height and let
          the column SCROLL when space is tight (e.g. ID-LoRA voice section
          added + hardware bar expanded), instead of letting flex-shrink
          crush sections into each other. */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4 min-h-0 [&>*]:shrink-0">
        <p className="text-xs text-text-secondary">{tStudio('groups.help')}</p>
        {/* Tools mode: standalone post-processing (upscale / revoice) on any
            existing clip. Renders in place of the generation controls. */}
        {isTools ? <Suspense fallback={<div role="status">{tCommon('status.loading')}</div>}>
          <ToolsPanel />
        </Suspense> : isModel3d ? <Hunyuan3DPanel /> : (
        <>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">{tStudio('groups.input')}</h3>
        {/* Edit mode: sub-mode toggle + sub-controls */}
        {isEdit && <EditSubModeToggle />}
        {isEdit && editControls}

        {/* Video mode */}
        {isVideo && !isOmniReference && <ModeToggle />}
        {/* Blend mode manages its own duration (overlap_sec) and its own
            start/end anchors — so the generic Duration slider and
            start/end ImageUpload don't apply there. */}
        {isVideo && !isBlend && <DurationSlider />}
        {isVideo && <MiniMaxH3TurboToggle />}
        {isVideo && <H3PromptControls />}
        <WangpModelControls />
        {/* Frames (image_mode 0) AND Extend (image_mode 3) both use the unified
            InputsPanel. In Extend mode its first tile is the source video to
            continue from; otherwise it's the start frame. */}
        {isVideo && !isAdvancedH3 && !isOmniReference && !isMultiClip && !isBlend && (
          <div>
            {isI2vOnly && !isContinue && (
              <div className="text-[10px] text-indicator-warning bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-1.5 mb-2">
                This model requires a start image to generate video.
              </div>
            )}
            <InputsPanel />
          </div>
        )}
        {isOmniReference && <OmniReferenceSection />}
        {isBlend && <BlendControls />}

        {/* Image mode: reference images */}
        {isImage && modelOptions?.image_ref_choices && <ImageRefSection />}
        {isImage && <PanoramaLoopPanel />}

        {/* Video/Image mode: audio controls (soundtrack, control video, etc.).
            In Frames mode (video, image_mode 0) the unified InputsPanel routes
            audio/control-video via tiles instead, so the dropdown is hidden
            there. Other video sub-modes + image mode keep AudioModeSection. */}
        {!isAdvancedH3 && !isEdit && !isAudio && !(isVideo && (imageMode === 0 || imageMode === 3)) && modelOptions?.audio_prompt_type_sources && <AudioModeSection />}

        {/* Audio mode: sub-mode toggle + mode-specific controls */}
        {isAudio && <AudioSubModeToggle />}
        {isAudio && audioSubMode === 'speech' && modelOptions?.audio_prompt_type_sources && <AudioModeSection />}
        {isAudio && audioSubMode === 'sfx' && <SfxControls />}
        {isAudio && audioSubMode === 'mixer' && <MixerControls />}
        {isAudio && audioSubMode === 'music' && <MusicControls />}

        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">{tStudio('groups.instructions')}</h3>
        {/* Prompt area (non-edit modes, skip for SFX/Mixer/Music which have their own UI) */}
        {!isEdit && !(isAudio && (audioSubMode === 'sfx' || audioSubMode === 'mixer' || audioSubMode === 'music')) && (isMultiClip ? <MultiClipEditor /> : <PromptInput />)}
        <StudioCommandPanels mode={generationMode} audioSubMode={audioSubMode}
          workspace={workspace || 'default'} model={String(modelType)}
          visible={studioUnobscured && (!isMobile || sidebarOpen)} />

        {/* Video: reference images below prompt. In Frames mode the InputsPanel
            renders them as ordered tiles instead. */}
        {isVideo && !isAdvancedH3 && !isOmniReference && imageMode !== 0 && imageMode !== 3 && modelOptions?.image_ref_choices && <ImageRefSection />}

        {/* Voice Reference (ID-LoRA) — gated by Settings → Services
            toggle (`voice_reference_enabled`). VoiceRefSection internally
            no-ops when the toggle is off. We render it for Studio Video
            mode (basic, multi-clip, continue, blend) — it's the same
            generation path that consumes `directorVoiceRef` server-side.
            Director mode renders its own copy in DirectorChat. */}
        {isVideo && !isOmniReference && imageMode !== 0 && imageMode !== 3 && <VoiceRefSection />}
        </>
        )}
      </div>

      {/* Bottom Bar: Advanced + LoRA Browser + Model + Generate.
          Hidden in Tools mode — ToolsPanel has its own Run button and
          owns no model. */}
      {!isTools && !isModel3d && (
      <div className="px-3 py-2.5 border-t border-border">
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">{tStudio('groups.model')} · {tStudio('groups.run')}</h3>
        <div className="flex items-center gap-2">
          <AdvancedSettings />
          <button
            onClick={() => useStore.getState().setRecipesOpen(true)}
            className="p-2 rounded-lg bg-bg-tertiary border border-border hover:border-border-light text-text-secondary hover:text-accent-blue transition-colors shrink-0"
            title="Recipes — one-click presets"
          >
            <BookMarked size={14} />
          </button>
          {!isOutpaint && (
            <button
              onClick={() => openLoraBrowser(true, modelType)}
              className="p-2 rounded-lg bg-bg-tertiary border border-border hover:border-border-light text-text-secondary hover:text-accent-blue transition-colors shrink-0"
              title="Browse LoRAs on CivitAI"
            >
              <Globe size={14} />
            </button>
          )}
          <div className="flex-1 min-w-0">
            <ModelSelector />
          </div>
          {!(isAudio && audioSubMode === 'mixer') && (
            <div className="shrink-0">
              <GenerateButton />
            </div>
          )}
        </div>
      </div>
      )}
    </>
  )

  return (
    <section data-testid="direct-generation-workspace" className="flex h-full min-h-0 flex-col bg-bg-secondary" aria-label={panelTitle}>
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-text-primary">{panelTitle}</h2>
      </header>
      {studioControls}
      <HardwareStatusBar />
    </section>
  )
}

export function Sidebar() {
  return <DirectGenerationWorkspace />
}
