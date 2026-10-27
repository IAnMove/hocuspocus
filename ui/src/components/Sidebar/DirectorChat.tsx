import { useFieldIds } from '../common/fieldIds'
import { controlLabel, controlReason, firstControlReason } from '../../i18n/controlLabel'
import { resolutionPresetLabel } from '../../lib/resolutionPresetLabel'
import { DirectorModelPicker } from './DirectorModelPicker'
import { lazy, Suspense, useState, useCallback, useRef, useMemo, useEffect } from 'react'
import { Upload, Loader2, Music, RotateCcw, Check, X, ChevronRight, ChevronDown, ImageIcon, Play, Film, Mic, Sparkles, Send, Users, FileText, Clock, BookOpen, Zap, Download } from 'lucide-react'
import { useStore, resolveResolution } from '../../stores/useStore'
import { fetchModelOptions } from '../../api/client'
import { MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { DirectorLoraSelector } from '../SettingsDrawer/DirectorLoraSelector'
import { DirectorSongSetup } from './DirectorSongSetup'
import { InfoTooltip } from './InfoTooltip'
import type { DirectorShotImageGuidance, DirectorSkill, ModelOptions, ShortFilmCharacter, ShortFilmPath } from '../../types'
import { formatSeconds, recommendedWindowProfile } from './DurationSlider'
import { DirectorClipImagePreview } from './DirectorClipImagePreview'
import { DirectorPlanRecoveryCard } from './DirectorPlanRecoveryCard'
import { MusicVideoTreatmentEditor, TreatmentSummary } from '../../features/director/MusicVideoTreatmentEditor'
import { useObjectUrl } from '../../lib/useObjectUrl'
import { useUiTranslation } from '../../i18n'
import { SpokenLanguageOptions } from '../../i18n/SpokenLanguageOptions'
import { visibleDirectorSkills } from './directorSkills'
import {
  directorChatPlaceholder,
  directorSendLabel,
  directorText,
  directorWillGenerateShotImages,
  imageGenStatusLine,
  imageSpinnerLabel,
  maxShotHint,
  planPhaseLabel,
  sectionDisplayName,
  shotGuidanceHint,
  videoStepsHint,
} from './directorChatLabels'

function AudioScaleSlider() {
  const { t } = useUiTranslation('director')
  const audioScale = useStore(s => s.directorAudioScale)
  const setAudioScale = useStore(s => s.setDirectorAudioScale)
  return (
    <>
      <span className="text-[10px] text-text-muted whitespace-nowrap">{t('chat.audioScale', { value: audioScale.toFixed(1) })}</span>
      <input
        aria-label={t('chat.audioScale', { value: audioScale.toFixed(1) })}
        type="range"
        min={0}
        max={5}
        step={0.1}
        value={audioScale}
        onChange={e => setAudioScale(parseFloat(e.target.value))}
        className="flex-1 h-1"
      />
      <div className="flex gap-2 text-[8px] text-text-muted">
        <span>{'1x' // i18n-ok: 1x
        }</span>
        <span>{t('chat.audioScaleTts')}</span>
        <span>{'5x' // i18n-ok: 5x
        }</span>
      </div>
    </>
  )
}

const ComicDirectorPanel = lazy(() => import('../../features/comics/ComicEditorPanel')
  .then(module => ({ default: module.ComicDirectorPanel })))

// AUDIO_ACCEPT lists both audio formats AND video formats. When a video
// file is uploaded, the backend's /api/v1/upload-audio endpoint extracts
// the audio track via ffmpeg and returns a WAV path. The user sees the
// same workflow either way — they can drop a music video here and get
// the soundtrack analyzed without converting first.
const AUDIO_ACCEPT = '.wav,.mp3,.flac,.ogg,.m4a,.mp4,.mov,.mkv,.webm,.avi,.m4v'
const IMAGE_ACCEPT = '.png,.jpg,.jpeg,.webp,.bmp'
const H3_VIDEO_ACCEPT = '.mp4,.mov,.mkv,.webm,.avi,.m4v'
const H3_AUDIO_ACCEPT = '.wav,.mp3,.flac,.ogg,.m4a'

const STEP_ORDER = ['upload', 'analyze', 'structure', 'style', 'plan', 'review', 'generate_images', 'plan_video', 'review_video'] as const
type DirectorStep = typeof STEP_ORDER[number]

function formatTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

const sectionColors: Record<string, string> = {
  intro: 'bg-blue-500/20 text-chip-blue',
  verse: 'bg-green-500/20 text-chip-green',
  'pre-chorus': 'bg-pink-500/20 text-chip-pink',
  chorus: 'bg-purple-500/20 text-chip-purple',
  bridge: 'bg-yellow-500/20 text-chip-yellow',
  outro: 'bg-gray-500/20 text-chip-gray',
  instrumental: 'bg-cyan-500/20 text-chip-cyan',
  // Short film scene types
  dialogue: 'bg-green-500/20 text-chip-green',
  action: 'bg-orange-500/20 text-chip-orange',
  opening: 'bg-blue-500/20 text-chip-blue',
  closing: 'bg-gray-500/20 text-chip-gray',
  scene: 'bg-teal-500/20 text-chip-teal',
}

const sectionBarColors: Record<string, string> = {
  intro: 'bg-blue-500',
  verse: 'bg-green-500',
  'pre-chorus': 'bg-pink-500',
  chorus: 'bg-purple-500',
  bridge: 'bg-yellow-500',
  outro: 'bg-gray-500',
  instrumental: 'bg-cyan-500',
  // Short film scene types
  dialogue: 'bg-green-500',
  action: 'bg-orange-500',
  opening: 'bg-blue-500',
  closing: 'bg-gray-500',
  scene: 'bg-teal-500',
}

/**
 * Textarea that auto-resizes its height to fit the content.
 *
 * Used for the per-clip image_prompt and video_prompt fields in the
 * Director chat review steps. Without this, long prompts produce a
 * scrollable inner textarea — and that textarea sits inside another
 * scrollable container, inside the chat panel which is itself
 * scrollable. The user has to triple-scroll to read a long prompt.
 *
 * With auto-resize the textarea grows to its full content height and
 * the only scroll is the parent chat panel's, matching the user's
 * "one scroll per surface" preference.
 *
 * Re-measures whenever `value` changes (controlled-component pattern):
 * setting height to 'auto' first lets it shrink as well as grow.
 *
 * `overflow-y: hidden` is forced via inline style so the textarea
 * never shows its own scrollbar — even when the browser would render
 * one defensively at the boundary between content height and box
 * height (Firefox especially does this). Without `hidden`, a wheel
 * event over the textarea gets captured by the textarea's would-be
 * scroll instead of bubbling up to the chat panel, so the user
 * can't scroll the chat when their cursor happens to be over a
 * prompt field.
 *
 * Optional `minHeight`/`maxHeight` (px) bound the growth — used by the
 * chat composer (issue #11), which keeps its resting 2-row size when
 * empty and stops growing at a cap. Past the cap the textarea scrolls
 * itself, so overflow flips to `auto` there; that's fine for the
 * composer because it sits OUTSIDE the scrollable chat panel — the
 * wheel-capture concern above doesn't apply.
 */
function AutoResizeTextarea({ minHeight, maxHeight, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  minHeight?: number
  maxHeight?: number
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    let h = el.scrollHeight
    if (minHeight) h = Math.max(h, minHeight)
    if (maxHeight) h = Math.min(h, maxHeight)
    el.style.height = `${h}px`
    if (maxHeight) el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [props.value, minHeight, maxHeight])
  // Merge any incoming style with our scrollbar-hiding override.
  // OUR override comes last so it wins — wheel-capture is the whole
  // point of the component, can't let a caller silently break it.
  const mergedStyle: React.CSSProperties = { ...(props.style || {}), overflowY: 'hidden' }
  return <textarea ref={ref} {...props} aria-label={props['aria-label'] ?? props.placeholder} style={mergedStyle} />
}

function SectionBadge({ label }: { label: string }) {
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${sectionColors[label] || 'bg-bg-hover text-text-muted'}`}>
      {sectionDisplayName(label)}
    </span>
  )
}

function EnergyDot({ energy }: { energy: number }) {
  const color = energy > 0.6 ? 'bg-chip-red' : energy < 0.3 ? 'bg-chip-blue' : 'bg-chip-yellow'
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} title={directorText('panel.energy', { percent: (energy * 100).toFixed(0) })} />
}

// Chat bubble wrapper
function SystemBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-bg-tertiary/50 rounded-lg p-3 border border-border/50 space-y-2">
      {children}
    </div>
  )
}

function UserBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-accent-blue/10 rounded-lg p-3 ml-8 border border-accent-blue/20">
      {children}
    </div>
  )
}

function LlmThinkingStream({ stage }: { stage: string }) {
  const { t } = useUiTranslation('director')
  const [streamText, setStreamText] = useState('')
  const [streamDone, setStreamDone] = useState(false)
  const [expanded, setExpanded] = useState(true)
  const appendLlmLog = useStore(s => s.directorAppendLlmLog)
  // Latest stream text, readable from inside the poll loop's closure
  // (streamText state would be stale there). Used to persist the finished
  // stream into the chat history on the streaming→done transition.
  const latestTextRef = useRef('')
  // Inner scroll container — kept fixed-height so a long thinking
  // dump doesn't blow up the entire chat panel. Auto-scrolls to the
  // bottom as new tokens arrive so the user always sees the latest
  // generation, just like a terminal tail.
  const streamScrollRef = useRef<HTMLDivElement>(null)

  // Poll the stream-status endpoint continuously for the lifetime of
  // the component. Two failure modes have to be handled:
  //
  //   1. We mount BEFORE the LLM starts streaming (rare but possible
  //      when the user clicks a button that kicks off planning). Need
  //      to wait for `done: false` before treating subsequent
  //      `done: true` as completion — otherwise we'd flash "done"
  //      immediately and never show any text.
  //
  //   2. Multiple LLM calls happen during the same component mount —
  //      e.g. short-film story mode where Pass 1 (screenplay) and
  //      Pass 2 (shot breakdown) both run while the chat sits at
  //      step='plan'. The previous implementation BROKE the polling
  //      loop after the first stream finished, so Pass 2 never showed.
  //      Now we keep polling: when we detect a fresh transition from
  //      done→streaming, we reset streamText and streamDone so the
  //      new stream renders cleanly from the top.
  //
  // The poll interval (400ms) is unchanged — fine for a streaming
  // text-display use case, server endpoint is cheap.
  useEffect(() => {
    let active = true
    const poll = async () => {
      // wasStreaming tracks the last poll's state so we can detect
      // transitions: streaming→done means current run finished;
      // done→streaming means a NEW LLM call has started.
      let wasStreaming = false
      while (active) {
        try {
          const res = await fetch('/api/v1/llm/stream-status')
          if (res.ok) {
            const data = await res.json()
            if (!active) break
            const isStreaming = !data.done
            // Transition: fresh stream started (done→streaming).
            // Mark not-done so the "thinking" indicator returns.
            // We don't wipe streamText here — the streamText update
            // below replaces it with the new stream's first tokens
            // in the same render, avoiding a flash of empty content.
            if (!wasStreaming && isStreaming) {
              setStreamDone(false)
            }
            // Transition: stream just finished (streaming→done).
            // Keep the final text visible, just stop the indicator —
            // and persist the completed stream into the chat history so
            // it survives this component unmounting at the next step.
            if (wasStreaming && !isStreaming) {
              setStreamDone(true)
              appendLlmLog(stage, data.text || latestTextRef.current)
            }
            // While actively streaming, push every chunk into state so
            // the user sees text grow live. Skip when idle so we don't
            // overwrite the previous stream's final text with stale or
            // empty backend buffer between runs.
            if (isStreaming) {
              setStreamText(data.text || '')
              latestTextRef.current = data.text || ''
            }
            wasStreaming = isStreaming
          }
        } catch { /* ignore — endpoint unreachable, retry next tick */ }
        await new Promise(r => setTimeout(r, 400))
      }
    }
    poll()
    return () => { active = false }
  }, [stage, appendLlmLog])

  // Auto-scroll the inner preview box to its bottom whenever new
  // tokens arrive. Uses scrollTop (NOT scrollIntoView) so we don't
  // also drag the outer chat panel — this is a self-contained tail.
  useEffect(() => {
    const el = streamScrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [streamText])

  // Separate thinking from output
  const thinkMatch = streamText.match(/<think>([\s\S]*?)(<\/think>|$)/)
  const thinking = thinkMatch ? thinkMatch[1].trim() : ''
  const isStillThinking = thinkMatch ? !thinkMatch[2].includes('</think>') : false
  const output = streamText.replace(/<think>[\s\S]*?(<\/think>|$)/, '').trim()

  const displayText = thinking || output || ''
  if (!displayText) return null

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-[10px] text-text-muted hover:text-text-secondary transition-colors"
      >
        {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        {isStillThinking ? t('chat.thinking') : thinking && !output ? t('chat.thinkingComplete') : output ? t('chat.writingScenes') : t('chat.llmOutput')}
      </button>
      {expanded && (
        // Fixed-height preview box. It's a "what's happening right now"
        // tail, not a full transcript — capping the height keeps the
        // chat scroll position stable while the LLM streams long
        // thinking dumps. Inner scroll auto-tails to the bottom (see
        // streamScrollRef effect above).
        <div
          ref={streamScrollRef}
          className="mt-1 rounded bg-bg-primary/50 border border-border/30 p-2 max-h-32 overflow-y-auto"
        >
          {thinking && (
            <pre className="text-[10px] text-text-muted whitespace-pre-wrap font-mono leading-relaxed">
              {thinking}
              {isStillThinking && <span className="animate-pulse">|</span>}
            </pre>
          )}
          {output && (
            <pre className="text-[10px] text-accent-blue/70 whitespace-pre-wrap font-mono leading-relaxed mt-1 pt-1 border-t border-border/30">
              {output}
              {!streamDone && !isStillThinking && <span className="animate-pulse">|</span>}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

/** Collapsed, persistent record of completed LLM streams for one stage.
 *  Replaces the old behavior where the thinking/output box vanished the
 *  moment a stage finished. Default-collapsed so history stays compact. */
function LlmLogStage({ stage, label }: { stage: string; label: string }) {
  const { t } = useUiTranslation('director')
  const log = useStore(s => s.directorLlmLog)
  const [openIdx, setOpenIdx] = useState<number | null>(null)
  const entries = log.filter(e => e.stage === stage)
  if (entries.length === 0) return null
  return (
    <div className="space-y-1">
      {entries.map((entry, i) => {
        const open = openIdx === i
        // Same thinking/output split as the live stream box
        const thinkMatch = entry.text.match(/<think>([\s\S]*?)(<\/think>|$)/)
        const thinking = thinkMatch ? thinkMatch[1].trim() : ''
        const output = entry.text.replace(/<think>[\s\S]*?(<\/think>|$)/, '').trim()
        return (
          <div key={i}>
            <button
              onClick={() => setOpenIdx(open ? null : i)}
              className="flex items-center gap-1 text-[10px] text-text-muted hover:text-text-secondary transition-colors"
            >
              {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
              {t(entries.length > 1 ? 'chat.llmPassDone' : 'chat.llmStageDone', { label, n: i + 1 })}
            </button>
            {open && (
              <div className="mt-1 rounded bg-bg-primary/50 border border-border/30 p-2 max-h-48 overflow-y-auto">
                {thinking && (
                  <pre className="text-[10px] text-text-muted whitespace-pre-wrap font-mono leading-relaxed">{thinking}</pre>
                )}
                {output && (
                  <pre className={`text-[10px] text-accent-blue/70 whitespace-pre-wrap font-mono leading-relaxed ${thinking ? 'mt-1 pt-1 border-t border-border/30' : ''}`}>{output}</pre>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function DirectorChat() {
  const { t } = useUiTranslation('director')
  const step = useStore(s => s.directorStep)
  const loading = useStore(s => s.directorLoading)
  // Sub-status text ("Loading transcription model (first use downloads
  // ~300MB)...", "Transcribing audio...", etc.) updated by the polling
  // loop in directorUploadAndAnalyze. Falls back to a static message
  // in the loading spinner when null.
  const loadingMessage = useStore(s => s.directorLoadingMessage)
  // Tracks whether ANY generation job is currently running. Used to
  // gate the "Generate" button in the video-prompts review step so it
  // doesn't look pressable while the system is auto-generating (auto
  // mode) or already generating from a previous click (manual mode).
  const isGenerating = useStore(s => s.isGenerating)
  const error = useStore(s => s.directorError)
  const planRecovery = useStore(s => s.directorPlanRecovery)
  const resumePlan = useStore(s => s.directorResumePlan)
  const analysis = useStore(s => s.directorAnalysis)
  const plannedClips = useStore(s => s.directorPlannedClips)
  const energyBias = useStore(s => s.directorEnergyBias)
  const pacingProfile = useStore(s => s.directorPacingProfile)
  const musicVideoTreatment = useStore(s => s.directorMusicVideoTreatment)
  const setMusicVideoTreatment = useStore(s => s.setDirectorMusicVideoTreatment)
  const clipPlans = useStore(s => s.directorClipPlans)
  const selectedDirectorShotImageSupport = useStore(s => s.models.find(
    model => model.model_type === (s.selectedModelPerMode.video || 'ltx2_22B_distilled_1_1'),
  )?.director?.shot_image_support)
  const directorShotImageGuidance = useStore(s => s.directorShotImageGuidance)
  const directorHasVisualReferences = useStore(s => Boolean(
    s.directorReferenceImage
    || s.directorReferenceImagePath
    || s.directorCharacterRefs.length
    || s.directorCharacterRefPaths.length
    || s.directorLocationRefs.length
    || s.directorLocationRefPaths.length
  ))
  const sceneDescription = useStore(s => s.directorSceneDescription)
  const spokenLanguage = useStore(s => s.directorSpokenLanguage)
  const setSpokenLanguage = useStore(s => s.setDirectorSpokenLanguage)
  const audioName = useStore(s => s.directorAudioName)
  const referenceImage = useStore(s => s.directorReferenceImage)
  const clipImages = useStore(s => s.directorClipImages)
  const imageGenProgress = useStore(s => s.directorImageGenProgress)
  const uploadAndAnalyze = useStore(s => s.directorUploadAndAnalyze)
  const setEnergyBias = useStore(s => s.directorSetEnergyBias)
  const setPacingProfile = useStore(s => s.directorSetPacingProfile)
  const confirmStructure = useStore(s => s.directorConfirmStructure)
  const setSceneDescription = useStore(s => s.directorSetSceneDescription)
  const setReferenceImage = useStore(s => s.directorSetReferenceImage)
  const planPrompts = useStore(s => s.directorPlanPrompts)
  const planVideoPrompts = useStore(s => s.directorPlanVideoPrompts)
  const generateStartImages = useStore(s => s.directorGenerateStartImages)
  const applyToClips = useStore(s => s.directorApplyToClips)
  const directorGenerate = useStore(s => s.directorGenerate)
  const editClipPlan = useStore(s => s.directorEditClipPlan)
  const reset = useStore(s => s.directorReset)
  const speakers = useStore(s => s.directorSpeakers)
  const speakerMappings = useStore(s => s.directorSpeakerMappings)
  const setSpeakerMapping = useStore(s => s.directorSetSpeakerMapping)
  const insertSpeakerMention = useStore(s => s.directorInsertSpeakerMention)
  const autoMode = useStore(s => s.directorAutoMode)
  const setAutoMode = useStore(s => s.setDirectorAutoMode)
  const seamless = useStore(s => s.directorSeamless)
  const setSeamless = useStore(s => s.setDirectorSeamless)
  const selectedVideoSupportsSeamless = useStore(s => {
    const selected = s.selectedModelPerMode.video || 'ltx2_22B_distilled_1_1'
    const model = s.models.find(item => item.model_type === selected)
    return model?.director
      ? model.director.video.seamless.compatible === true
      : true
  })
  const skill = useStore(s => s.directorSkill)
  const setSkill = useStore(s => s.setDirectorSkill)
  const openSkill = (next: DirectorSkill) => setSkill(next)
  const musicSource = useStore(s => s.directorMusicSource)
  const setMusicSource = useStore(s => s.setDirectorMusicSource)
  const songDescription = useStore(s => s.directorSongDescription)
  const setSongDescription = useStore(s => s.setDirectorSongDescription)
  const generateTrack = useStore(s => s.directorGenerateTrack)

  // Short film specific
  const shortFilmCharacters = useStore(s => s.shortFilmCharacters)
  const shortFilmSetCharacters = useStore(s => s.shortFilmSetCharacters)
  const shortFilmUploadAndAnalyze = useStore(s => s.shortFilmUploadAndAnalyze)
  const shortFilmSetPacingBias = useStore(s => s.shortFilmSetPacingBias)
  const shortFilmPlanPrompts = useStore(s => s.shortFilmPlanPrompts)
  const shortFilmPlanVideoPrompts = useStore(s => s.shortFilmPlanVideoPrompts)
  const shortFilmPath = useStore(s => s.shortFilmPath)
  const shortFilmSetPath = useStore(s => s.shortFilmSetPath)
  const shortFilmPlanFromStory = useStore(s => s.shortFilmPlanFromStory)
  const shortFilmTargetDuration = useStore(s => s.shortFilmTargetDuration)
  const shortFilmSetTargetDuration = useStore(s => s.shortFilmSetTargetDuration)
  const shortFilmNarrative = useStore(s => s.shortFilmNarrative)
  const shortFilmSetNarrative = useStore(s => s.shortFilmSetNarrative)
  const shortFilmVisualStyle = useStore(s => s.shortFilmVisualStyle)
  const shortFilmSetVisualStyle = useStore(s => s.shortFilmSetVisualStyle)
  const shortFilmPreserveVisualStyle = useStore(s => s.shortFilmPreserveVisualStyle)
  const shortFilmSetPreserveVisualStyle = useStore(s => s.shortFilmSetPreserveVisualStyle)
  const directorCharacterVisualStyle = useStore(s => s.directorCharacterVisualStyle)
  const setDirectorCharacterVisualStyle = useStore(s => s.setDirectorCharacterVisualStyle)
  const directorAllowClipText = useStore(s => s.directorAllowClipText)
  const setDirectorAllowClipText = useStore(s => s.setDirectorAllowClipText)
  const startDirectorPipeline = useStore(s => s.startDirectorPipeline)
  const pipelineStatus = useStore(s => s.pipelineStatus)
  const pipelinePhase = pipelineStatus?.phase
  const pipelineIsActive = pipelineStatus?.status === 'running'
  const usesShotImages = directorWillGenerateShotImages(
    selectedDirectorShotImageSupport,
    directorShotImageGuidance,
    directorHasVisualReferences,
  )

  const isShortFilm = skill === 'short_film'
  const isStoryPath = isShortFilm && shortFilmPath === 'story'
  const isMusicVideo = !!skill && !isShortFilm
  const isDirectVideo = musicVideoTreatment.generation_mode === 'direct_video'
  // Music Video "Generate a track" setup: the bottom chat IS the song
  // description, and Send kicks off the whole write-song → render → video chain.
  const isMvGenerate = isMusicVideo && musicSource === 'generate'
  const mvGenerateSetup = isMvGenerate && step === 'upload'

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [localBias, setLocalBias] = useState<number | null>(null)
  const [showAnalysisDetails, setShowAnalysisDetails] = useState(false)
  const sliderRef = useRef<number | null>(null)
  // null means "use the current story description as the untouched draft".
  // Once the user types (including clearing the field), their explicit draft
  // wins without needing an effect that synchronously mirrors store state.
  const [chatInput, setChatInput] = useState<string | null>(null)
  const resolvedChatInput = chatInput ?? (step === 'style' ? sceneDescription : '')

  const refImagePreview = useObjectUrl(referenceImage)

  const speakerSamples = useMemo(() => {
    const samples: Record<string, string[]> = {}
    if (analysis?.lyrics) {
      for (const seg of analysis.lyrics) {
        if (seg.speaker && !samples[seg.speaker]) {
          samples[seg.speaker] = []
        }
        if (seg.speaker && samples[seg.speaker].length < 2) {
          samples[seg.speaker].push(seg.text)
        }
      }
    }
    return samples
  }, [analysis])

  const currentIndex = STEP_ORDER.indexOf(step)
  const pastStep = (s: DirectorStep) => currentIndex > STEP_ORDER.indexOf(s)
  const atStep = (s: DirectorStep) => step === s

  const handleFile = useCallback((file: File) => {
    // Accept audio/* MIME OR video/* MIME (backend extracts the audio
    // track from video) OR a matching file extension. Some browsers /
    // OSes don't set MIME on drag-drop, so the extension fallback is
    // load-bearing.
    const mimeOk = file.type.startsWith('audio/') || file.type.startsWith('video/')
    const extOk = AUDIO_ACCEPT.split(',').some(ext => file.name.toLowerCase().endsWith(ext))
    if (!mimeOk && !extOk) {
      return
    }
    if (isShortFilm) {
      shortFilmUploadAndAnalyze(file)
    } else {
      uploadAndAnalyze(file)
    }
  }, [uploadAndAnalyze, shortFilmUploadAndAnalyze, isShortFilm])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [handleFile])

  const totalClipDuration = useMemo(
    () => plannedClips.length > 0 ? plannedClips[plannedClips.length - 1].end : 0,
    [plannedClips]
  )

  const beatDistribution = useMemo(() => {
    const counts: Record<number, number> = {}
    for (const c of plannedClips) {
      counts[c.beat_count] = (counts[c.beat_count] || 0) + 1
    }
    return Object.entries(counts)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([beats, count]) => t('panel.beatDistribution', { count: Number(count), beats }))
      .join(', ')
  }, [plannedClips, t])

  // Auto-scroll to bottom on step/loading changes. loadingMessage and error
  // are included so progress-text updates (e.g. "Generating music track…",
  // analyze phases) and new errors pull the view down to the newest content.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [step, loading, loadingMessage, error, planRecovery, clipPlans.length, clipImages.length, skill])

  const handleChatSubmit = () => {
    // Music Video "Generate a track": the chat is the song description, and
    // Send runs write-song → render track → analyze → plan → images → video.
    if (mvGenerateSetup) {
      if (songDescription.trim() && !loading) generateTrack()
      return
    }
    if (step === 'style' && resolvedChatInput.trim()) {
      setSceneDescription(resolvedChatInput.trim())
      if (autoMode) {
        // Auto mode: run entire flow server-side via pipeline
        startDirectorPipeline()
      } else if (isStoryPath) {
        shortFilmPlanFromStory()
      } else if (isShortFilm) {
        shortFilmPlanPrompts()
      } else {
        planPrompts()
      }
    }
  }

  // Determine chat input state
  const chatInputEnabled = (step === 'style' || mvGenerateSetup) && !loading
  const chatInputPlaceholder = directorChatPlaceholder({
    skill,
    mvGenerateSetup,
    isShortFilm,
    shortFilmPath,
    step,
    isMvGenerate,
    isStoryPath,
    speakerCount: speakers.length,
  })

  if (skill === 'comic') {
    return (
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <BookOpen size={14} className="text-accent-blue" />
            <span className="text-xs font-medium text-text-primary">{t('chat.comicDirector')}</span>
          </div>
          <button
            onClick={reset}
            className="flex items-center gap-0.5 text-[10px] text-text-muted transition-colors hover:text-text-primary"
            title={t('panel.startOverTitle')}
          >
            <RotateCcw size={10} /> {t('panel.startOver')}
          </button>
        </div>
        <Suspense fallback={<div className="flex items-center justify-center gap-2 py-8 text-xs text-text-muted"><Loader2 size={14} className="animate-spin text-accent-blue" /> {t('chat.openingComic')}</div>}>
          <ComicDirectorPanel createCompleteComic />
        </Suspense>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {/* Header with Start Over */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {isShortFilm ? <Film size={14} className="text-accent-blue" /> : <Music size={14} className="text-accent-blue" />}
            <span className="text-xs font-medium text-text-primary">{t('panel.title')}</span>
            {analysis && !isShortFilm && (
              <span className="text-[10px] text-text-muted">
                {t('panel.bpm', { bpm: analysis.bpm.toFixed(0) })}
              </span>
            )}
            {analysis && isShortFilm && (
              <span className="text-[10px] text-text-muted">
                {formatTime(analysis.duration)}
              </span>
            )}
            {!analysis && isStoryPath && (
              <span className="text-[10px] text-text-muted">
                {t('song.duration', { count: shortFilmTargetDuration })}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => useStore.getState().setMediaFilter('runs')}
              className="text-[10px] text-accent-blue hover:text-accent-blue/80 flex items-center gap-0.5 transition-colors"
              title={t('chat.openWorkspaces')}
            >
              {t('chat.workspaces')}
            </button>
            {(skill || step !== 'upload') && (
              <button
                onClick={reset}
                className="text-[10px] text-text-muted hover:text-text-primary flex items-center gap-0.5 transition-colors"
                title={t('panel.startOverTitle')}
              >
                <RotateCcw size={10} /> {t('panel.startOver')}
              </button>
            )}
          </div>
        </div>

        {/* Welcome message */}
        <SystemBubble>
          <p className="text-xs text-text-secondary">
            {t('chat.welcome')}
          </p>
        </SystemBubble>

        {/* Aspect ratio + resolution selectors (always visible before skill selection) */}
        {!skill && (
          <div className="space-y-2">
            <DirectorAspectRatioSelector />
            <DirectorResolutionSelector />
          </div>
        )}

        {/* Skill selector */}
        {!skill ? (
          <SkillSelector onSelect={openSkill} />
        ) : (
          <UserBubble>
            <div className="flex items-center gap-1.5 text-xs text-text-primary">
              {isShortFilm ? <Film size={12} className="text-accent-blue" /> : <Music size={12} className="text-accent-blue" />}
              <span>{isShortFilm ? t('chat.shortFilm') : t('chat.musicVideo')}</span>
            </div>
          </UserBubble>
        )}

        {/* Short Film path chooser */}
        {isShortFilm && skill && !shortFilmPath && (
          <SystemBubble>
            <p className="text-xs text-text-secondary mb-2">{t('chat.shortFilmHow')}</p>
            <PathChooser onSelect={(path: ShortFilmPath) => {
              shortFilmSetPath(path)
              if (path === 'story') {
                useStore.setState({ directorStep: 'style' })
              }
            }} />
          </SystemBubble>
        )}
        {isShortFilm && shortFilmPath && (
          <UserBubble>
            <div className="flex items-center gap-1.5 text-xs text-text-primary">
              {shortFilmPath === 'story' ? <FileText size={12} className="text-accent-blue" /> : <Upload size={12} className="text-accent-blue" />}
              <span>{shortFilmPath === 'story' ? t('chat.describeStory') : t('chat.uploadAudio')}</span>
            </div>
          </UserBubble>
        )}

        {/* Upload step — hidden for story path and before short film path is chosen */}
        {skill && (!isShortFilm || shortFilmPath === 'audio') && (atStep('upload') || atStep('analyze') || pastStep('analyze')) && (
          <>
            {!audioName && !pastStep('analyze') ? (
              <SystemBubble>
                <p className="text-xs text-text-secondary mb-2">
                  {isShortFilm
                    ? t('chat.uploadRefsIntro')
                    : t('chat.uploadTrackIntro')}
                </p>
                <div className="space-y-3">
                  <ReferenceImageUpload
                    referenceImage={referenceImage}
                    refImagePreview={refImagePreview}
                    setReferenceImage={setReferenceImage}
                  />
                  {<AdditionalRefsSection />}
                  {isShortFilm && (
                    <CharacterNaming
                      characters={shortFilmCharacters}
                      setCharacters={shortFilmSetCharacters}
                    />
                  )}
                  {/* Music Video: upload a track OR generate one with ACE-Step */}
                  {!isShortFilm && (
                    <div className="flex gap-1.5 p-1 bg-bg-tertiary rounded-lg border border-border">
                      {(['upload', 'generate'] as const).map(opt => {
                        const active = (musicSource || 'upload') === opt
                        return (
                          <button
                            key={opt}
                            onClick={() => setMusicSource(opt)}
                            className={`flex-1 px-2 py-1.5 rounded-md text-[11px] font-medium transition-all ${
                              active ? 'bg-accent-blue text-white' : 'text-text-secondary hover:text-text-primary'
                            }`}
                          >
                            {opt === 'upload' ? t('chat.uploadTrack') : t('chat.generateTrack')}
                          </button>
                        )
                      })}
                    </div>
                  )}
                  {!isShortFilm && musicSource === 'generate' ? (
                    !loading && <DirectorSongSetup />
                  ) : (
                    <UploadZone
                      dragOver={dragOver}
                      setDragOver={setDragOver}
                      handleDrop={handleDrop}
                      handleFile={handleFile}
                      loading={loading && atStep('analyze')}
                      loadingMessage={loadingMessage}
                      audioName={audioName}
                      isShortFilm={isShortFilm}
                    />
                  )}
                  {/* Music Video: up-front options (LoRA + post-processing) live
                      here at the first step instead of buried mid-flow. */}
                  {!isShortFilm && (
                    <div className="pt-1 border-t border-border/50 space-y-1">
                      <DirectorLoraAccordion />
                      <DirectorAdvancedAccordion />
                    </div>
                  )}
                  {/* Track-generation progress renders LAST in the bubble so
                      the newest activity is the bottom-most chat content (the
                      scroll anchor brings it into view) — previously it sat
                      above the LoRA/Advanced accordions. */}
                  {!isShortFilm && musicSource === 'generate' && loading && (
                    <div className="flex items-center gap-2 py-2">
                      <Loader2 size={14} className="animate-spin text-accent-blue" />
                      <span className="text-xs text-text-muted">{loadingMessage || t('chat.generating')}</span>
                    </div>
                  )}
                </div>
              </SystemBubble>
            ) : audioName && (atStep('analyze') || atStep('upload')) ? (
              <SystemBubble>
                <div className="space-y-3">
                  {/* Keep the reference selections VISIBLE during analysis —
                      they used to unmount behind a `!loading` gate, which read
                      as "my selections disappeared". Interaction is disabled
                      while loading; the state is untouched. */}
                  <div className={loading ? 'opacity-60 pointer-events-none' : ''}>
                    <ReferenceImageUpload
                      referenceImage={referenceImage}
                      refImagePreview={refImagePreview}
                      setReferenceImage={setReferenceImage}
                    />
                    {<AdditionalRefsSection />}
                  </div>
                  <UploadZone
                    dragOver={dragOver}
                    setDragOver={setDragOver}
                    handleDrop={handleDrop}
                    handleFile={handleFile}
                    loading={loading}
                    loadingMessage={loadingMessage}
                    audioName={audioName}
                    isShortFilm={isShortFilm}
                  />
                </div>
              </SystemBubble>
            ) : audioName && pastStep('analyze') ? (
              <UserBubble>
                <div className="flex items-center gap-2 text-xs text-text-primary">
                  {isShortFilm ? <Film size={12} className="text-text-muted" /> : <Music size={12} className="text-text-muted" />}
                  <span className="truncate">{audioName}</span>
                  {referenceImage && refImagePreview && (
                    <img src={refImagePreview} alt={t('chat.refAlt')} className="w-8 h-8 object-cover rounded border border-border ml-auto" />
                  )}
                </div>
              </UserBubble>
            ) : null}
          </>
        )}

        {/* Analysis result — hidden for story path */}
        {!isStoryPath && analysis && pastStep('analyze') && (
          <SystemBubble>
            <AnalysisSummary
              analysis={analysis}
              showDetails={showAnalysisDetails}
              setShowDetails={setShowAnalysisDetails}
              isShortFilm={isShortFilm}
            />
            {/* Allow adding/changing reference photo after analysis */}
            {!pastStep('style') && (
              <div className="mt-2 pt-2 border-t border-border/50">
                <ReferenceImageUpload
                  referenceImage={referenceImage}
                  refImagePreview={refImagePreview}
                  setReferenceImage={setReferenceImage}
                  compact
                />
                {<AdditionalRefsSection />}
              </div>
            )}
          </SystemBubble>
        )}

        {/* Structure step — hidden for story path */}
        {!isStoryPath && (atStep('structure') || pastStep('structure')) && (
          <>
            <SystemBubble>
              <StructureView
                plannedClips={plannedClips}
                energyBias={energyBias}
                localBias={localBias}
                setLocalBias={setLocalBias}
                sliderRef={sliderRef}
                setEnergyBias={isShortFilm ? shortFilmSetPacingBias : setEnergyBias}
                loading={loading}
                totalClipDuration={totalClipDuration}
                beatDistribution={beatDistribution}
                confirmStructure={confirmStructure}
                isActive={atStep('structure')}
                isShortFilm={isShortFilm}
                isMusicVideo={isMusicVideo}
                pacingProfile={pacingProfile}
                setPacingProfile={setPacingProfile}
              />
            </SystemBubble>
            {pastStep('structure') && (
              <UserBubble>
                <div className="flex items-center gap-1.5 text-xs text-text-primary">
                  <Check size={12} className="text-indicator-success" />
                  <span>{t(isShortFilm ? 'chat.scenesConfirmed' : 'chat.clipsConfirmed', { count: plannedClips.length })}</span>
                  <span className="text-text-muted">({formatTime(totalClipDuration)})</span>
                </div>
              </UserBubble>
            )}
          </>
        )}

        {/* Style step */}
        {(atStep('style') || pastStep('style')) && (
          <>
            {atStep('style') && <SystemBubble>
              <label className="block">
                <span className="text-[10px] text-text-muted">{t('spoken.label')}</span>
                <select aria-label={t('spoken.label')} className="mt-1 w-full rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-[10px] text-text-primary" value={spokenLanguage} onChange={event => setSpokenLanguage(event.target.value)}>
                  <SpokenLanguageOptions />
                </select>
                <span className="mt-1 block text-[9px] leading-relaxed text-text-muted">{t('spoken.hint')}</span>
              </label>
            </SystemBubble>}
            {/* Story path: show reference image + characters + duration here (since no upload step) */}
            {isStoryPath && atStep('style') && (
              <SystemBubble>
                <p className="text-xs text-text-secondary mb-2">
                  {t('chat.storySetup')}
                </p>
                <div className="space-y-3">
                  <ReferenceImageUpload
                    referenceImage={referenceImage}
                    refImagePreview={refImagePreview}
                    setReferenceImage={setReferenceImage}
                  />
                  {<AdditionalRefsSection />}
                  <CharacterNaming
                    characters={shortFilmCharacters}
                    setCharacters={shortFilmSetCharacters}
                  />
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-text-muted flex items-center gap-1">
                        <Clock size={10} /> {t('chat.targetDuration')}
                      </span>
                      <span className="text-[10px] text-text-primary font-medium">{t('song.duration', { count: shortFilmTargetDuration })}</span>
                    </div>
                    <input
                      aria-label={t('song.duration', { count: shortFilmTargetDuration })}
                      type="range"
                      min={10}
                      max={300}
                      step={5}
                      value={shortFilmTargetDuration}
                      onChange={e => shortFilmSetTargetDuration(Number(e.target.value))}
                      className="w-full h-1 bg-bg-hover rounded-lg appearance-none cursor-pointer accent-accent-blue"
                    />
                    <div className="flex justify-between text-[9px] text-text-muted mt-0.5">
                      <span>{'10s' // i18n-ok: 10s
                      }</span>
                      <span>{'5m' // i18n-ok: 5m
                      }</span>
                    </div>
                  </div>
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input aria-label={t('chat.narrative')}
                      type="checkbox"
                      checked={shortFilmNarrative}
                      onChange={e => shortFilmSetNarrative(e.target.checked)}
                      className="accent-accent-blue"
                    />
                    <div>
                      <span className="text-[10px] text-text-primary">{t('chat.narrative')}</span>
                      <p className="text-[9px] text-text-muted leading-tight">
                        {t('chat.narrativeHint')}
                      </p>
                    </div>
                  </label>
                  <label className="flex items-start gap-2 rounded-md border border-purple-500/30 bg-purple-500/10 p-2 cursor-pointer">
                    <input aria-label={t('chat.preserveStyle')}
                      type="checkbox"
                      checked={shortFilmPreserveVisualStyle}
                      onChange={e => shortFilmSetPreserveVisualStyle(e.target.checked)}
                      className="mt-0.5 accent-purple-400"
                    />
                    <div>
                      <span className="text-[10px] text-purple-200">{t('chat.preserveStyle')}</span>
                      <p className="text-[9px] text-text-muted leading-tight">
                        {t('chat.preserveStyleHint')}
                      </p>
                    </div>
                  </label>
                  <label className="block">
                    <span className="text-[10px] text-text-muted">{t('chat.canonicalStyle')}</span>
                    <AutoResizeTextarea
                      aria-label={t('chat.canonicalStyle')}
                      value={shortFilmVisualStyle}
                      onChange={e => shortFilmSetVisualStyle(e.target.value)}
                      disabled={!shortFilmPreserveVisualStyle}
                      title={controlReason(!shortFilmPreserveVisualStyle, 'disabled.unlockLayer')}
                      rows={3}
                      className="mt-1 w-full resize-none rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-[10px] leading-relaxed text-text-primary focus:outline-none focus:border-accent-blue disabled:opacity-50"
                      placeholder={t('chat.canonicalStylePlaceholder')}
                    />
                    <p className="mt-1 text-[9px] text-text-muted">
                      {t('chat.canonicalStyleHint')}
                    </p>
                  </label>
                  <label className="block">
                    <span className="text-[10px] text-text-muted">{t('chat.characterStyle')}</span>
                    <AutoResizeTextarea
                      aria-label={t('chat.characterStyle')}
                      value={directorCharacterVisualStyle}
                      onChange={e => setDirectorCharacterVisualStyle(e.target.value)}
                      disabled={!shortFilmPreserveVisualStyle}
                      title={controlReason(!shortFilmPreserveVisualStyle, 'disabled.unlockLayer')}
                      rows={3}
                      className="mt-1 w-full resize-none rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-[10px] leading-relaxed text-text-primary focus:outline-none focus:border-accent-blue disabled:opacity-50"
                      placeholder={t('chat.characterStylePlaceholder')}
                    />
                    <p className="mt-1 text-[9px] text-text-muted">
                      {t('chat.characterStyleHint')}
                    </p>
                  </label>
                  <label className="flex items-start gap-2 cursor-pointer group">
                    <input aria-label={t('clipText.label')}
                      type="checkbox"
                      checked={directorAllowClipText}
                      onChange={e => setDirectorAllowClipText(e.target.checked)}
                      className="mt-0.5 accent-accent-blue"
                    />
                    <div>
                      <span className="text-[10px] text-text-primary">{t('clipText.label')}</span>
                      <p className="text-[9px] text-text-muted leading-tight">
                        {t('clipText.hint')}
                      </p>
                    </div>
                  </label>
                </div>
              </SystemBubble>
            )}
            {isStoryPath && pastStep('style') && referenceImage && refImagePreview && (
              <UserBubble>
                <div className="flex items-center gap-2 text-xs text-text-primary">
                  <img src={refImagePreview} alt={t('chat.refAlt')} className="w-8 h-8 object-cover rounded border border-border" />
                  <span>{t('chat.durationFilm', { count: shortFilmTargetDuration })}</span>
                </div>
              </UserBubble>
            )}
            {isMusicVideo && atStep('style') && (
              <SystemBubble>
                <MusicVideoTreatmentEditor
                  treatment={musicVideoTreatment}
                  onChange={setMusicVideoTreatment}
                />
              </SystemBubble>
            )}
            {isMusicVideo && pastStep('style') && (
              <UserBubble>
                <p className="text-[10px] text-text-secondary">
                  {isDirectVideo ? t('directVideo.mode') : <TreatmentSummary treatment={musicVideoTreatment} />}
                </p>
              </UserBubble>
            )}
            <SystemBubble>
              <StyleForm
                speakers={speakers}
                speakerMappings={speakerMappings}
                speakerSamples={speakerSamples}
                setSpeakerMapping={setSpeakerMapping}
                insertSpeakerMention={insertSpeakerMention}
                isActive={atStep('style')}
                isShortFilm={isShortFilm}
                isStoryPath={isStoryPath}
              />
            </SystemBubble>
            {pastStep('style') && sceneDescription && (
              <UserBubble>
                <p className="text-xs text-text-primary">{sceneDescription}</p>
              </UserBubble>
            )}
          </>
        )}

        {/* Plan loading with LLM thinking stream */}
        {atStep('plan') && loading && (
          <SystemBubble>
            <div className="flex items-center gap-2 py-1">
              <Loader2 size={14} className="animate-spin text-accent-blue" />
              <span className="text-xs text-text-muted">
                {planPhaseLabel(pipelinePhase, isStoryPath, isShortFilm, usesShotImages)}
              </span>
            </div>
            {pipelinePhase !== 'polishing_prompts' && <LlmThinkingStream stage="plan" />}
          </SystemBubble>
        )}

        {/* Completed planning streams stay in the chat history */}
        {(pastStep('plan') || (atStep('plan') && !loading)) && (
          <LlmLogStage stage="plan" label={isShortFilm ? t('chat.planStage') : usesShotImages ? t('chat.imageVideoStage') : t('chat.videoPlanningStage')} />
        )}

        {/* Review step (image prompts) */}
        {usesShotImages && (atStep('review') || pastStep('review')) && (
          <SystemBubble>
            <ImagePromptsReview
              clipPlans={clipPlans}
              plannedClips={plannedClips}
              speakerMappings={speakerMappings}
              editClipPlan={editClipPlan}
              planPrompts={isStoryPath ? shortFilmPlanFromStory : isShortFilm ? shortFilmPlanPrompts : planPrompts}
              generateStartImages={generateStartImages}
              loading={loading}
              isActive={atStep('review')}
              isShortFilm={isShortFilm}
            />
          </SystemBubble>
        )}

        {/* Image generation step */}
        {usesShotImages && (atStep('generate_images') || pastStep('generate_images')) && (
          <SystemBubble>
            <ImageGenView
              loading={loading}
              imageGenProgress={imageGenProgress}
              clipImages={clipImages}
            />
          </SystemBubble>
        )}

        {/* Plan video loading */}
        {atStep('plan_video') && loading && (
          <SystemBubble>
            <div className="flex items-center gap-2 py-1">
              <Loader2 size={14} className="animate-spin text-accent-blue" />
              <span className="text-xs text-text-muted">{t('panel.writingVideoPrompts')}</span>
            </div>
            <LlmThinkingStream stage="plan_video" />
          </SystemBubble>
        )}

        {/* Completed video-prompt streams stay in the chat history */}
        {(pastStep('plan_video') || (atStep('plan_video') && !loading) || atStep('review_video')) && (
          <LlmLogStage stage="plan_video" label={t('panel.videoPrompts')} />
        )}

        {/* Video review step */}
        {atStep('review_video') && (
          <SystemBubble>
            <VideoPromptsReview
              clipPlans={clipPlans}
              plannedClips={plannedClips}
              clipImages={clipImages}
              speakerMappings={speakerMappings}
              editClipPlan={editClipPlan}
              planVideoPrompts={isShortFilm ? shortFilmPlanVideoPrompts : planVideoPrompts}
              directorGenerate={directorGenerate}
              applyToClips={applyToClips}
              loading={loading}
              isShortFilm={isShortFilm}
              // "Generating" is true if EITHER a manual job is running
              // (isGenerating) OR an auto-mode pipeline is actively
              // running. Auto mode doesn't push jobs into the same job
              // queue — it has its own pipelineStatus state machine —
              // so without the OR the button looks pressable during
              // auto generation. The label flips to "Auto Generating…"
              // when the pipeline is what's running, so it's clear
              // *why* the button is disabled.
              isGenerating={isGenerating || pipelineIsActive}
              isAutoGenerating={autoMode && pipelineIsActive}
              generationError={error}
            />
          </SystemBubble>
        )}

        {/* Keep failures adjacent to the activity that produced them. Video
            generation renders its error directly below the Generate status
            control; earlier-stage failures land here, after the current step,
            instead of appearing near the first line of the conversation. */}
        {planRecovery && !atStep('review_video') && (
          <DirectorPlanRecoveryCard
            job={planRecovery}
            loading={loading}
            onResume={resumePlan}
          />
        )}
        {error && !planRecovery && !atStep('review_video') && (
          <div role="alert" className="text-[11px] text-red-300 bg-red-500/10 rounded px-2 py-2 border border-red-500/30 flex items-start gap-1.5">
            <X size={12} className="mt-0.5 shrink-0" />
            <span><strong className="font-semibold">{t('chat.errorPrefix')}</strong> {error}</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Persistent toggles + Chat input bar */}
      <div className="px-4 py-3 border-t border-border space-y-2">
        {skill && (
          <div className="space-y-2">
            <div className="flex items-center gap-4">
              <label
                className={`flex items-center gap-1.5 select-none ${selectedVideoSupportsSeamless ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}`}
                title={selectedVideoSupportsSeamless
                  ? t('chat.seamlessTitle')
                  : t('chat.seamlessUnsupported')}
              >
                <input aria-label={t('chat.seamless')}
                  type="checkbox"
                  checked={seamless}
                  disabled={!selectedVideoSupportsSeamless || isDirectVideo}
                  title={firstControlReason([
                    [!selectedVideoSupportsSeamless, 'disabled.chooseModel'],
                    [isDirectVideo, 'disabled.sendNeedsStep'],
                  ])}
                  onChange={e => setSeamless(e.target.checked)}
                  className="accent-accent-blue w-3 h-3"
                />
                <span className={`text-[10px] ${isDirectVideo ? 'text-text-muted/50' : 'text-text-secondary'}`}>{t('chat.seamless')}</span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer select-none" title={t('chat.autoTitle')}>
                <input aria-label={t('chat.auto')}
                  type="checkbox"
                  checked={autoMode}
                  onChange={e => setAutoMode(e.target.checked)}
                  className="accent-red-500 w-3 h-3"
                />
                <span className={`text-[10px] ${autoMode ? 'text-red-400' : 'text-text-secondary'}`}>{t('chat.auto')}</span>
              </label>
            </div>
            {audioName && (
              <div className="flex items-center gap-2">
                <AudioScaleSlider />
                <div className="flex gap-2 text-[8px] text-text-muted">
                  <span>{'1x' // i18n-ok: 1x
                  }</span>
                  <span>{t('chat.audioScaleTts')}</span>
                  <span>{'5x' // i18n-ok: 5x
                  }</span>
                </div>
              </div>
            )}
          </div>
        )}
        <div className="flex items-end gap-2">
          {/* Auto-grows with content (issue #11). The composer bar is the
              last child of the panel's flex column, so extra height is
              taken from the messages area above — the box visually
              expands UPWARD from its bottom-anchored position. Rests at
              2 rows (min 56px), caps at 240px (~11 lines), scrolls with
              a visible thumb past that. */}
          <AutoResizeTextarea
            aria-label={chatInputPlaceholder}
            value={mvGenerateSetup ? songDescription : resolvedChatInput}
            onChange={e => {
              const v = e.target.value
              if (mvGenerateSetup) { setSongDescription(v); return }
              setChatInput(v)
              if (step === 'style') setSceneDescription(v)
            }}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey && chatInputEnabled) {
                e.preventDefault()
                handleChatSubmit()
              }
            }}
            placeholder={chatInputPlaceholder}
            disabled={!chatInputEnabled}
            title={firstControlReason([
              [loading, 'disabled.sendWhileBusy'],
              [!chatInputEnabled, 'disabled.sendNeedsStep'],
            ])}
            rows={2}
            minHeight={56}
            maxHeight={240}
            className="flex-1 bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted resize-none focus:outline-none focus:border-accent-blue transition-colors disabled:opacity-50 disabled:cursor-not-allowed scrollbar-visible"
          />
          <button
            onClick={handleChatSubmit}
            disabled={!chatInputEnabled || !(mvGenerateSetup ? songDescription : resolvedChatInput).trim()}
            className="p-2 rounded-lg bg-accent-blue text-white hover:bg-accent-blue-hover transition-colors disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
           title={directorSendLabel(chatInputEnabled, loading, mvGenerateSetup, songDescription, resolvedChatInput)} aria-label={directorSendLabel(chatInputEnabled, loading, mvGenerateSetup, songDescription, resolvedChatInput)}>
            {loading && (step === 'style' || isMusicVideo) ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Send size={16} />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// --- Sub-components ---

function CharacterNaming({
  characters, setCharacters,
}: {
  characters: ShortFilmCharacter[]
  setCharacters: (characters: ShortFilmCharacter[]) => void
}) {
  const { t } = useUiTranslation('director')
  const addCharacter = () => {
    setCharacters([...characters, { name: '', description: '' }])
  }

  const updateCharacter = (index: number, field: 'name' | 'description', value: string) => {
    const updated = characters.map((c, i) =>
      i === index ? { ...c, [field]: value } : c
    )
    setCharacters(updated)
  }

  const removeCharacter = (index: number) => {
    setCharacters(characters.filter((_, i) => i !== index))
  }

  return (
    <div>
      <label className="text-[11px] text-text-muted uppercase tracking-wider block mb-1.5">
        <Users size={10} className="inline mr-1" />
        {t('chat.nameCharacters')}
      </label>
      <div className="space-y-1.5">
        {characters.map((char, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <input aria-label={t('chat.characterName', { n: i + 1 })}
              type="text"
              value={char.name}
              onChange={e => updateCharacter(i, 'name', e.target.value)}
              placeholder={t('chat.characterName', { n: i + 1 })}
              className="flex-1 bg-bg-secondary border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue transition-colors"
            />
            <input aria-label={t('chat.briefDescription')}
              type="text"
              value={char.description}
              onChange={e => updateCharacter(i, 'description', e.target.value)}
              placeholder={t('chat.briefDescription')}
              className="flex-1 bg-bg-secondary border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue transition-colors"
            />
            <button
              onClick={() => removeCharacter(i)}
              className="p-1 rounded hover:bg-bg-hover transition-colors shrink-0"
             title={controlLabel('a11y.removeCharacter')} aria-label={controlLabel('a11y.removeCharacter')}>
              <X size={10} className="text-text-muted" />
            </button>
          </div>
        ))}
      </div>
      <button
        onClick={addCharacter}
        className="mt-1.5 text-[10px] text-accent-blue hover:text-accent-blue-hover transition-colors"
      >
        {t('chat.addCharacter')}
      </button>
      <span className="text-[10px] text-text-muted block mt-1">
        {t('chat.nameCharactersHint')}
      </span>
    </div>
  )
}

function DirectorAspectRatioSelector() {
  const { t } = useUiTranslation('director')
  const ratio = useStore(s => s.directorAspectRatio)
  const setRatio = useStore(s => s.setDirectorAspectRatio)
  const presets = [
    { value: '16:9' as const, label: '16:9', desc: t('chat.wide') },
    { value: '9:16' as const, label: '9:16', desc: t('chat.portrait') },
    { value: '1:1' as const, label: '1:1', desc: t('chat.square') },
    { value: '4:3' as const, label: '4:3', desc: t('chat.classic') },
    { value: '3:4' as const, label: '3:4', desc: t('chat.tall') },
  ]
  return (
    <div>
      <label className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('chat.aspectRatio')}</label>
      <div className="flex gap-1.5">
        {presets.map(p => (
          <button
            key={p.value}
            onClick={() => setRatio(p.value)}
            className={`flex-1 py-1.5 rounded-lg border text-xs transition-all ${
              ratio === p.value
                ? 'border-accent-blue bg-accent-blue/10 text-text-primary'
                : 'border-border text-text-muted hover:border-border-light hover:text-text-secondary'
            }`}
          >
            <div className="font-medium">{p.label}</div>
            <div className="text-[9px] mt-0.5 opacity-60">{p.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

function DirectorResolutionSelector() {
  const { t } = useUiTranslation('director')
  const resolution = useStore(s => s.directorResolution)
  const aspectRatio = useStore(s => s.directorAspectRatio)
  const setResolution = useStore(s => s.setDirectorResolution)
  const videoModel = useStore(s => s.selectedModelPerMode.video || 'ltx2_22B_distilled_1_1')
  const totalVramGb = useStore(s => s.systemStats?.gpu.vram_total_gb ?? 0)
  const [options, setOptions] = useState<ModelOptions | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchModelOptions(videoModel)
      .then(value => { if (!cancelled) setOptions(value) })
      .catch(() => { if (!cancelled) setOptions(null) })
    return () => { cancelled = true }
  }, [videoModel])

  const fallbackOrder = ['480p', '540p', '720p', '1080p'] as const
  const modelPresetOrder = (options?.resolution_preset_order || []).filter(
    value => value !== 'auto' && value !== '768p',
  )
  const presetOrder = modelPresetOrder.length > 0
    ? modelPresetOrder
    : [...fallbackOrder]
  const presets = presetOrder.map(value => ({
    value,
    label: resolutionPresetLabel(value, options?.resolution_presets?.[value]?.label),
  }))
  const resolvedResolution = resolveResolution(options, resolution, aspectRatio)
  const recommendation = recommendedWindowProfile(
    options?.director_memory_policy || options?.sliding_window_memory_policy,
    resolvedResolution,
    totalVramGb,
  )
  const fps = options?.fps || 24
  const selectedConfig = options?.resolution_presets?.[resolution]
  return (
    <div>
      <label className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('chat.resolution')}</label>
      <div className="flex gap-1.5">
        {presets.map(p => (
          <button
            key={p.value}
            onClick={() => setResolution(p.value)}
            className={`flex-1 py-2 rounded-lg border text-xs font-medium transition-all ${
              resolution === p.value
                ? 'border-accent-blue bg-accent-blue/10 text-text-primary'
                : 'border-border text-text-muted hover:border-border-light hover:text-text-secondary'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="mt-1 text-[10px] text-text-muted">
        {resolvedResolution}
        {recommendation?.frames != null && totalVramGb > 0 && (
          <> &middot; {t('chat.autoMaxShot', { time: formatSeconds(recommendation.frames / fps), gb: totalVramGb.toFixed(0) })}</>
        )}
      </div>
      {recommendation?.supported === false && (
        <div className="mt-1 text-[10px] text-amber-400">
          {t('chat.autoRecommends', { resolution: recommendation.fallbackResolution || t('chat.lowerResolution') })}
        </div>
      )}
      {selectedConfig?.hint && (
        <div className={`mt-1 text-[10px] ${selectedConfig.experimental ? 'text-amber-400' : 'text-text-muted'}`}>
          {selectedConfig.hint}
        </div>
      )}
    </div>
  )
}

export function SkillSelector({ onSelect }: { onSelect: (skill: DirectorSkill) => void }) {
  const { t } = useUiTranslation('director')
  const skills = [
    { id: 'music_video' as DirectorSkill, label: t('chat.skills.musicVideo'), desc: t('chat.skills.musicVideoDesc'), icon: Music, active: true },
    { id: 'short_film' as DirectorSkill, label: t('chat.skills.shortFilm'), desc: t('chat.skills.shortFilmDesc'), icon: Film, active: true },
    { id: 'comic' as DirectorSkill, label: t('chat.skills.comic'), desc: t('chat.skills.comicDesc'), icon: BookOpen, active: true },
    { id: 'music_video' as DirectorSkill, label: t('chat.skills.videoPodcast'), desc: t('chat.comingSoon'), icon: Mic, active: false },
    { id: 'music_video' as DirectorSkill, label: t('chat.skills.viralVideo'), desc: t('chat.comingSoon'), icon: Sparkles, active: false },
  ]

  return (
    <div className="grid grid-cols-2 gap-2">
      {visibleDirectorSkills(skills).map((s) => (
        <button
          key={s.label}
          onClick={() => s.active && onSelect(s.id)}
          disabled={!s.active}
          title={controlReason(!s.active, 'disabled.actionInProgress')}
          className={`relative p-3 rounded-lg border text-left transition-all ${
            s.active
              ? 'border-accent-blue/30 bg-bg-tertiary/50 hover:border-accent-blue hover:bg-accent-blue/5 cursor-pointer'
              : 'border-border/30 bg-bg-tertiary/20 opacity-50 cursor-not-allowed'
          }`}
        >
          <s.icon size={16} className={s.active ? 'text-accent-blue mb-1.5' : 'text-text-muted mb-1.5'} />
          <div className="text-xs font-medium text-text-primary">{s.label}</div>
          <div className="text-[10px] text-text-muted mt-0.5">{s.desc}</div>
          {!s.active && (
            <span className="absolute top-1.5 right-1.5 text-[8px] bg-bg-hover text-text-muted px-1.5 py-0.5 rounded-full">
              {t('chat.soon')}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}

function PathChooser({ onSelect }: { onSelect: (path: ShortFilmPath) => void }) {
  const { t } = useUiTranslation('director')
  const paths = [
    { id: 'audio' as ShortFilmPath, label: t('chat.uploadAudio'), desc: t('chat.uploadAudioDesc'), icon: Upload },
    { id: 'story' as ShortFilmPath, label: t('chat.describeStory'), desc: t('chat.describeStoryDesc'), icon: FileText },
  ]
  return (
    <div className="grid grid-cols-2 gap-2">
      {paths.map((p) => (
        <button
          key={p.id}
          onClick={() => onSelect(p.id)}
          className="p-3 rounded-lg border border-accent-blue/30 bg-bg-tertiary/50 hover:border-accent-blue hover:bg-accent-blue/5 cursor-pointer text-left transition-all"
        >
          <p.icon size={16} className="text-accent-blue mb-1.5" />
          <div className="text-xs font-medium text-text-primary">{p.label}</div>
          <div className="text-[10px] text-text-muted mt-0.5">{p.desc}</div>
        </button>
      ))}
    </div>
  )
}

function UploadZone({
  dragOver, setDragOver, handleDrop, handleFile, loading, loadingMessage, audioName, isShortFilm,
}: {
  dragOver: boolean
  setDragOver: (v: boolean) => void
  handleDrop: (e: React.DragEvent) => void
  handleFile: (file: File) => void
  loading: boolean
  /** Sub-status string from the analyze polling loop. Falls back
   *  to the default ("Analyzing audio..." / "Transcribing dialogue...")
   *  when null. */
  loadingMessage: string | null
  audioName: string | null
  isShortFilm?: boolean
}) {
  const { t } = useUiTranslation('director')
  return (
    <div
      onDragOver={e => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={`border-2 border-dashed rounded-lg p-4 text-center transition-colors ${
        dragOver ? 'border-accent-blue bg-accent-blue/10' : 'border-border hover:border-border-light'
      }`}
    >
      {loading ? (
        <div className="flex flex-col items-center gap-2 py-2">
          <Loader2 size={20} className="animate-spin text-accent-blue" />
          {/* Sub-status (set by directorUploadAndAnalyze polling loop) takes
              precedence over the static fallback. Reflects backend phase:
              "Loading transcription model (first use downloads ~300MB)..." etc. */}
          <span className="text-[11px] text-text-muted text-center px-2">
            {loadingMessage || (isShortFilm ? t('chat.transcribing') : t('panel.analyzing'))}
          </span>
        </div>
      ) : audioName ? (
        <div className="flex flex-col items-center gap-1">
          <Music size={16} className="text-text-muted" />
          <span className="text-xs text-text-secondary truncate max-w-full">{audioName}</span>
        </div>
      ) : (
        <label className="cursor-pointer flex flex-col items-center gap-1.5">
          <Music size={20} className="text-accent-blue/60" />
          <span className="text-xs text-text-secondary">{isShortFilm ? t('chat.dropDialogue') : t('chat.dropSongOrVideo')}</span>
          <span className="text-[10px] text-text-muted">{t('chat.audioVideoFormats')}</span>
          <input aria-label={t('chat.audioVideoFormats')}
            type="file"
            accept={AUDIO_ACCEPT}
            className="hidden"
            onChange={e => {
              const file = e.target.files?.[0]
              if (file) handleFile(file)
            }}
          />
        </label>
      )}
    </div>
  )
}

function ReferenceImageUpload({
  referenceImage, refImagePreview, setReferenceImage, compact,
}: {
  referenceImage: File | null
  refImagePreview: string | null
  setReferenceImage: (file: File | null) => void
  compact?: boolean
}) {
  const fieldIds = useFieldIds()

  const { t } = useUiTranslation('director')
  const strengthLabel = useStore(s => s.modelOptions?.input_video_strength_label ?? '')
  const inputVideoStrength = useStore(s => s.params.input_video_strength ?? 1.0)
  const setParam = useStore(s => s.setParam)
  const [dragOver, setDragOver] = useState(false)

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file && file.type.startsWith('image/')) setReferenceImage(file)
  }, [setReferenceImage])

  if (compact) {
    return (
      <div className="space-y-2">
        {referenceImage && refImagePreview ? (
          <div className="flex items-center gap-2">
            <label className="cursor-pointer">
              <img
                src={refImagePreview}
                alt={t('panel.referenceAlt')}
                className="w-10 h-10 object-cover rounded-lg border border-border hover:border-accent-blue transition-colors"
                title={t('chat.clickToChange')}
              />
              <input
                type="file"
                accept={IMAGE_ACCEPT}
                className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) setReferenceImage(f) }}
              />
            </label>
            <div className="flex-1 min-w-0">
              <span className="text-[10px] text-text-muted">{t('chat.referenceImage')}</span>
            </div>
            <button
              onClick={() => setReferenceImage(null)}
              className="p-1 rounded hover:bg-bg-hover transition-colors"
              title={controlLabel('a11y.removeImage')} aria-label={controlLabel('a11y.removeImage')}
            >
              <X size={12} className="text-text-muted" />
            </button>
          </div>
        ) : (
          <label className="cursor-pointer flex items-center gap-2 border border-dashed border-border rounded px-2 py-1.5 hover:border-accent-blue transition-colors">
            <ImageIcon size={12} className="text-text-muted" />
            <span className="text-[10px] text-text-muted">{t('chat.addReferenceImage')}</span>
            <input aria-label={t('chat.addReferenceImage')}
              type="file"
              accept={IMAGE_ACCEPT}
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) setReferenceImage(f) }}
            />
          </label>
        )}
        {referenceImage && (
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label htmlFor={fieldIds('f0')} className="text-[11px] text-text-secondary">{strengthLabel || t('chat.imageStrength')}</label>
              <span className="text-[11px] text-text-muted tabular-nums">{inputVideoStrength.toFixed(2)}</span>
            </div>
            <input aria-label={strengthLabel || t('chat.imageStrength')} id={fieldIds('f0')} type="range" min={0} max={1} step={0.01} value={inputVideoStrength}
              onChange={e => setParam('input_video_strength', parseFloat(e.target.value))}
              className="w-full h-1 accent-accent-blue" />
            <p className="text-[9px] text-text-muted">{t('chat.lowerMotion')}</p>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {referenceImage && refImagePreview ? (
        <div className="relative">
          <label className="cursor-pointer block">
            <img
              src={refImagePreview}
              alt={t('panel.referenceAlt')}
              className="w-full h-24 object-cover rounded-lg border border-border hover:border-accent-blue transition-colors"
              title={t('chat.clickToChangeImage')}
            />
            <input
              type="file"
              accept={IMAGE_ACCEPT}
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) setReferenceImage(f) }}
            />
          </label>
          <button
            onClick={() => setReferenceImage(null)}
            className="absolute top-1.5 right-1.5 bg-bg-primary/80 rounded-full p-1 hover:bg-bg-hover transition-colors"
            title={controlLabel('a11y.removeImage')} aria-label={controlLabel('a11y.removeImage')}
          >
            <X size={12} className="text-text-muted" />
          </button>
          <span className="absolute bottom-1.5 left-1.5 text-[9px] text-white/80 bg-black/50 px-1.5 py-0.5 rounded">
            {t('chat.referenceImageChange')}
          </span>
        </div>
      ) : (
        <label
          className={`cursor-pointer block border-2 border-dashed rounded-lg p-4 text-center transition-colors ${
            dragOver ? 'border-accent-blue bg-accent-blue/10' : 'border-border hover:border-border-light'
          }`}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <div className="flex flex-col items-center gap-1.5">
            <ImageIcon size={20} className="text-accent-blue/60" />
            <span className="text-xs text-text-secondary">{t('chat.dropReference')}</span>
            <span className="text-[10px] text-text-muted">{t('chat.createsStartImages')}</span>
          </div>
          <input aria-label={t('chat.dropReference')}
            type="file"
            accept={IMAGE_ACCEPT}
            className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) setReferenceImage(f) }}
          />
        </label>
      )}
      {referenceImage && (
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <label htmlFor={fieldIds('f1')} className="text-[11px] text-text-secondary">{strengthLabel || t('chat.imageStrength')}</label>
            <span className="text-[11px] text-text-muted tabular-nums">{inputVideoStrength.toFixed(2)}</span>
          </div>
          <input aria-label={strengthLabel || t('chat.imageStrength')} id={fieldIds('f1')} type="range" min={0} max={1} step={0.01} value={inputVideoStrength}
            onChange={e => setParam('input_video_strength', parseFloat(e.target.value))}
            className="w-full h-1 accent-accent-blue" />
          <p className="text-[9px] text-text-muted">{t('chat.lowerMotion')}</p>
        </div>
      )}
    </div>
  )
}

