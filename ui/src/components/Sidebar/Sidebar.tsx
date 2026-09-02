import { useEffect, useRef, useState } from 'react'
import { X, Globe, BookMarked, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
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
import { BlendControls } from './BlendControls'
import { AnchorReturnBanner } from './AnchorReturnBanner'
import { VoiceRefSection } from './VoiceRefSection'
import { ToolsPanel } from './ToolsPanel'
import { Hunyuan3DPanel } from './Hunyuan3DPanel'
import { HardwareStatusBar } from './HardwareStatusBar'
import { MiniMaxH3TurboToggle } from './MiniMaxH3TurboToggle'
import { PanoramaLoopPanel } from './PanoramaLoopPanel'
import { BrandIdentity } from '../BrandIdentity'
import { DirectorChat } from './DirectorChat'
import { useUiTranslation } from '../../i18n'

export function Sidebar() {
  const { t } = useUiTranslation('navigation')
  const [toolsCollapsed, setToolsCollapsed] = useState(() =>
    window.localStorage.getItem('hocuspocus-tools-sidebar-collapsed') === 'true')
  const generationMode = useStore(s => s.generationMode)
  const imageMode = useStore(s => s.params.image_mode)
  const modelOptions = useStore(s => s.modelOptions)
  const sidebarOpen = useStore(s => s.sidebarOpen)
  const appVersion = useStore(s => s.systemConfig?.app_version)
  const setSidebarOpen = useStore(s => s.setSidebarOpen)
  const setSidebarMode = useStore(s => s.setSidebarMode)
  const sidebarMode = useStore(s => s.sidebarMode)
  const setSettingsOpen = useStore(s => s.setSettingsOpen)
  const editSubMode = useStore(s => s.editSubMode)
  const modelType = useStore(s => s.params.model_type)
  const openLoraBrowser = useStore(s => s.setLoraBrowserOpen)
  const isMobile = useIsMobile()

  const isVideo = generationMode === 'video'
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
    setToolsCollapsed(collapsed)
    window.localStorage.setItem('hocuspocus-tools-sidebar-collapsed', String(collapsed))
  }

  useEffect(() => {
    const openStudio = () => {
      setSidebarMode('studio')
      setToolsSidebarCollapsed(false)
      setSidebarOpen(true)
    }
    const openSettings = () => {
      setSidebarOpen(false)
      setSettingsOpen(true)
    }
    const openDirector = () => {
      setSidebarMode('director')
      setToolsSidebarCollapsed(false)
      setSidebarOpen(true)
    }
    window.addEventListener('hocuspocus:studio-open', openStudio)
    window.addEventListener('hocuspocus:settings-open', openSettings)
    window.addEventListener('maestro:director-open', openDirector)
    return () => {
      window.removeEventListener('hocuspocus:studio-open', openStudio)
      window.removeEventListener('hocuspocus:settings-open', openSettings)
      window.removeEventListener('maestro:director-open', openDirector)
    }
  // The event bridge deliberately tracks stable Zustand actions only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
          <RecastControls />
          <PromptInput />
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
        {/* Tools mode: standalone post-processing (upscale / revoice) on any
            existing clip. Renders in place of the generation controls. */}
        {isTools ? <ToolsPanel /> : isModel3d ? <Hunyuan3DPanel /> : (
        <>
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
        {/* Frames (image_mode 0) AND Extend (image_mode 3) both use the unified
            InputsPanel. In Extend mode its first tile is the source video to
            continue from; otherwise it's the start frame. */}
        {isVideo && !isOmniReference && !isMultiClip && !isBlend && (
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
        {!isEdit && !isAudio && !(isVideo && (imageMode === 0 || imageMode === 3)) && modelOptions?.audio_prompt_type_sources && <AudioModeSection />}

        {/* Audio mode: sub-mode toggle + mode-specific controls */}
        {isAudio && <AudioSubModeToggle />}
        {isAudio && audioSubMode === 'speech' && modelOptions?.audio_prompt_type_sources && <AudioModeSection />}
        {isAudio && audioSubMode === 'sfx' && <SfxControls />}
        {isAudio && audioSubMode === 'mixer' && <MixerControls />}
        {isAudio && audioSubMode === 'music' && <MusicControls />}

        {/* Prompt area (non-edit modes, skip for SFX/Mixer/Music which have their own UI) */}
        {!isEdit && !(isAudio && (audioSubMode === 'sfx' || audioSubMode === 'mixer' || audioSubMode === 'music')) && (isMultiClip ? <MultiClipEditor /> : <PromptInput />)}

        {/* Video: reference images below prompt. In Frames mode the InputsPanel
            renders them as ordered tiles instead. */}
        {isVideo && !isOmniReference && imageMode !== 0 && imageMode !== 3 && modelOptions?.image_ref_choices && <ImageRefSection />}

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
          <div className="shrink-0">
            <GenerateButton />
          </div>
        </div>
      </div>
      )}
    </>
  )

  // Mobile: overlay drawer
  if (isMobile) {
    return (
      <>
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-black/40 z-40"
            onClick={() => setSidebarOpen(false)}
          />
        )}
        <aside className={`fixed top-0 left-0 h-full w-[380px] max-w-[85vw] bg-bg-secondary border-r border-border z-50 flex flex-col transform transition-transform duration-300 ease-in-out ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}>
          {/* Header */}
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <BrandIdentity appVersion={appVersion} />
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setSidebarOpen(false)}
                className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
              >
                <X size={16} />
              </button>
            </div>
          </div>
          {isDirector ? <DirectorChat /> : studioControls}
          <HardwareStatusBar />
        </aside>
      </>
    )
  }

  if (toolsCollapsed) {
    return (
      <aside className="w-11 h-full bg-bg-secondary border-r border-border flex flex-col items-center shrink-0">
        <button
          onClick={() => setToolsSidebarCollapsed(false)}
          className="m-1.5 p-2 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
          title="Expand Studio tools"
          aria-label="Expand Studio tools"
        >
          <PanelLeftOpen size={17} />
        </button>
        <span className="mt-2 text-[10px] uppercase tracking-[0.2em] text-text-muted [writing-mode:vertical-rl]">
          {panelTitle}
        </span>
      </aside>
    )
  }

  // Desktop: static sidebar
  return (
    <aside className="w-[420px] h-full bg-bg-secondary border-r border-border flex flex-col shrink-0">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <BrandIdentity appVersion={appVersion} />
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-text-secondary">{panelTitle}</span>
          <button
            onClick={() => setToolsSidebarCollapsed(true)}
            className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
            title="Collapse Studio tools"
            aria-label="Collapse Studio tools"
          >
            <PanelLeftClose size={16} />
          </button>
        </div>
      </div>
      {isDirector ? <DirectorChat /> : studioControls}
      <HardwareStatusBar />
    </aside>
  )
}