function DraggableRefRow({ file, label, index, onRemove, onLabelChange, onReorder, placeholder }: {
  file: File; label: string; index: number
  onRemove: (i: number) => void
  onLabelChange: (i: number, v: string) => void
  onReorder: (from: number, to: number) => void
  placeholder: string
}) {
  const { t } = useUiTranslation('director')
  const [dragOver, setDragOver] = useState(false)
  const previewUrl = useObjectUrl(file)

  return (
    <div
      draggable
      onDragStart={e => { e.dataTransfer.setData('text/plain', String(index)); e.dataTransfer.effectAllowed = 'move' }}
      onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => {
        e.preventDefault(); setDragOver(false)
        const from = parseInt(e.dataTransfer.getData('text/plain'), 10)
        if (!isNaN(from) && from !== index) onReorder(from, index)
      }}
      className={`flex items-center gap-1.5 group cursor-grab active:cursor-grabbing transition-colors rounded ${
        dragOver ? 'bg-accent-blue/10 border border-accent-blue/30' : ''
      }`}
    >
      <div className="relative flex-shrink-0">
        <img src={previewUrl || ''} alt={t('chat.refN', { n: index + 1 })}
          className="w-[60px] h-[60px] object-cover rounded border border-border pointer-events-none" />
        <button onClick={() => onRemove(index)}
          className="absolute -top-1 -right-1 bg-red-500 rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity z-10" title={controlLabel('a11y.removeReference')} aria-label={controlLabel('a11y.removeReference')}>
          <X size={8} className="text-white" />
        </button>
        <span className="absolute bottom-0 left-0 bg-black/60 text-white text-[7px] px-1 rounded-br rounded-tl pointer-events-none">
          {index + 1}
        </span>
      </div>
      <input aria-label={placeholder}
        type="text"
        value={label}
        onChange={e => onLabelChange(index, e.target.value)}
        placeholder={placeholder}
        className="flex-1 min-w-0 bg-bg-secondary border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary placeholder:text-text-muted focus:border-accent-blue outline-none"
      />
    </div>
  )
}

function AdditionalRefsSection() {
  const charRefs = useStore(s => s.directorCharacterRefs)
  const charLabels = useStore(s => s.directorCharacterRefLabels)
  const locRefs = useStore(s => s.directorLocationRefs)
  const locLabels = useStore(s => s.directorLocationRefLabels)
  const addCharRef = useStore(s => s.directorAddCharacterRef)
  const removeCharRef = useStore(s => s.directorRemoveCharacterRef)
  const setCharLabel = useStore(s => s.directorSetCharacterRefLabel)
  const reorderCharRefs = useStore(s => s.directorReorderCharacterRefs)
  const addLocRef = useStore(s => s.directorAddLocationRef)
  const removeLocRef = useStore(s => s.directorRemoveLocationRef)
  const setLocLabel = useStore(s => s.directorSetLocationRefLabel)
  const reorderLocRefs = useStore(s => s.directorReorderLocationRefs)
  const referenceImage = useStore(s => s.directorReferenceImage)
  const videoModel = useStore(s => s.selectedModelPerMode.video || 'ltx2_22B_distilled_1_1')
  const h3VideoRefs = useStore(s => s.directorH3VideoRefs)
  const h3AudioRefs = useStore(s => s.directorH3AudioRefs)
  const addH3VideoRef = useStore(s => s.directorAddH3VideoRef)
  const removeH3VideoRef = useStore(s => s.directorRemoveH3VideoRef)
  const addH3AudioRef = useStore(s => s.directorAddH3AudioRef)
  const removeH3AudioRef = useStore(s => s.directorRemoveH3AudioRef)
  const voiceRef = useStore(s => s.directorVoiceRef)
  const setVoiceRef = useStore(s => s.setDirectorVoiceRef)
  const identityScale = useStore(s => s.directorIdentityGuidanceScale)
  const setIdentityScale = useStore(s => s.setDirectorIdentityGuidanceScale)
  const clipPlans = useStore(s => s.directorClipPlans)
  const isDirectVideo = useStore(
    s => s.directorMusicVideoTreatment.generation_mode === 'direct_video'
  )
  const h3ReferenceMode = useStore(s => s.savedParamsPerMode.video?.h3_reference_mode || 'first_frame')
  const setH3ReferenceMode = useStore(s => s.setDirectorH3ReferenceMode)
  const isH3 = videoModel.startsWith('minimax_h3')
  const h3UserRefCount = (referenceImage ? 1 : 0) + charRefs.length + (locRefs.length ? 1 : 0) + h3VideoRefs.length + h3AudioRefs.length
  const voiceReferenceEnabled = useStore(s => s.servicesConfig?.voice_reference_enabled ?? false)
  const selectedVideoModel = useStore(s => s.selectedModelPerMode.video || 'ltx2_22B_distilled_1_1')
  const supportsVoiceReference = useStore(s => (
    s.models.find(model => model.model_type === selectedVideoModel)
      ?.director?.supports_voice_reference ?? false
  ))
  const voiceReferenceMode = useStore(s => (
    s.models.find(model => model.model_type === selectedVideoModel)
      ?.director?.voice_reference_mode ?? 'none'
  ))
  const { t } = useUiTranslation('director')
  const [expanded, setExpanded] = useState(
    charRefs.length > 0 || locRefs.length > 0 || h3VideoRefs.length > 0
      || h3AudioRefs.length > 0 || voiceRef !== null
  )

  const handleFiles = useCallback((files: FileList | null, type: 'char' | 'loc') => {
    if (!files) return
    const add = type === 'char' ? addCharRef : addLocRef
    const imageCount = charRefs.length + (locRefs.length ? 1 : 0) + (referenceImage ? 1 : 0)
    const shouldLimit = isH3 && h3ReferenceMode === 'references' && type === 'char'
    const available = shouldLimit ? Math.max(0, Math.min(8 - imageCount, 11 - h3UserRefCount)) : files.length
    Array.from(files).slice(0, available).forEach(f => { if (f.type.startsWith('image/')) add(f) })
  }, [addCharRef, addLocRef, charRefs.length, locRefs.length, referenceImage, isH3, h3ReferenceMode, h3UserRefCount])

  const nativeVoiceReference = voiceReferenceMode === 'native_reference'
  const showVoiceReference = supportsVoiceReference
    && (nativeVoiceReference || voiceReferenceEnabled)
  const totalRefs = charRefs.length + locRefs.length + h3VideoRefs.length
    + h3AudioRefs.length + (showVoiceReference && voiceRef ? 1 : 0)

  return (
    <div className="mt-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-[10px] text-text-muted hover:text-text-secondary transition-colors w-full"
      >
        {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        <Users size={10} />
        <span>{t('chat.additionalRefs')}</span>
        {totalRefs > 0 && <span className="ml-auto bg-accent-blue/20 text-accent-blue px-1.5 rounded-full text-[9px]">{totalRefs}</span>}
      </button>
      {expanded && (
        <div className="mt-1.5 space-y-2 pl-1">
          {/* Character References */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-text-secondary">{t('chat.characterRefs')}</span>
              <label className="cursor-pointer text-[9px] text-accent-blue hover:underline">
                {t('chat.add')}
                <input aria-label={t('chat.add')} type="file" accept={IMAGE_ACCEPT} multiple className="hidden"
                  onChange={e => handleFiles(e.target.files, 'char')} />
              </label>
            </div>
            {charRefs.length > 0 && (
              <div className="space-y-1">
                {charRefs.map((f, i) => (
                  <DraggableRefRow key={`c${i}-${f.name}`} file={f} label={charLabels[i] || ''} index={i}
                    onRemove={removeCharRef} onLabelChange={setCharLabel} onReorder={reorderCharRefs}
                    placeholder={t('chat.characterRefPlaceholder')} />
                ))}
              </div>
            )}
            {charRefs.length === 0 && (
              <p className="text-[9px] text-text-muted italic">{t('chat.characterRefsHint')}</p>
            )}
          </div>
          {/* Location References */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-text-secondary">{t('chat.locationRefs')}</span>
              <label className="cursor-pointer text-[9px] text-accent-blue hover:underline">
                {t('chat.add')}
                <input aria-label={t('chat.add')} type="file" accept={IMAGE_ACCEPT} multiple className="hidden"
                  onChange={e => handleFiles(e.target.files, 'loc')} />
              </label>
            </div>
            {locRefs.length > 0 && (
              <div className="space-y-1">
                {locRefs.map((f, i) => (
                  <DraggableRefRow key={`l${i}-${f.name}`} file={f} label={locLabels[i] || ''} index={i}
                    onRemove={removeLocRef} onLabelChange={setLocLabel} onReorder={reorderLocRefs}
                    placeholder={t('chat.locationRefPlaceholder')} />
                ))}
              </div>
            )}
            {locRefs.length === 0 && (
              <p className="text-[9px] text-text-muted italic">{t('chat.locationRefsHint')}</p>
            )}
          </div>
          {/* LTX uses an ID-LoRA; H3 Omni maps the sample as a native voice
              reference in each shot's Ref2VA manifest. */}
          {showVoiceReference && <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-text-secondary"><Mic size={9} className="inline mr-0.5" />{t('chat.voiceRef')}</span>
              {!voiceRef ? (
                <label className="cursor-pointer text-[9px] text-accent-blue hover:underline">
                  {t('chat.add')}
                  <input aria-label={t('chat.add')} type="file" accept={AUDIO_ACCEPT} className="hidden"
                    onChange={e => { const f = e.target.files?.[0]; if (f) setVoiceRef(f); e.target.value = '' }} />
                </label>
              ) : (
                <button onClick={() => setVoiceRef(null)} className="text-[9px] text-red-400 hover:text-red-300">{t('chat.remove')}</button>
              )}
            </div>
            {voiceRef ? (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 bg-bg-tertiary rounded px-1.5 py-1">
                  <Mic size={10} className="text-accent-blue shrink-0" />
                  <span className="text-[9px] text-text-secondary truncate">{voiceRef.name}</span>
                </div>
                {!nativeVoiceReference && <div className="flex items-center gap-1.5">
                  <span className="text-[9px] text-text-muted whitespace-nowrap">{t('chat.identityScale')}</span>
                  <input aria-label={t('chat.identityScale')} type="range" min={0} max={10} step={0.5} value={identityScale}
                    onChange={e => setIdentityScale(parseFloat(e.target.value))}
                    className="flex-1 h-1 accent-accent-blue" />
                  <span className="text-[9px] text-text-muted w-5 text-right">{identityScale}</span>
                </div>}
              </div>
            ) : (
              <p className="text-[9px] text-text-muted italic">
                {nativeVoiceReference
                  ? t('chat.voiceSampleH3')
                  : t('chat.voiceSampleShort')}
              </p>
            )}
          </div>}
          {isH3 && !isDirectVideo && <div className="rounded-md border border-cyan-500/25 bg-cyan-500/5 p-2 space-y-2">
            <div>
              <div className="flex items-center justify-between">
                <label className="text-[10px] font-medium text-cyan-200" htmlFor="director-h3-reference-mode">
                  {t('dashboard.h3Conditioning')}
                </label>
                {h3ReferenceMode === 'references' && <span className="text-[9px] text-text-muted">{t('chat.refsPerShot', { count: h3UserRefCount, max: 11 })}</span>}
              </div>
              <select aria-label={t('dashboard.h3Conditioning')}
                id="director-h3-reference-mode"
                value={h3ReferenceMode}
                onChange={event => setH3ReferenceMode(event.target.value as 'first_frame' | 'references')}
                className="mt-1 w-full rounded border border-cyan-500/25 bg-bg-tertiary px-1.5 py-1 text-[10px] text-text-primary focus:outline-none focus:border-cyan-400"
              >
                <option value="first_frame">{t('chat.fl2vaOption')}</option>
                <option value="references">{t('chat.ref2vaOption')}</option>
              </select>
              <p className="text-[9px] text-text-muted leading-tight mt-0.5">
                {h3ReferenceMode === 'first_frame'
                  ? t('chat.fl2vaHint')
                  : t('chat.ref2vaHint')}
              </p>
            </div>
            {h3ReferenceMode === 'references' && <><div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-text-secondary"><Film size={9} className="inline mr-0.5" />{t('chat.videoRefs', { count: h3VideoRefs.length, max: 3 })}</span>
                {h3VideoRefs.length < 3 && h3UserRefCount < 11 && <label className="cursor-pointer text-[9px] text-accent-blue hover:underline">
                  {t('chat.add')}
                  <input aria-label={t('chat.add')} type="file" accept={H3_VIDEO_ACCEPT} multiple className="hidden"
                    onChange={e => {
                      Array.from(e.target.files || []).slice(0, Math.min(3 - h3VideoRefs.length, 11 - h3UserRefCount)).forEach(addH3VideoRef)
                      e.target.value = ''
                    }} />
                </label>}
              </div>
              {h3VideoRefs.map((file, index) => (
                <div key={`${file.name}-${index}`} className="flex items-center gap-1.5 bg-bg-tertiary rounded px-1.5 py-1 mb-1">
                  <Film size={10} className="text-cyan-300 shrink-0" />
                  <span className="text-[9px] text-text-secondary truncate flex-1">{file.name}</span>
                  <button onClick={() => removeH3VideoRef(index)} className="text-red-400" title={controlLabel('a11y.removeVideoReference')} aria-label={controlLabel('a11y.removeVideoReference')}><X size={9} /></button>
                </div>
              ))}
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-text-secondary"><Mic size={9} className="inline mr-0.5" />{t('chat.audioRefs', { count: h3AudioRefs.length, max: 3 })}</span>
                {h3AudioRefs.length < 3 && h3UserRefCount < 11 && <label className="cursor-pointer text-[9px] text-accent-blue hover:underline">
                  {t('chat.add')}
                  <input aria-label={t('chat.add')} type="file" accept={H3_AUDIO_ACCEPT} multiple className="hidden"
                    onChange={e => {
                      Array.from(e.target.files || []).slice(0, Math.min(3 - h3AudioRefs.length, 11 - h3UserRefCount)).forEach(addH3AudioRef)
                      e.target.value = ''
                    }} />
                </label>}
              </div>
              {h3AudioRefs.map((file, index) => (
                <div key={`${file.name}-${index}`} className="flex items-center gap-1.5 bg-bg-tertiary rounded px-1.5 py-1 mb-1">
                  <Mic size={10} className="text-cyan-300 shrink-0" />
                  <span className="text-[9px] text-text-secondary truncate flex-1">{file.name}</span>
                  <button onClick={() => removeH3AudioRef(index)} className="text-red-400" title={controlLabel('a11y.removeAudioReference')} aria-label={controlLabel('a11y.removeAudioReference')}><X size={9} /></button>
                </div>
              ))}
              <p className="text-[9px] text-text-muted/70">{t('chat.refDurationHint')}</p>
            </div>
            {clipPlans.length > 0 && <div className="border-t border-cyan-500/15 pt-1.5 space-y-1">
              <p className="text-[9px] font-medium text-cyan-200">{t('chat.refsPerShotHeading')}</p>
              {clipPlans.map((plan, index) => {
                const metadata = plan.metadata || {}
                const requested = String(metadata.location_ref_label || '')
                const match = requested
                  ? locLabels.findIndex(label => label.trim().toLocaleLowerCase() === requested.trim().toLocaleLowerCase())
                  : (locRefs.length === 1 ? 0 : -1)
                const location = match >= 0
                  ? t('chat.locationFile', { label: locLabels[match] || t('chat.location'), file: locRefs[match]?.name || '' })
                  : t('chat.noLocationMatch')
                const characters = charRefs.map((file, charIndex) => charLabels[charIndex] || file.name)
                return <div key={index} className="rounded bg-bg-tertiary px-1.5 py-1 text-[9px] leading-tight">
                  <div className="text-text-secondary">{t('chat.shotGeneratedFrame', { n: index + 1 })}</div>
                  {characters.length > 0 && <div className="text-text-muted">{t('chat.charactersList', { names: characters.join(', ') })}</div>}
                  <div className={match >= 0 ? 'text-text-muted' : 'text-amber-300'}>{t('dashboard.locationList', { value: location })}</div>
                </div>
              })}
            </div>}</>}
          </div>}
        </div>
      )}
    </div>
  )
}

function AnalysisSummary({
  analysis, showDetails, setShowDetails, isShortFilm,
}: {
  analysis: NonNullable<ReturnType<typeof useStore.getState>['directorAnalysis']>
  showDetails: boolean
  setShowDetails: (v: boolean | ((p: boolean) => boolean)) => void
  isShortFilm?: boolean
}) {
  const { t } = useUiTranslation('director')
  // Count unique speakers
  const speakerCount = new Set(
    (analysis.lyrics || []).map(l => l.speaker).filter(Boolean)
  ).size
  const downloadSrt = () => {
    if (!analysis.lyrics_srt) return
    const url = URL.createObjectURL(new Blob([analysis.lyrics_srt], { type: 'application/x-subrip;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'lyrics-timeline.srt'
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-1">
      <p className="text-xs text-text-secondary mb-1">
        {isShortFilm ? t('chat.transcriptionComplete') : t('chat.analysisComplete')}
      </p>
      {analysis.warnings?.map((warning, index) => (
        <p key={index} className="rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1 text-[10px] text-amber-300">
          {warning}
        </p>
      ))}
      {analysis.lyric_timing && !isShortFilm && (
        <div className="flex items-center justify-between gap-2 rounded border border-cyan-500/20 bg-cyan-500/5 px-2 py-1 text-[10px]">
          <span className="text-cyan-100">
            {t('chat.lyricTimeline', { percent: Math.round(analysis.lyric_timing.coverage * 100) })}
          </span>
          {analysis.lyrics_srt && (
            <button type="button" onClick={downloadSrt} className="flex shrink-0 items-center gap-1 text-cyan-300 hover:text-cyan-100">
              <Download size={10} /> {'SRT' // i18n-ok: SRT
              }
            </button>
          )}
        </div>
      )}
      <button
        onClick={() => setShowDetails(v => !v)}
        className="flex items-center gap-3 text-[11px] text-text-muted w-full hover:text-text-secondary transition-colors"
      >
        <ChevronDown size={10} className={`transition-transform ${showDetails ? '' : '-rotate-90'}`} />
        <span>{formatTime(analysis.duration)}</span>
        {!isShortFilm && <span>{t('panel.bpm', { bpm: analysis.bpm.toFixed(0) })}</span>}
        {isShortFilm && speakerCount > 0 && <span>{t('chat.speakers', { count: speakerCount })}</span>}
        {!isShortFilm && <span>{t('panel.sectionsCount', { count: analysis.sections.length })}</span>}
        {analysis.lyrics && <span>{t(isShortFilm ? 'chat.dialogueLines' : 'panel.lyricSegments', { count: analysis.lyrics.length })}</span>}
      </button>

      {showDetails && (
        // No inner scroll — chat panel handles scrolling.
        <div className="bg-bg-tertiary rounded-lg p-2 space-y-2 text-[10px]">
          <div>
            <div className="text-text-muted uppercase tracking-wider mb-1 font-medium">{t('panel.sections')}</div>
            <div className="space-y-0.5">
              {analysis.sections.map((sec, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-text-muted w-16 shrink-0">
                    {formatTime(sec.start)}-{formatTime(sec.end)}
                  </span>
                  <SectionBadge label={sec.label} />
                  <EnergyDot energy={sec.energy} />
                  <span className="text-text-muted">{(sec.energy * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          </div>

          {analysis.lyrics && analysis.lyrics.length > 0 && (
            <div>
              <div className="text-text-muted uppercase tracking-wider mb-1 font-medium">
                {t('panel.lyrics')} {analysis.lyric_timing?.method === 'authoritative_lyrics_word_alignment'
                  ? t('chat.lyricsAligned')
                  : analysis.song_structure?.length ? t('chat.lyricsStructured') : t('panel.lyricsWhisper')}
              </div>
              <div className="space-y-0.5">
                {analysis.song_structure && analysis.song_structure.length > 0 ? (
                  analysis.song_structure.map((section, si) => {
                    const nextStart = si < analysis.song_structure!.length - 1
                      ? analysis.song_structure![si + 1].start
                      : Infinity
                    const sectionLyrics = analysis.lyrics!.filter(
                      seg => seg.start >= section.start && seg.start < nextStart
                    )
                    return (
                      <div key={si} className="mb-1.5">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <SectionBadge label={section.label} />
                          <span className="text-text-muted">{formatTime(section.start)}</span>
                          <span className="text-text-secondary font-medium">[{section.display_label}]</span>
                        </div>
                        {sectionLyrics.map((seg, li) => (
                          <div key={li} className="flex gap-2 pl-2">
                            <span className="text-text-muted w-14 shrink-0 text-right">
                              {formatTime(seg.start)}
                            </span>
                            <span className="text-text-secondary">
                              {seg.speaker && (
                                <span className="text-accent-blue text-[9px] mr-1">[{seg.speaker}]</span>
                              )}
                              {seg.text}
                            </span>
                          </div>
                        ))}
                        {sectionLyrics.length === 0 && (
                          <div className="pl-2 text-text-muted italic">{t('panel.instrumental')}</div>
                        )}
                      </div>
                    )
                  })
                ) : (
                  analysis.lyrics.map((seg, i) => (
                    <div key={i} className="flex gap-2">
                      <span className="text-text-muted w-16 shrink-0">
                        {formatTime(seg.start)}-{formatTime(seg.end)}
                      </span>
                      <span className="text-text-secondary">
                        {seg.speaker && (
                          <span className="text-accent-blue text-[9px] mr-1">[{seg.speaker}]</span>
                        )}
                        {seg.text}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StructureView({
  plannedClips, energyBias, localBias, setLocalBias, sliderRef, setEnergyBias,
  loading, totalClipDuration, beatDistribution, confirmStructure, isActive, isShortFilm,
  isMusicVideo, pacingProfile, setPacingProfile,
}: {
  plannedClips: ReturnType<typeof useStore.getState>['directorPlannedClips']
  energyBias: number
  localBias: number | null
  setLocalBias: (v: number | null) => void
  sliderRef: React.MutableRefObject<number | null>
  setEnergyBias: (bias: number) => Promise<void>
  loading: boolean
  totalClipDuration: number
  beatDistribution: string
  confirmStructure: () => void
  isActive: boolean
  isShortFilm?: boolean
  isMusicVideo?: boolean
  pacingProfile: 'cinematic' | 'balanced' | 'rhythmic'
  setPacingProfile: (profile: 'cinematic' | 'balanced' | 'rhythmic') => Promise<void>
}) {
  const fieldIds = useFieldIds()

  const { t } = useUiTranslation('director')
  const pacingChoices = [
    ['cinematic', t('chat.pacingCinematic'), t('chat.pacingRangeCinematic')],
    ['balanced', t('chat.pacingBalanced'), t('chat.pacingRangeBalanced')],
    ['rhythmic', t('chat.pacingRhythmic'), t('chat.pacingRangeRhythmic')],
  ] as const
  return (
    <div className="space-y-3">
      <p className="text-xs text-text-secondary">
        {isShortFilm
          ? t('chat.structureShortFilm')
          : t('chat.structureMusic')}
      </p>

      {isActive && isMusicVideo && (
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label className="text-[11px] uppercase tracking-wider text-text-muted">{t('chat.editingRhythm')}</label>
            <span className="text-[10px] text-text-muted">{t('chat.generatedClips', { count: plannedClips.length })}</span>
          </div>
          <div className="grid grid-cols-3 gap-1">
            {pacingChoices.map(([value, label, duration]) => (
              <button
                key={value}
                type="button"
                disabled={loading}
                title={controlReason(loading, 'disabled.actionInProgress')}
                onClick={() => void setPacingProfile(value)}
                className={`rounded-md border px-1.5 py-1.5 text-center transition-colors disabled:opacity-50 ${pacingProfile === value
                  ? 'border-accent-blue bg-accent-blue/10 text-accent-blue'
                  : 'border-border text-text-secondary hover:border-accent-blue/50'}`}
              >
                <span className="block text-[10px] font-medium">{label}</span>
                <span className="block text-[9px] text-text-muted">{duration}</span>
              </button>
            ))}
          </div>
          <p className="mt-1 text-[9px] leading-relaxed text-text-muted">
            {t('chat.moreCuts')}
          </p>
        </div>
      )}

      {isActive && !isMusicVideo && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label htmlFor={fieldIds('f0')} className="text-[11px] text-text-muted uppercase tracking-wider">{isShortFilm ? t('chat.scenePacing') : t('panel.cutSpeed')}</label>
            <span className="text-xs text-text-secondary">
              {(localBias ?? energyBias) > 0 ? '+' : ''}{localBias ?? energyBias}
            </span>
          </div>
          <input aria-label={isShortFilm ? t('chat.scenePacing') : t('panel.cutSpeed')} id={fieldIds('f0')}
            type="range"
            min={-2}
            max={2}
            step={1}
            value={localBias ?? energyBias}
            onChange={e => {
              const v = Number(e.target.value)
              setLocalBias(v)
              sliderRef.current = v
            }}
            onMouseUp={() => {
              if (sliderRef.current !== null && sliderRef.current !== energyBias) {
                setEnergyBias(sliderRef.current)
              }
              setLocalBias(null)
              sliderRef.current = null
            }}
            onTouchEnd={() => {
              if (sliderRef.current !== null && sliderRef.current !== energyBias) {
                setEnergyBias(sliderRef.current)
              }
              setLocalBias(null)
              sliderRef.current = null
            }}
            className="w-full"
          />
          <div className="flex items-center justify-between mt-1 text-[10px] text-text-muted">
            <span>{isShortFilm ? t('chat.longerScenes') : t('panel.slowerCuts')}</span>
            <span>{isShortFilm ? t('chat.shorterScenes') : t('panel.fasterCuts')}</span>
          </div>
        </div>
      )}

      <div className="bg-bg-tertiary rounded-lg p-2 space-y-2">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-text-secondary font-medium">{t(isShortFilm ? 'chat.scenesCount' : 'panel.clipsCount', { count: plannedClips.length })}</span>
          <span className="text-text-muted">{t('panel.totalTime', { time: formatTime(totalClipDuration) })}</span>
        </div>

        {loading ? (
          <div className="flex items-center gap-1.5 text-[10px] text-text-muted py-1">
            <Loader2 size={10} className="animate-spin" /> {t('panel.recalculating')}
          </div>
        ) : (
          <>
            <div className="flex gap-px h-8 rounded overflow-hidden">
              {plannedClips.map((clip, i) => {
                const clipDur = clip.end - clip.start
                const totalDur = plannedClips.reduce((s, c) => s + (c.end - c.start), 0)
                const widthPct = isShortFilm
                  ? Math.max((clipDur / totalDur) * 100, 1.5)
                  : Math.max((clip.beat_count / plannedClips.reduce((s, c) => s + c.beat_count, 0)) * 100, 1.5)
                const barColor = sectionBarColors[clip.section_label] || 'bg-gray-500'
                const section = sectionDisplayName(clip.section_label)
                const tooltipLabel = isShortFilm
                  ? t('chat.sceneTooltip', { n: i + 1, section, seconds: clipDur.toFixed(1) })
                  : t('panel.clipTooltip', { n: i + 1, section, beats: clip.beat_count, seconds: clipDur.toFixed(1) })
                return (
                  <div
                    key={i}
                    className={`${barColor} opacity-70 hover:opacity-100 transition-opacity relative group cursor-default`}
                    style={{ width: `${widthPct}%` }}
                    title={tooltipLabel}
                  >
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10 pointer-events-none">
                      <div className="bg-bg-primary border border-border rounded px-1.5 py-1 text-[9px] text-text-secondary whitespace-nowrap shadow-lg">
                        {tooltipLabel}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="text-[9px] text-text-muted space-y-1">
              {!isShortFilm && <div>{beatDistribution}</div>}
              <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                {Object.entries(sectionBarColors).map(([label, color]) => {
                  const count = plannedClips.filter(c => c.section_label === label).length
                  if (count === 0) return null
                  return (
                    <div key={label} className="flex items-center gap-1">
                      <span className={`w-2 h-2 rounded-sm ${color}`} />
                      <span>{t('panel.sectionCount', { label: sectionDisplayName(label), count })}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </>
        )}
      </div>

      {isActive && (
        <button
          onClick={confirmStructure}
          disabled={loading || plannedClips.length === 0}
          title={firstControlReason([
            [loading, 'disabled.actionInProgress'],
            [plannedClips.length === 0, 'disabled.sendNeedsStep'],
          ])}
          className="w-full py-2 rounded-lg bg-accent-blue text-white text-xs font-medium hover:bg-accent-blue-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
        >
          <ChevronRight size={12} /> {t('panel.continue')}
        </button>
      )}
    </div>
  )
}

/**
 * DirectorAdvancedAccordion — collapsed-by-default panel exposing the
 * post-processing knobs (spatial upsampling, film grain, self refiner)
 * that used to live in the Director Parameters settings tab. Sits in
 * the chat sidebar alongside the LoRA accordion so per-shoot tweaks
 * are co-located with the rest of the per-shoot setup.
 *
 * Defaults are intentionally "off" for all controls so a user who
 * never opens this accordion gets clean unprocessed output. Each
 * control has a one-line description making clear what it does and
 * what it costs (e.g. "may introduce artifacts" for the refiner)
 * rather than implying a quality hierarchy.
 *
 * No "Quality" preset bundling — the three controls are independent
 * with distinct purposes (resolution change vs aesthetic vs
 * experimental). See the design discussion captured in commit notes.
 */
function DirectorAdvancedAccordion() {
  const fieldIds = useFieldIds()

  const { t } = useUiTranslation('director')
  const [open, setOpen] = useState(false)
  const videoModel = useStore(s => s.selectedModelPerMode.video || 'ltx2_22B_distilled_1_1')
  const videoStepsByModel = useStore(s => s.directorVideoInferenceStepsByModel)
  const setVideoSteps = useStore(s => s.setDirectorVideoInferenceSteps)
  const maxShotFramesByModel = useStore(s => s.directorVideoMaxShotFramesByModel)
  const setMaxShotFrames = useStore(s => s.setDirectorVideoMaxShotFrames)
  const turboModeByModel = useStore(s => s.directorH3TurboModeByModel)
  const setTurboMode = useStore(s => s.setDirectorH3TurboMode)
  const savedVideoLoras = useStore(s => s.savedLoraPerMode.video)
  const directorSetLora = useStore(s => s.directorSetLora)
  const directorResolution = useStore(s => s.directorResolution)
  const directorAspectRatio = useStore(s => s.directorAspectRatio)
  const totalVramGb = useStore(s => s.systemStats?.gpu.vram_total_gb ?? 0)
  const [directorVideoOptions, setDirectorVideoOptions] = useState<ModelOptions | null>(null)
  const shotImageSupport = useStore(s => s.models.find(
    model => model.model_type === videoModel,
  )?.director?.shot_image_support)
  const shotImageGuidance = useStore(s => s.directorShotImageGuidance)
  const setShotImageGuidance = useStore(s => s.setDirectorShotImageGuidance)
  const hasVisualReferences = useStore(s => Boolean(
    s.directorReferenceImage
    || s.directorReferenceImagePath
    || s.directorCharacterRefs.length
    || s.directorCharacterRefPaths.length
    || s.directorLocationRefs.length
    || s.directorLocationRefPaths.length
  ))
  const generateShotImages = directorWillGenerateShotImages(
    shotImageSupport,
    shotImageGuidance,
    hasVisualReferences,
  )

  // Image post-processing
  const imgUpsampling = useStore(s => s.directorImageSpatialUpsampling)
  const setImgUpsampling = useStore(s => s.setDirectorImageSpatialUpsampling)
  const imgGrain = useStore(s => s.directorImageFilmGrainIntensity)
  const setImgGrain = useStore(s => s.setDirectorImageFilmGrainIntensity)
  const imgGrainSat = useStore(s => s.directorImageFilmGrainSaturation)
  const setImgGrainSat = useStore(s => s.setDirectorImageFilmGrainSaturation)

  // Video post-processing
  const vidUpsampling = useStore(s => s.directorVideoSpatialUpsampling)
  const setVidUpsampling = useStore(s => s.setDirectorVideoSpatialUpsampling)
  const vidGrain = useStore(s => s.directorVideoFilmGrainIntensity)
  const setVidGrain = useStore(s => s.setDirectorVideoFilmGrainIntensity)
  const vidGrainSat = useStore(s => s.directorVideoFilmGrainSaturation)
  const setVidGrainSat = useStore(s => s.setDirectorVideoFilmGrainSaturation)
  const vidSelfRefiner = useStore(s => s.directorVideoSelfRefiner)
  const setVidSelfRefiner = useStore(s => s.setDirectorVideoSelfRefiner)

  // Fetch the selected Director model's sampling contract without routing it
  // through Studio's global modelOptions/params state. That separation is the
  // point of this control: changing steps in either surface must not silently
  // modify the other one.
  useEffect(() => {
    let cancelled = false
    fetchModelOptions(videoModel)
      .then(options => {
        if (cancelled) return
        setDirectorVideoOptions(options)
        const rawDefault = options.default_num_inference_steps
        if (rawDefault != null && Number.isFinite(rawDefault)) {
          const current = useStore.getState().directorVideoInferenceStepsByModel[videoModel]
          if (current == null) setVideoSteps(videoModel, rawDefault)
        }
      })
      .catch(() => {
        if (!cancelled) setDirectorVideoOptions(null)
      })
    return () => { cancelled = true }
  }, [setVideoSteps, videoModel])

  const activeDirectorVideoOptions = directorVideoOptions?.model_type === videoModel
    ? directorVideoOptions
    : null
  const rawDefaultVideoSteps = activeDirectorVideoOptions?.default_num_inference_steps
  const defaultVideoSteps = rawDefaultVideoSteps == null
    ? null
    : Math.max(1, Math.min(50, Math.round(rawDefaultVideoSteps)))
  const configuredVideoSteps = videoStepsByModel[videoModel]
  const videoSteps = activeDirectorVideoOptions?.lock_inference_steps
    ? defaultVideoSteps
    : (configuredVideoSteps ?? defaultVideoSteps)
  const videoStepsLocked = activeDirectorVideoOptions?.lock_inference_steps === true
  const resolvedVideoResolution = resolveResolution(
    activeDirectorVideoOptions,
    directorResolution,
    directorAspectRatio,
  )
  const windowRecommendation = recommendedWindowProfile(
    activeDirectorVideoOptions?.director_memory_policy
      || activeDirectorVideoOptions?.sliding_window_memory_policy,
    resolvedVideoResolution,
    totalVramGb,
  )
  const safeShotFrames = windowRecommendation?.frames ?? null
  const manualMaxShotFrames = maxShotFramesByModel[videoModel] ?? null
  const framesMinimum = activeDirectorVideoOptions?.frames_minimum ?? 1
  const framesMaximum = activeDirectorVideoOptions?.frames_maximum ?? framesMinimum
  const framesStep = activeDirectorVideoOptions?.frames_steps ?? 1
  const nativeShotChoices = [124, 175, 243, 345].filter(frames => (
    frames >= framesMinimum
    && frames <= framesMaximum
    && (frames - framesMinimum) % Math.max(1, framesStep) === 0
  ))
  const turboOption = activeDirectorVideoOptions?.minimax_h3_turbo
  const turboSelected = Boolean(
    turboOption
    && turboModeByModel[videoModel] === true
    && savedVideoLoras?.activated_loras?.includes(turboOption.filename)
  )

  const setDirectorTurbo = (checked: boolean) => {
    if (!turboOption) return
    const current = savedVideoLoras || {
      activated_loras: [],
      loras_multipliers: '',
      loraWeights: {},
      availableLoras: [],
    }
    const nextLoras = current.activated_loras.filter(
      filename => filename !== turboOption.filename,
    )
    const nextWeights = { ...current.loraWeights }
    delete nextWeights[turboOption.filename]
    if (checked) {
      nextLoras.push(turboOption.filename)
      nextWeights[turboOption.filename] = [turboOption.weight]
    }
    const nextAvailable = current.availableLoras.includes(turboOption.filename)
      ? current.availableLoras
      : [...current.availableLoras, turboOption.filename]
    const multipliers = nextLoras.map(filename => (
      (nextWeights[filename] || [1]).map(value => value.toFixed(2)).join(';')
    )).join(' ')
    directorSetLora('video', nextLoras, multipliers, nextWeights, nextAvailable)
    setTurboMode(videoModel, checked)
    if (checked) {
      setVideoSteps(videoModel, turboOption.steps)
    } else if (videoSteps === turboOption.steps && defaultVideoSteps != null) {
      setVideoSteps(videoModel, defaultVideoSteps)
    }
  }

  const upsamplingOptions = [
    { value: '', label: t('chat.off') },
    { value: 'lanczos1.5', label: 'Lanczos 1.5×' }, // i18n-ok: Lanczos
    { value: 'lanczos2', label: 'Lanczos 2×' }, // i18n-ok: Lanczos
  ]
  const shotLimitTime = formatSeconds((safeShotFrames ?? 0) / ((activeDirectorVideoOptions?.fps || 24)))

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-2.5 py-1.5 text-[11px] text-text-secondary hover:bg-bg-hover transition-colors"
      >
        <span>{t('chat.advanced')}</span>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && (
        <div className="px-2.5 pb-2.5 space-y-3">
          {shotImageSupport && shotImageSupport !== 'required' && (
            <div className="space-y-1 pt-1">
              <label htmlFor={fieldIds('f0')} className="text-[11px] text-text-secondary block">{t('chat.shotImageGuidance')}</label>
              <select aria-label={t('chat.shotImageGuidance')} id={fieldIds('f0')}
                value={shotImageGuidance}
                onChange={e => setShotImageGuidance(e.target.value as DirectorShotImageGuidance)}
                className="w-full bg-bg-tertiary border border-border rounded-lg px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
              >
                <option value="auto">{t('chat.autoRecommended')}</option>
                <option value="prompt_only">
                  {shotImageSupport === 'direct_references' ? t('chat.directReferencesOnly') : t('chat.promptOnly')}
                </option>
                <option value="generate">{t('chat.generateShotImages')}</option>
              </select>
              <p className="text-[10px] text-text-muted">
                {shotGuidanceHint(shotImageSupport, shotImageGuidance, hasVisualReferences, generateShotImages)}
              </p>
            </div>
          )}
          {/* IMAGE section */}
          {generateShotImages && <div className="space-y-2">
            <div className="text-[10px] text-text-muted uppercase tracking-wider">{t('modelPicker.image')}</div>

            <div>
              <label htmlFor={fieldIds('f1')} className="text-[11px] text-text-secondary block mb-1">{t('chat.upsampling')}</label>
              <select aria-label={t('chat.upsampling')} id={fieldIds('f1')}
                value={imgUpsampling}
                onChange={e => setImgUpsampling(e.target.value)}
                className="w-full bg-bg-tertiary border border-border rounded-lg px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
              >
                {upsamplingOptions.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <p className="text-[10px] text-text-muted mt-0.5">
                {t('chat.upscaleImage')}
              </p>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label htmlFor={fieldIds('f2')} className="text-[11px] text-text-secondary">{t('chat.filmGrain')}</label>
                <span className="text-[10px] text-text-muted tabular-nums">{imgGrain.toFixed(2)}</span>
              </div>
              <input aria-label={t('chat.filmGrain')} id={fieldIds('f2')}
                type="range" min={0} max={1} step={0.01} value={imgGrain}
                onChange={e => setImgGrain(parseFloat(e.target.value))}
                className="w-full"
              />
              <p className="text-[10px] text-text-muted mt-0.5">
                {t('chat.filmGrainHint')}
              </p>
              {imgGrain > 0 && (
                <div className="mt-1.5">
                  <div className="flex items-center justify-between mb-1">
                    <label htmlFor={fieldIds('f3')} className="text-[10px] text-text-muted">{t('chat.grainSaturation')}</label>
                    <span className="text-[10px] text-text-muted tabular-nums">{imgGrainSat.toFixed(2)}</span>
                  </div>
                  <input aria-label={t('chat.grainSaturation')} id={fieldIds('f3')}
                    type="range" min={0} max={1} step={0.01} value={imgGrainSat}
                    onChange={e => setImgGrainSat(parseFloat(e.target.value))}
                    className="w-full"
                  />
                </div>
              )}
            </div>
          </div>}

          {/* VIDEO section */}
          <div className="space-y-2 pt-1 border-t border-border">
            <div className="text-[10px] text-text-muted uppercase tracking-wider pt-2">{t('modelPicker.video')}</div>

            {turboOption && (
              <div className={`rounded-lg border px-2.5 py-2 ${
                turboSelected
                  ? 'border-accent-blue/50 bg-accent-blue/10'
                  : 'border-border bg-bg-tertiary/50'
              }`}>
                <label className="flex cursor-pointer items-center gap-2">
                  <input aria-label={'H3 Turbo'}
                    type="checkbox"
                    checked={turboSelected}
                    onChange={event => setDirectorTurbo(event.target.checked)}
                    className="accent-accent-blue"
                  />
                  <Zap size={12} className={turboSelected ? 'text-accent-blue' : 'text-text-muted'} />
                  <span className="text-[11px] font-medium text-text-primary">{'H3 Turbo' // i18n-ok: H3
                  }</span>
                  <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[8px] font-medium uppercase tracking-wider text-indicator-warning">
                    {t('chat.experimental')}
                  </span>
                  <InfoTooltip label={t('chat.aboutH3Turbo')} text={turboOption.guide} />
                </label>
                <p className="mt-1 text-[10px] text-text-muted">
                  {t('chat.turboEnables', { weight: turboOption.weight.toFixed(2), steps: turboOption.steps })}
                </p>
              </div>
            )}

            <div title={t('chat.turboApplies')}>
              <div className="flex items-center justify-between mb-1">
                <label htmlFor={fieldIds('f4')} className="text-[11px] text-text-secondary">{t('chat.inferenceSteps')}</label>
                <div className="flex items-center gap-1.5">
                  {!videoStepsLocked && !turboSelected && defaultVideoSteps != null && configuredVideoSteps != null
                    && configuredVideoSteps !== defaultVideoSteps && (
                    <button
                      type="button"
                      onClick={() => setVideoSteps(videoModel, defaultVideoSteps)}
                      className="text-[9px] text-accent-blue hover:text-accent-blue/80"
                    >
                      {t('chat.default')}
                    </button>
                  )}
                  <input aria-label={t('chat.inferenceSteps')} id={fieldIds('f4')}
                    type="number"
                    min={1}
                    max={50}
                    step={1}
                    value={videoSteps ?? ''}
                    disabled={videoSteps == null || videoStepsLocked || turboSelected}
                    title={firstControlReason([
                      [videoSteps == null, 'disabled.actionInProgress'],
                      [videoStepsLocked, 'disabled.unlockLayer'],
                      [turboSelected, 'disabled.unlockLayer'],
                    ])}
                    onChange={e => {
                      const value = Number(e.target.value)
                      if (Number.isFinite(value)) setVideoSteps(videoModel, value)
                    }}
                    className="w-14 bg-bg-tertiary border border-border rounded px-1.5 py-0.5 text-[11px] text-text-primary text-center focus:outline-none focus:border-accent-blue disabled:opacity-50"
                  />
                </div>
              </div>
              <input
                aria-label={t('chat.inferenceSteps')}
                type="range"
                min={1}
                max={50}
                step={1}
                value={videoSteps ?? 1}
                disabled={videoSteps == null || videoStepsLocked || turboSelected}
                title={firstControlReason([
                  [videoSteps == null, 'disabled.actionInProgress'],
                  [videoStepsLocked, 'disabled.unlockLayer'],
                  [turboSelected, 'disabled.unlockLayer'],
                ])}
                onChange={e => setVideoSteps(videoModel, Number(e.target.value))}
                className="w-full disabled:opacity-50"
              />
              <p className="text-[10px] text-text-muted mt-0.5">
                {videoStepsHint(turboSelected, turboOption?.steps, videoStepsLocked, videoSteps, defaultVideoSteps)}
              </p>
            </div>

            {(activeDirectorVideoOptions?.director_memory_policy
              || activeDirectorVideoOptions?.sliding_window_memory_policy)
              && nativeShotChoices.length > 0 && (
              <div>
                <div className="flex items-center justify-between gap-2 mb-1">
                  <label htmlFor={fieldIds('f5')} className="text-[11px] text-text-secondary">{t('chat.maxPlannedShot')}</label>
                  <select aria-label={t('chat.maxPlannedShot')} id={fieldIds('f5')}
                    value={manualMaxShotFrames ?? ''}
                    onChange={event => setMaxShotFrames(
                      videoModel,
                      event.target.value ? Number(event.target.value) : null,
                    )}
                    className="bg-bg-tertiary border border-border rounded px-1.5 py-0.5 text-[11px] text-text-primary focus:outline-none focus:border-accent-blue"
                  >
                    <option value="">{t('chat.auto')}</option>
                    {nativeShotChoices.map(frames => (
                      <option key={frames} value={frames}>
                        {formatSeconds(frames / (activeDirectorVideoOptions.fps || 24))}
                      </option>
                    ))}
                  </select>
                </div>
                <p className={`text-[10px] ${
                  manualMaxShotFrames != null
                  && safeShotFrames != null
                  && manualMaxShotFrames > safeShotFrames
                    ? 'text-amber-400'
                    : 'text-text-muted'
                }`}>
                  {maxShotHint(manualMaxShotFrames, safeShotFrames, shotLimitTime, resolvedVideoResolution, totalVramGb.toFixed(0))}
                </p>
              </div>
            )}

            <div>
              <label htmlFor={fieldIds('f6')} className="text-[11px] text-text-secondary block mb-1">{t('chat.upsampling')}</label>
              <select aria-label={t('chat.upsampling')} id={fieldIds('f6')}
                value={vidUpsampling}
                onChange={e => setVidUpsampling(e.target.value)}
                className="w-full bg-bg-tertiary border border-border rounded-lg px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
              >
                {upsamplingOptions.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <p className="text-[10px] text-text-muted mt-0.5">
                {t('chat.upscaleVideo')}
              </p>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label htmlFor={fieldIds('f7')} className="text-[11px] text-text-secondary">{t('chat.filmGrain')}</label>
                <span className="text-[10px] text-text-muted tabular-nums">{vidGrain.toFixed(2)}</span>
              </div>
              <input aria-label={t('chat.filmGrain')} id={fieldIds('f7')}
                type="range" min={0} max={1} step={0.01} value={vidGrain}
                onChange={e => setVidGrain(parseFloat(e.target.value))}
                className="w-full"
              />
              <p className="text-[10px] text-text-muted mt-0.5">
                {t('chat.filmGrainHint')}
              </p>
              {vidGrain > 0 && (
                <div className="mt-1.5">
                  <div className="flex items-center justify-between mb-1">
                    <label htmlFor={fieldIds('f8')} className="text-[10px] text-text-muted">{t('chat.grainSaturation')}</label>
                    <span className="text-[10px] text-text-muted tabular-nums">{vidGrainSat.toFixed(2)}</span>
                  </div>
                  <input aria-label={t('chat.grainSaturation')} id={fieldIds('f8')}
                    type="range" min={0} max={1} step={0.01} value={vidGrainSat}
                    onChange={e => setVidGrainSat(parseFloat(e.target.value))}
                    className="w-full"
                  />
                </div>
              )}
            </div>

            {activeDirectorVideoOptions?.self_refiner === true && <div>
              <div className="flex items-center justify-between mb-1">
                <label htmlFor={fieldIds('f9')} className="text-[11px] text-text-secondary">{t('chat.selfRefiner')}</label>
                <span className="text-[9px] uppercase tracking-wider text-text-muted bg-bg-tertiary border border-border rounded px-1 py-px">
                  {t('chat.experimental')}
                </span>
              </div>
              <select aria-label={t('chat.selfRefiner')} id={fieldIds('f9')}
                value={vidSelfRefiner}
                onChange={e => setVidSelfRefiner(Number(e.target.value))}
                className="w-full bg-bg-tertiary border border-border rounded-lg px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
              >
                <option value={0}>{t('chat.off')}</option>
                <option value={1}>{'P1-Norm' // i18n-ok: P1-Norm
                }</option>
                <option value={2}>{'P2-Norm' // i18n-ok: P2-Norm
                }</option>
              </select>
              <p className="text-[10px] text-text-muted mt-0.5">
                {t('chat.selfRefinerHint')}
              </p>
            </div>}
          </div>
        </div>
      )}
    </div>
  )
}

/** Compact model picker for Director. Director's automated stages have a
 *  stricter input contract than Studio, so the backend publishes explicit
 *  per-workflow compatibility metadata for this selector to enforce. */

function DirectorLoraAccordion() {
  // Resolve Director's per-shoot image and video models from saved
  // per-mode selections, falling back to the same Director defaults
  // the pipeline submission uses (useStore.ts:5574). The previous
  // fallback to `s.params.model_type` was wrong — that field carries
  // the CURRENTLY-ACTIVE Studio model, which on fresh launch is
  // whatever Studio happens to be in (usually video). On a fresh
  // launch, that meant Director's "Image LoRAs" accordion would
  // fetch the video model's LoRA dir and display LTX loras under
  // the image header. Falling back to a known image-class default
  // (flux2_klein_9b) instead of the active Studio model fixes that.
  const imageModel = useStore(s => s.selectedModelPerMode.image || 'flux2_klein_9b')
  const videoModel = useStore(s => s.selectedModelPerMode.video || 'ltx2_22B_distilled_1_1')
  const shotImageSupport = useStore(s => s.models.find(
    model => model.model_type === videoModel,
  )?.director?.shot_image_support)
  const shotImageGuidance = useStore(s => s.directorShotImageGuidance)
  const hasVisualReferences = useStore(s => Boolean(
    s.directorReferenceImage
    || s.directorReferenceImagePath
    || s.directorCharacterRefs.length
    || s.directorCharacterRefPaths.length
    || s.directorLocationRefs.length
    || s.directorLocationRefPaths.length
  ))
  const generateShotImages = directorWillGenerateShotImages(
    shotImageSupport,
    shotImageGuidance,
    hasVisualReferences,
  )
  const selectDirectorImageModel = useStore(s => s.selectDirectorImageModel)
  const selectDirectorVideoModel = useStore(s => s.selectDirectorVideoModel)
  const minimaxImageReady = useStore(s => Boolean(s.servicesConfig?.minimax_api_key_set))
  const [imageOpen, setImageOpen] = useState(false)
  const [videoOpen, setVideoOpen] = useState(false)
  const { t } = useUiTranslation('director')

  return (
    <div className="space-y-1">
      {/* Models the pipeline will use — visible + changeable here so the
          user can verify before starting; LoRA lists below follow. */}
      <div className="space-y-1 mb-1.5">
        {generateShotImages && (
          <>
            <DirectorModelPicker mode="image" value={imageModel} onChange={selectDirectorImageModel} />
            {imageModel === MINIMAX_IMAGE_API_MODEL && (
              <p className={`pl-[50px] text-[9px] leading-relaxed ${minimaxImageReady ? 'text-emerald-400' : 'text-amber-300'}`}>
                {minimaxImageReady
                  ? t('chat.imageApiReady')
                  : t('chat.imageApiKey')}
              </p>
            )}
          </>
        )}
        <DirectorModelPicker mode="video" value={videoModel} onChange={selectDirectorVideoModel} />
      </div>
      {/* Image LoRAs */}
      {generateShotImages && imageModel && imageModel !== MINIMAX_IMAGE_API_MODEL && (
        <div className="border border-border rounded-lg overflow-hidden">
          <button
            onClick={() => setImageOpen(!imageOpen)}
            className="w-full flex items-center justify-between px-2.5 py-1.5 text-[11px] text-text-secondary hover:bg-bg-hover transition-colors"
          >
            <span>{t('chat.imageLoras')}</span>
            {imageOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
          {imageOpen && (
            <div className="px-2.5 pb-2">
              <DirectorLoraSelector mode="image" modelType={imageModel} />
            </div>
          )}
        </div>
      )}
      {/* Video LoRAs */}
      {videoModel && (
        <div className="border border-border rounded-lg overflow-hidden">
          <button
            onClick={() => setVideoOpen(!videoOpen)}
            className="w-full flex items-center justify-between px-2.5 py-1.5 text-[11px] text-text-secondary hover:bg-bg-hover transition-colors"
          >
            <span>{t('chat.videoLoras')}</span>
            {videoOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
          {videoOpen && (
            <div className="px-2.5 pb-2">
              <DirectorLoraSelector mode="video" modelType={videoModel} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StyleForm({
  speakers, speakerMappings, speakerSamples, setSpeakerMapping, insertSpeakerMention, isActive, isShortFilm, isStoryPath,
}: {
  speakers: string[]
  speakerMappings: ReturnType<typeof useStore.getState>['directorSpeakerMappings']
  speakerSamples: Record<string, string[]>
  setSpeakerMapping: (speakerId: string, name: string, role: 'rapping' | 'singing' | 'speaking' | '') => void
  insertSpeakerMention: (speakerId: string) => void
  isActive: boolean
  isShortFilm?: boolean
  isStoryPath?: boolean
}) {
  const { t } = useUiTranslation('director')
  if (!isActive) {
    return (
      <div className="space-y-2">
        <p className="text-xs text-text-muted">
          {isStoryPath ? t('chat.storySubmitted')
            : isShortFilm ? t('chat.storyDescriptionSubmitted')
            : t('chat.sceneSubmitted')}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-text-secondary">
        {isStoryPath
          ? t('chat.describeStoryLong')
          : isShortFilm
            ? t('chat.describeShortFilmStyle')
            : t('chat.describeSceneStyle')}
      </p>

      {/* Speaker Mapping — hidden for story path (no audio = no detected speakers) */}
      {!isStoryPath && speakers.length >= 1 && (
        <div>
          <label className="text-[11px] text-text-muted uppercase tracking-wider block mb-1">{t('panel.speakersDetected')}</label>
          <div className="space-y-2">
            {speakerMappings.map((mapping) => (
              <div key={mapping.speakerId} className="bg-bg-tertiary rounded-lg p-2 space-y-1">
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => insertSpeakerMention(mapping.speakerId)}
                    className="text-[10px] px-1.5 py-0.5 rounded-full bg-accent-blue/20 text-accent-blue hover:bg-accent-blue/30 shrink-0 transition-colors"
                    title={t('panel.insertSpeaker', { id: mapping.speakerId })}
                  >
                    {mapping.speakerId}
                  </button>
                  <input aria-label={t('panel.speakerPlaceholder')}
                    type="text"
                    value={mapping.name}
                    onChange={e => setSpeakerMapping(mapping.speakerId, e.target.value, mapping.role)}
                    placeholder={t('panel.speakerPlaceholder')}
                    className="flex-1 bg-bg-secondary border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue transition-colors"
                  />
                  <select
                    aria-label={t('panel.role')}
                    value={mapping.role}
                    onChange={e => setSpeakerMapping(mapping.speakerId, mapping.name, e.target.value as typeof mapping.role)}
                    className="bg-bg-secondary border border-border rounded px-1.5 py-1 text-[10px] text-text-secondary focus:outline-none focus:border-accent-blue transition-colors"
                  >
                    <option value="">{t('panel.role')}</option>
                    {!isShortFilm && <option value="rapping">{t('panel.rapping')}</option>}
                    {!isShortFilm && <option value="singing">{t('panel.singing')}</option>}
                    <option value="speaking">{t('panel.speaking')}</option>
                  </select>
                </div>
                {speakerSamples[mapping.speakerId] && (
                  <div className="text-[9px] text-text-muted pl-1 italic">
                    {speakerSamples[mapping.speakerId].map((line, li) => (
                      <div key={li} className="truncate">&ldquo;{line}&rdquo;</div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
          <span className="text-[10px] text-text-muted mt-1 block">
            {t('panel.speakersHint')}
          </span>
        </div>
      )}

      {/* LoRA + advanced post-processing. Short Film shows them here at the
          scene-description step; Music Video surfaces them at the first setup
          step instead (so all up-front choices live together). */}
      {isShortFilm && (
        <>
          <DirectorLoraAccordion />
          <DirectorAdvancedAccordion />
        </>
      )}

      <p className="text-[11px] text-text-muted">
        {isStoryPath
          ? t('chat.sendStory')
          : isShortFilm
            ? t('chat.sendStoryDescription')
            : t('chat.sendSceneDescription')}
      </p>
    </div>
  )
}

function ImagePromptsReview({
  clipPlans, plannedClips, speakerMappings, editClipPlan, planPrompts,
  generateStartImages, loading, isActive, isShortFilm,
}: {
  clipPlans: ReturnType<typeof useStore.getState>['directorClipPlans']
  plannedClips: ReturnType<typeof useStore.getState>['directorPlannedClips']
  speakerMappings: ReturnType<typeof useStore.getState>['directorSpeakerMappings']
  editClipPlan: (index: number, field: 'video_prompt' | 'image_prompt', value: string) => void
  planPrompts: () => Promise<void>
  generateStartImages: () => Promise<void>
  loading: boolean
  isActive: boolean
  isShortFilm?: boolean
}) {
  const { t } = useUiTranslation('director')
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('panel.startImagePrompts')}</label>
        {isActive && (
          <button
            onClick={planPrompts}
            disabled={loading}
            title={controlReason(loading, 'disabled.actionInProgress')}
            className="text-[10px] text-accent-blue hover:text-accent-blue-hover flex items-center gap-0.5"
          >
            <RotateCcw size={10} /> {t('panel.regenerate')}
          </button>
        )}
      </div>

      {/* No inner scroll — the chat panel handles scrolling. The list
          extends to the natural total height of all clip cards. */}
      <div className="space-y-2">
        {clipPlans.map((plan, i) => {
          const clip = plannedClips[i]
          return (
            <div key={i} className="bg-bg-tertiary rounded-lg p-2 space-y-1.5">
              <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
                <span className="font-medium text-text-secondary">{isShortFilm ? t('dashboard.shot', { n: i + 1 }) : t('panel.clipN', { n: i + 1 })}</span>
                {clip && (
                  <>
                    <span>{formatTime(clip.start)}-{formatTime(clip.end)}</span>
                    {!isShortFilm && <span>{t('panel.beatsShort', { count: clip.beat_count })}</span>}
                    <SectionBadge label={clip.section_label} />
                    {!isShortFilm && <EnergyDot energy={clip.energy} />}
                    {clip.dominant_speaker && (
                      <span className="text-accent-blue">
                        {speakerMappings.find(m => m.speakerId === clip.dominant_speaker)?.name || clip.dominant_speaker}
                      </span>
                    )}
                  </>
                )}
              </div>
              {/* AutoResizeTextarea grows with content — no internal
                  scroll on long prompts. rows={4} provides a sensible
                  initial height before content is loaded. */}
              <AutoResizeTextarea
                aria-label={t('dashboard.imagePrompt')}
                value={plan.image_prompt}
                onChange={e => editClipPlan(i, 'image_prompt', e.target.value)}
                rows={4}
                disabled={!isActive}
                title={controlReason(!isActive, 'disabled.sendNeedsStep')}
                className="w-full bg-bg-secondary border border-border rounded px-2 py-1.5 text-xs text-text-primary resize-none focus:outline-none focus:border-accent-blue transition-colors disabled:opacity-60"
              />
            </div>
          )
        })}
      </div>

      {isActive && (
        <button
          onClick={generateStartImages}
          disabled={loading}
          title={controlReason(loading, 'disabled.actionInProgress')}
          className="w-full py-2 rounded-lg bg-accent-blue text-white text-xs font-medium hover:bg-accent-blue-hover transition-colors flex items-center justify-center gap-1.5"
        >
          {/* Always available now — directorGenerateStartImages generates an
              establishing/anchor image first when no reference was provided. */}
          <ImageIcon size={12} /> {t('panel.generateStartImages')}
        </button>
      )}
    </div>
  )
}

function ImageGenView({
  loading, imageGenProgress, clipImages,
}: {
  loading: boolean
  imageGenProgress: ReturnType<typeof useStore.getState>['directorImageGenProgress']
  clipImages: ReturnType<typeof useStore.getState>['directorClipImages']
}) {
  const { t } = useUiTranslation('director')
  // Architecture-mismatch advisories from the backend's image-gen filter.
  // Surfacing these in chat (vs only in the console) lets the user see
  // immediately why some of their selected LoRAs didn't get applied —
  // most commonly a Flux 2 Dev–trained LoRA that won't load against
  // Klein 9B's narrower hidden dim.
  const loraWarnings = useStore(s => s.pipelineStatus?.lora_warnings) || []
  return (
    <div className="space-y-3">
      <label className="text-[11px] text-text-muted uppercase tracking-wider block">{t('panel.generatingStartImages')}</label>

      {loraWarnings.length > 0 && (
        <div className="space-y-1.5">
          {loraWarnings.map((w, i) => (
            <div key={i} className="px-2.5 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-[11px] text-text-primary leading-snug whitespace-pre-line">
              {w}
            </div>
          ))}
        </div>
      )}


      {imageGenProgress && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-text-secondary">
              {imageGenProgress.status === 'done'
                ? t('panel.allImagesReady')
                : t('panel.clipOf', { current: imageGenProgress.current + 1, total: imageGenProgress.total })}
            </span>
            <span className="text-text-muted">
              {imageGenStatusLine(imageGenProgress.currentClipLabel, imageGenProgress.status)}
            </span>
          </div>
          <div className="w-full bg-bg-tertiary rounded-full h-1.5">
            <div
              className="bg-accent-blue h-1.5 rounded-full transition-all"
              style={{
                width: `${imageGenProgress.status === 'done'
                  ? 100
                  : ((imageGenProgress.current + (imageGenProgress.status === 'polling' ? 0.5 : 0)) / imageGenProgress.total) * 100
                }%`,
              }}
            />
          </div>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center gap-2 py-2">
          <Loader2 size={16} className="animate-spin text-accent-blue" />
          <span className="text-[11px] text-text-muted">
            {imageSpinnerLabel(imageGenProgress?.status)}
          </span>
        </div>
      )}

      {clipImages.length > 0 && (
        // No inner scroll — chat panel scrolls. Grid wraps naturally
        // and extends downward as more images come in.
        <div className="grid grid-cols-3 gap-1.5">
          {clipImages.map((img, i) => (
            <div key={i} className="relative">
              <DirectorClipImagePreview
                image={img}
                alt={t('panel.clipN', { n: img.clipIndex + 1 })}
                className="w-full aspect-square object-cover rounded-lg border border-border"
              />
              <span className="absolute bottom-0.5 left-0.5 text-[8px] bg-black/60 text-white px-1 py-0.5 rounded">
                {img.clipIndex + 1}
              </span>
            </div>
          ))}
        </div>
      )}

      {!loading && imageGenProgress?.status === 'error' && (
        <button
          onClick={() => { useStore.setState({ directorStep: 'review_video' }) }}
          className="w-full py-2 rounded-lg bg-accent-blue text-white text-xs font-medium hover:bg-accent-blue-hover transition-colors flex items-center justify-center gap-1.5"
        >
          <ChevronRight size={12} /> {t('chat.continueToVideo')}
        </button>
      )}
    </div>
  )
}

function VideoPromptsReview({
  clipPlans, plannedClips, clipImages, speakerMappings, editClipPlan,
  planVideoPrompts, directorGenerate, applyToClips, loading, isShortFilm,
  isGenerating, isAutoGenerating, generationError,
}: {
  clipPlans: ReturnType<typeof useStore.getState>['directorClipPlans']
  plannedClips: ReturnType<typeof useStore.getState>['directorPlannedClips']
  clipImages: ReturnType<typeof useStore.getState>['directorClipImages']
  speakerMappings: ReturnType<typeof useStore.getState>['directorSpeakerMappings']
  editClipPlan: (index: number, field: 'video_prompt' | 'image_prompt', value: string) => void
  planVideoPrompts: () => Promise<void>
  directorGenerate: () => void
  applyToClips: () => void
  loading: boolean
  isShortFilm?: boolean
  /** True when ANY generation job is currently running. The Generate
   *  button needs this so it can show a disabled "Generating..."
   *  state instead of looking pressable — important in auto mode
   *  where the system auto-triggers Generate after planning, and as
   *  a double-click guard in manual mode. */
  isGenerating?: boolean
  /** True specifically when auto-mode pipeline is the thing running.
   *  Used only to swap the button label to "Auto Generating..." so
   *  the user knows the system is driving itself, not waiting on
   *  them to click. */
  isAutoGenerating?: boolean
  /** Terminal generation failure shown in place, immediately below the
   *  status control that previously said "Auto Generating...". */
  generationError?: string | null
}) {
  const { t } = useUiTranslation('director')
  const directVideo = useStore(s => s.directorMusicVideoTreatment.generation_mode === 'direct_video')
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('panel.videoPrompts')}</label>
        <button
          onClick={planVideoPrompts}
          disabled={loading}
          title={controlReason(loading, 'disabled.actionInProgress')}
          className="text-[10px] text-accent-blue hover:text-accent-blue-hover flex items-center gap-0.5"
        >
          <RotateCcw size={10} /> {t('panel.regenerate')}
        </button>
      </div>

      {directVideo && (
        <div className="rounded-md border border-fuchsia-500/30 bg-fuchsia-500/10 px-2 py-1.5 text-[9px] leading-relaxed text-fuchsia-100">
          {t('directVideo.promptNote')}
        </div>
      )}

      {clipImages.length > 0 && (
        <div className="grid grid-cols-5 gap-1 mb-1">
          {clipImages.map((img, i) => (
            <div key={i} className="relative">
              <DirectorClipImagePreview
                image={img}
                alt={t('panel.clipN', { n: img.clipIndex + 1 })}
                className="w-full aspect-square object-cover rounded border border-border"
              />
              <span className="absolute bottom-0 left-0 text-[7px] bg-black/60 text-white px-0.5 rounded-br">
                {img.clipIndex + 1}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* No inner scroll — chat panel handles it. AutoResizeTextarea
          grows each prompt to its full height so long video prompts
          don't double-scroll. */}
      <div className="space-y-2">
        {clipPlans.map((plan, i) => {
          const clip = plannedClips[i]
          return (
            <div key={i} className="bg-bg-tertiary rounded-lg p-2 space-y-1.5">
              <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
                <span className="font-medium text-text-secondary">{isShortFilm ? t('dashboard.shot', { n: i + 1 }) : t('panel.clipN', { n: i + 1 })}</span>
                {clip && (
                  <>
                    <span>{formatTime(clip.start)}-{formatTime(clip.end)}</span>
                    <SectionBadge label={clip.section_label} />
                    {clip.dominant_speaker && (
                      <span className="text-accent-blue">
                        {speakerMappings.find(m => m.speakerId === clip.dominant_speaker)?.name || clip.dominant_speaker}
                      </span>
                    )}
                  </>
                )}
              </div>
              <AutoResizeTextarea
                aria-label={t('dashboard.videoPrompt')}
                value={plan.video_prompt}
                onChange={e => editClipPlan(i, 'video_prompt', e.target.value)}
                rows={4}
                className="w-full bg-bg-secondary border border-border rounded px-2 py-1.5 text-xs text-text-primary resize-none focus:outline-none focus:border-accent-blue transition-colors"
              />
            </div>
          )
        })}
      </div>

      <div className="space-y-2">
        {/* Generate button has two render modes:
            - Idle (no jobs running): bright green CTA, click triggers
              directorGenerate. Applies in manual mode where the user
              actively kicks off generation from this review screen.
            - Generating (any job in flight): muted disabled state with
              spinner + "Generating..." label. Applies in BOTH:
                * Auto mode, where directorGenerate auto-triggers right
                  after the chat reaches review_video — without this
                  guard, the button looked pressable while generation
                  was already running, confusing the user.
                * Manual mode after the user clicked Generate — guards
                  against double-submission. */}
        {generationError ? (
          <div className="space-y-2">
            <button
              disabled
              title={controlLabel('status.failed')}
              className="w-full py-2.5 rounded-lg bg-red-500/10 border border-red-500/40 text-red-300 text-sm font-semibold flex items-center justify-center gap-1.5 cursor-not-allowed"
            >
              <X size={14} /> {t('chat.error')}
            </button>
            <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-2 text-[11px] leading-snug text-red-200">
              {generationError}
            </div>
          </div>
        ) : isGenerating ? (
          // Muted disabled state. opacity-60 dims the whole control
          // (including the spinner) so it reads as "not interactive"
          // even against the bright accent backgrounds Golden Hour and
          // similar themes use. Border is dropped to a subtler tone so
          // it doesn't compete with the active CTA color elsewhere on
          // screen. Label switches to "Auto Generating…" when the
          // system is driving the pipeline by itself, so the user
          // understands they're not waiting on a click.
          <button
            disabled
            title={controlReason(true, 'disabled.actionInProgress')}
            className="w-full py-2.5 rounded-lg bg-bg-tertiary border border-border/40 text-text-muted text-sm font-medium flex items-center justify-center gap-1.5 cursor-not-allowed opacity-60"
          >
            <Loader2 size={14} className="animate-spin" />
            {isAutoGenerating ? t('chat.autoGenerating') : t('chat.generatingNow')}
          </button>
        ) : (
          <button
            onClick={directorGenerate}
            className="w-full py-2.5 rounded-lg bg-accent-green hover:bg-accent-green-hover text-white text-sm font-semibold transition-colors flex items-center justify-center gap-1.5"
          >
            <Play size={14} fill="white" /> {t('chat.generate')}
          </button>
        )}
        <button
          onClick={applyToClips}
          className="w-full py-2 rounded-lg border border-border text-text-secondary text-xs font-medium hover:bg-bg-hover hover:text-text-primary transition-colors flex items-center justify-center gap-1.5"
        >
          <ChevronRight size={12} /> {t('panel.editInStudio')}
        </button>
      </div>
    </div>
  )
}
