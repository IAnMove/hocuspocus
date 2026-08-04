import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle, ArrowDown, ArrowUp, Check, CheckCircle2, Clapperboard, Eye, Film,
  ImagePlus, ListVideo, Loader2, Play, Plus, Settings2, ShieldCheck, Sparkles, Trash2, Upload,
} from 'lucide-react'
import * as api from '../../api/client'
import { DirectorLoraSelector } from '../../components/SettingsDrawer/DirectorLoraSelector'
import { useStore } from '../../stores/useStore'
import type { PlannedClip } from '../../types'
import { forEachComicPanelCapture } from './export'
import {
  comicId, mergeComicVideoOverrideFields, normalizeComicPlan, simplifyDirectorText,
} from './model'
import { useComicStore } from './store'
import type {
  ComicAsset, ComicCharacter, ComicDirectorRequest, ComicGlossaryEntry, ComicPlanPanel,
  ComicVideoOverrideField,
} from './types'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
const input = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue'
type ComicMovieQuality = '480p' | '540p' | '720p' | '1080p'
type ComicMovieAspect = 'landscape' | 'portrait' | 'square'

type ComicMovieResolution = {
  quality: ComicMovieQuality
  value: string
  label: string
  recommended?: boolean
}

const comicMovieResolutions = (
  modelId: string,
  aspect: ComicMovieAspect,
): ComicMovieResolution[] => {
  if (modelId === 'minimax_h3') {
    if (aspect === 'square') {
      return [
        { quality: '480p', value: '640x640', label: '≈480p · 640×640' },
        { quality: '540p', value: '736x736', label: '≈540p · 736×736', recommended: true },
        { quality: '720p', value: '992x992', label: '≈720p · 992×992 · high' },
      ]
    }
    const portrait = aspect === 'portrait'
    return [
      { quality: '480p', value: portrait ? '448x832' : '832x448', label: `≈480p · ${portrait ? '448×832' : '832×448'}` },
      { quality: '540p', value: portrait ? '544x960' : '960x544', label: `≈540p · ${portrait ? '544×960' : '960×544'} · recommended`, recommended: true },
      { quality: '720p', value: portrait ? '704x1280' : '1280x704', label: `≈720p · ${portrait ? '704×1280' : '1280×704'} · high` },
    ]
  }
  return [
    {
      quality: '480p',
      value: aspect === 'portrait' ? '448x832' : aspect === 'square' ? '640x640' : '832x448',
      label: `≈480p · ${aspect === 'portrait' ? '448×832' : aspect === 'square' ? '640×640' : '832×448'} · test`,
    },
    {
      quality: '720p',
      value: aspect === 'portrait' ? '704x1280' : aspect === 'square' ? '1024x1024' : '1280x704',
      label: `≈720p · ${aspect === 'portrait' ? '704×1280' : aspect === 'square' ? '1024×1024' : '1280×704'} · recommended`,
      recommended: true,
    },
    {
      quality: '1080p',
      value: aspect === 'portrait' ? '1088x1920' : aspect === 'square' ? '1408x1408' : '1920x1088',
      label: `≈1080p · ${aspect === 'portrait' ? '1088×1920' : aspect === 'square' ? '1408×1408' : '1920×1088'} · heavy`,
    },
  ]
}

const motionLevelLabel = (level: number) => (
  level <= 0
    ? '0 · exact hold'
    : level === 1
      ? '1 · ambient, locked camera'
      : level === 2
        ? '2 · restrained performance'
        : '3 · authored action'
)

const motionMethodLabel = (renderer?: string) => (
  renderer === 'hold'
    ? 'Exact still'
    : renderer === 'parallax'
      ? 'Deterministic push'
      : renderer === 'cinemagraph'
        ? 'AI living still'
        : renderer === 'ltx'
          ? 'Model-driven I2V'
          : 'Automatic'
)

const VIDEO_OVERRIDE_BY_PROPERTY: Partial<Record<keyof ComicPlanPanel, ComicVideoOverrideField>> = {
  videoIncluded: 'included',
  videoOrder: 'order',
  videoAction: 'action',
  videoRenderer: 'renderer',
  videoFit: 'fit',
  videoMotion: 'motion_mode',
  videoMotionLevel: 'motion_level',
  durationSeconds: 'duration',
  cameraMove: 'camera',
  videoPrompt: 'video_prompt',
  videoSeed: 'seed',
  videoEndFrame: 'end_frame',
  videoTestSelected: 'test_selected',
}

function overrideChangesForPatch(patch: Partial<ComicPlanPanel>): {
  add: ComicVideoOverrideField[]
  remove: ComicVideoOverrideField[]
} {
  const add: ComicVideoOverrideField[] = []
  const remove: ComicVideoOverrideField[] = []
  Object.entries(patch).forEach(([property, value]) => {
    const field = VIDEO_OVERRIDE_BY_PROPERTY[property as keyof ComicPlanPanel]
    if (!field) return
    const followsAutomatic = value === undefined
      || (property === 'videoMotion' && value === 'auto')
      || (property === 'videoEndFrame' && value === 'auto')
    ;(followsAutomatic ? remove : add).push(field)
  })
  return { add, remove }
}

type SavedComicVideoSettings = {
  aspect?: ComicMovieAspect
  defaultDuration?: number
  targetFilmShots?: number
  quality?: ComicMovieQuality
  motionMode?: 'contextual' | 'living-still' | 'action'
  imageFit?: 'reframe' | 'cover' | 'contain'
  endFrameMode?: 'none' | 'smart' | 'all'
  fidelity?: 'faithful' | 'balanced' | 'expressive'
}

const comicVideoSettingsKey = (workspace: string, comicIdValue: string) =>
  `maestro-comic-video-settings:${workspace}:${comicIdValue}`

const readComicVideoSettings = (
  workspace: string,
  comicIdValue: string,
): SavedComicVideoSettings => {
  try {
    return JSON.parse(
      window.localStorage.getItem(comicVideoSettingsKey(workspace, comicIdValue)) || '{}',
    ) as SavedComicVideoSettings
  } catch {
    return {}
  }
}

export function ComicWritingProviderFields({
  value,
  onChange,
  disabled = false,
}: {
  value: ComicDirectorRequest
  onChange: <K extends keyof ComicDirectorRequest>(key: K, value: ComicDirectorRequest[K]) => void
  disabled?: boolean
}) {
  const services = useStore(state => state.servicesConfig)
  const provider = value.writingProvider || 'maestro'
  const external = provider !== 'maestro'
  const apiKeySet = provider === 'deepseek'
    ? Boolean(services?.deepseek_api_key_set)
    : provider === 'minimax'
      ? Boolean(services?.minimax_api_key_set)
    : provider === 'openai'
      ? Boolean(services?.openai_api_key_set)
      : provider === 'openai-compatible'
        ? Boolean(services?.compatible_api_key_set) || Boolean(services?.compatible_base_url)
        : true
  const selectProvider = (next: ComicDirectorRequest['writingProvider']) => {
    onChange('writingProvider', next)
    if (next === 'deepseek') {
      onChange('writingModel', 'deepseek-v4-pro')
      onChange('writingBaseUrl', 'https://api.deepseek.com')
    } else if (next === 'minimax') {
      onChange('writingModel', 'MiniMax-M3')
      onChange('writingBaseUrl', 'https://api.minimax.io/v1')
    } else if (next === 'openai') {
      onChange('writingModel', 'gpt-4.1')
      onChange('writingBaseUrl', 'https://api.openai.com')
    } else if (next === 'openai-compatible') {
      onChange('writingModel', '')
      onChange('writingBaseUrl', services?.compatible_base_url || '')
    }
  }
  return (
    <div className="space-y-2 rounded-lg border border-border bg-bg-tertiary/30 p-2.5">
      <label className="block text-[10px] text-text-muted">Writing LLM
        <select
          className={`${input} mt-1`}
          disabled={disabled}
          value={value.writingProvider || 'maestro'}
          onChange={event => selectProvider(event.target.value as ComicDirectorRequest['writingProvider'])}
        >
          <option value="maestro">Maestro internal · default</option>
          <option value="deepseek">DeepSeek · only this comic</option>
          <option value="minimax">MiniMax · only this comic</option>
          <option value="openai">OpenAI · only this comic</option>
          <option value="openai-compatible">Custom OpenAI-compatible · only this comic</option>
        </select>
      </label>
      {external && <>
        <label className="block text-[10px] text-text-muted">Model
          {provider === 'deepseek' ? (
            <select className={`${input} mt-1`} disabled={disabled} value={value.writingModel || 'deepseek-v4-pro'} onChange={event => onChange('writingModel', event.target.value)}>
              <option value="deepseek-v4-pro">DeepSeek V4 Pro · best story quality</option>
              <option value="deepseek-v4-flash">DeepSeek V4 Flash · faster and cheaper</option>
            </select>
          ) : provider === 'minimax' ? (
            <select className={`${input} mt-1`} disabled={disabled} value={value.writingModel || 'MiniMax-M3'} onChange={event => onChange('writingModel', event.target.value)}>
              <option value="MiniMax-M3">MiniMax M3 · multimodal, 1M context</option>
              <option value="MiniMax-M2.7">MiniMax M2.7 · character-rich interaction</option>
              <option value="MiniMax-M2.7-highspeed">MiniMax M2.7 Highspeed · lower latency</option>
            </select>
          ) : (
            <input className={`${input} mt-1`} disabled={disabled} value={value.writingModel || ''} onChange={event => onChange('writingModel', event.target.value)} placeholder={provider === 'openai' ? 'gpt-4.1' : 'Model name exposed by your server'} />
          )}
        </label>
        <div className="rounded border border-border px-2 py-1.5 text-[9px] text-text-muted">
          {provider === 'deepseek'
            ? 'https://api.deepseek.com · Translation always uses V4 Flash, even when Pro is selected here.'
            : provider === 'minimax'
              ? 'https://api.minimax.io/v1 · Shares the MiniMax key with image generation, but not its model selection.'
            : provider === 'openai'
              ? 'https://api.openai.com'
              : services?.compatible_base_url || 'Set the custom compatible URL in Settings → Services.'}
        </div>
        <p className={`text-[9px] ${apiKeySet ? 'text-emerald-400' : 'text-amber-300'}`}>
          {apiKeySet
            ? provider === 'openai-compatible' && !services?.compatible_api_key_set
              ? 'Custom endpoint configured without authentication. The internal LLM remains unchanged.'
              : 'Provider credential configured. The internal LLM remains loaded and unchanged.'
            : `Add your ${provider === 'deepseek' ? 'DeepSeek' : provider === 'minimax' ? 'MiniMax' : provider === 'openai' ? 'OpenAI' : 'custom compatible'} credential in Settings → Services.`}
        </p>
      </>}
      {!external && <p className="text-[9px] text-text-muted">Uses Maestro's configured internal LLM. External selection never changes the global provider.</p>}
    </div>
  )
}

function scriptForPanel(panel: ComicPlanPanel): string {
  return [
    ...(panel.captions || []).map(text => `[Caption] ${text}`),
    ...(panel.dialogue || []).map(line => `[${line.speakerId || 'Dialogue'}] ${line.text}`),
    ...(panel.soundEffects || []).map(text => `[SFX] ${text}`),
  ].join('\n')
}

function updateCharacters(characters: ComicCharacter[]) {
  const state = useComicStore.getState()
  const director = state.project.director
  state.patchProject({
    characters,
    ...(director ? {
      director: {
        ...director,
        input: { ...director.input, characters },
        plan: { ...director.plan, characters },
        scriptApprovedAt: undefined,
        scriptVersion: (director.scriptVersion || 1) + 1,
      },
    } : {}),
  })
}

export function ComicCharactersPanel({
  generateReference,
  notify,
}: {
  generateReference: (character: ComicCharacter) => Promise<void>
  notify: (kind: 'ok' | 'error', text: string) => void
}) {
  const project = useComicStore(state => state.project)
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploadTarget, setUploadTarget] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [draft, setDraft] = useState({ name: '', role: '', description: '' })
  const patchCharacter = (id: string, patch: Partial<ComicCharacter>) => {
    updateCharacters(project.characters.map(character => character.id === id
      ? { ...character, ...patch }
      : character))
  }
  const add = () => {
    if (!draft.name.trim()) return
    updateCharacters([...project.characters, {
      id: comicId('character'),
      name: draft.name.trim(),
      role: draft.role.trim(),
      description: draft.description.trim(),
      personality: '',
      motivation: '',
      voice: '',
      wardrobe: '',
      visualNotes: '',
      negativePrompt: '',
      referenceAssetIds: [],
      locked: true,
    }])
    setDraft({ name: '', role: '', description: '' })
  }
  const upload = async (file?: File) => {
    const character = project.characters.find(item => item.id === uploadTarget)
    if (!file || !character) return
    setBusy(character.id)
    try {
      const uploaded = await api.uploadImage(file)
      const asset: ComicAsset = {
        id: comicId('asset'), name: `${character.name} reference`, kind: 'upload',
        source: uploaded.url, thumbnail: uploaded.url, characterIds: [character.id],
        createdAt: new Date().toISOString(),
      }
      useComicStore.getState().addAsset(asset)
      const references = Array.from(new Set([...(character.referenceAssetIds || []), asset.id]))
      patchCharacter(character.id, { referenceAssetId: asset.id, referenceAssetIds: references })
      notify('ok', `Reference added to ${character.name}.`)
    } catch (error) {
      notify('error', (error as Error).message)
    } finally {
      setBusy(null)
      setUploadTarget(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-purple-400/30 bg-purple-400/5 p-3">
        <div className="text-xs font-semibold text-text-primary">Character bible</div>
        <p className="mt-1 text-[10px] text-text-muted">Define personality, voice and stable visual traits. Reference images are reused whenever the character appears.</p>
      </div>
      <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={event => upload(event.target.files?.[0])} />
      {project.characters.map(character => (
        <details key={character.id} open className="rounded-lg border border-border bg-bg-tertiary/30">
          <summary className="cursor-pointer px-2.5 py-2 text-xs font-medium text-text-primary">{character.name}{character.role ? ` · ${character.role}` : ''}</summary>
          <div className="space-y-2 p-2.5 pt-0">
            <div className="grid grid-cols-2 gap-2">
              <input className={input} value={character.name} onChange={event => patchCharacter(character.id, { name: event.target.value })} placeholder="Name" />
              <input className={input} value={character.role || ''} onChange={event => patchCharacter(character.id, { role: event.target.value })} placeholder="Role / archetype" />
            </div>
            <textarea className={input} rows={3} value={character.description} onChange={event => patchCharacter(character.id, { description: event.target.value })} placeholder="Canonical appearance" />
            <textarea className={input} rows={2} value={character.personality || ''} onChange={event => patchCharacter(character.id, { personality: event.target.value })} placeholder="Personality, flaws and contradictions" />
            <textarea className={input} rows={2} value={character.motivation || ''} onChange={event => patchCharacter(character.id, { motivation: event.target.value })} placeholder="Goal, need and stakes" />
            <textarea className={input} rows={2} value={character.voice || ''} onChange={event => patchCharacter(character.id, { voice: event.target.value })} placeholder="Voice: vocabulary, rhythm, phrases to avoid" />
            <textarea className={input} rows={2} value={character.wardrobe || ''} onChange={event => patchCharacter(character.id, { wardrobe: event.target.value })} placeholder="Wardrobe and invariant accessories" />
            <textarea className={input} rows={2} value={character.visualNotes || ''} onChange={event => patchCharacter(character.id, { visualNotes: event.target.value })} placeholder="Face, body, palette, silhouette and scale" />
            <textarea className={input} rows={2} value={character.negativePrompt || ''} onChange={event => patchCharacter(character.id, { negativePrompt: event.target.value })} placeholder="Never show / continuity exclusions" />
            {!!character.referenceAssetIds?.length && (
              <div className="grid grid-cols-3 gap-1.5">
                {character.referenceAssetIds.map(assetId => {
                  const asset = project.assets[assetId]
                  return asset ? <button key={assetId} onClick={() => patchCharacter(character.id, { referenceAssetId: assetId })} className={`relative aspect-square overflow-hidden rounded border ${character.referenceAssetId === assetId ? 'border-accent-blue' : 'border-border'}`} title="Use as primary identity reference"><img src={asset.thumbnail || asset.source} className="size-full object-cover" /></button> : null
                })}
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <button className={button} disabled={busy !== null} onClick={() => { setUploadTarget(character.id); fileRef.current?.click() }}><Upload size={12} /> Add reference</button>
              <button className={`${button} border-purple-400/40 text-purple-300`} disabled={busy !== null} onClick={async () => { setBusy(character.id); try { await generateReference(character); notify('ok', `Reference generated for ${character.name}.`) } catch (error) { notify('error', (error as Error).message) } finally { setBusy(null) } }}>
                {busy === character.id ? <Loader2 size={12} className="animate-spin" /> : <ImagePlus size={12} />} Generate portrait
              </button>
            </div>
            <button className={`${button} w-full text-red-300`} onClick={() => updateCharacters(project.characters.filter(item => item.id !== character.id))}><Trash2 size={12} /> Remove character</button>
          </div>
        </details>
      ))}
      <div className="space-y-2 rounded-lg border border-dashed border-border p-2.5">
        <input className={input} value={draft.name} onChange={event => setDraft(value => ({ ...value, name: event.target.value }))} placeholder="New character name" />
        <input className={input} value={draft.role} onChange={event => setDraft(value => ({ ...value, role: event.target.value }))} placeholder="Role / archetype" />
        <textarea className={input} rows={2} value={draft.description} onChange={event => setDraft(value => ({ ...value, description: event.target.value }))} placeholder="Canonical appearance" />
        <button className={`${button} w-full`} disabled={!draft.name.trim()} onClick={add}><Plus size={12} /> Create character</button>
      </div>
    </div>
  )
}

export function ComicScriptPanel({ notify }: { notify: (kind: 'ok' | 'error', text: string) => void }) {
  const project = useComicStore(state => state.project)
  const director = project.director
  const storyboard = director?.input.productionMode === 'storyboard'
  const [revisionInstruction, setRevisionInstruction] = useState('')
  const [revising, setRevising] = useState(false)
  if (!director) return <p className="text-xs text-text-muted">Create an editable Director plan first.</p>
  const patchPlan = (patch: Partial<typeof director.plan>) => {
    const state = useComicStore.getState()
    const current = state.project.director!
    state.patchProject({ director: { ...current, plan: { ...current.plan, ...patch }, scriptApprovedAt: undefined, scriptVersion: (current.scriptVersion || 1) + 1 } })
  }
  const patchBeat = (index: number, patch: Record<string, string>) => {
    const beats = [...(director.plan.storyStructure || [])]
    beats[index] = { ...beats[index], ...patch }
    patchPlan({ storyStructure: beats })
  }
  const patchPanel = (pageIndex: number, panelIndex: number, script: string) => {
    const plan = structuredClone(director.plan)
    const panel = plan.pages[pageIndex].panels[panelIndex]
    const captions: string[] = []
    const dialogue: ComicPlanPanel['dialogue'] = []
    const soundEffects: string[] = []
    script.split(/\r?\n/).map(line => line.trim()).filter(Boolean).forEach(line => {
      const match = line.match(/^\[([^\]]+)\]\s*(.+)$/)
      const tag = match?.[1] || 'Dialogue'
      const text = match?.[2] || line
      if (/^caption$/i.test(tag)) captions.push(text)
      else if (/^sfx$/i.test(tag)) soundEffects.push(text)
      else dialogue.push({ speakerId: /^dialogue$/i.test(tag) ? undefined : tag, text, bubbleType: 'speech' })
    })
    Object.assign(panel, { captions, dialogue, soundEffects })
    const normalized = normalizeComicPlan(plan, director.input.dialogueDensity)
    const state = useComicStore.getState()
    state.patchProject(simplifyDirectorText({ ...state.project, director: { ...director, plan: normalized, scriptApprovedAt: undefined, scriptVersion: (director.scriptVersion || 1) + 1 } }))
  }
  const approve = () => {
    const state = useComicStore.getState()
    state.patchProject({ director: { ...state.project.director!, scriptApprovedAt: new Date().toISOString() } })
    notify('ok', 'Script approved. Artwork can now be generated from this version.')
  }
  const improveStory = async () => {
    if (director.completedPanelIds.length && !window.confirm('Some artwork already exists. Revising the story keeps those images, so changed scenes may need individual regeneration. Continue?')) return
    setRevising(true)
    try {
      const result = await api.reviseComicStory({
        plan: director.plan,
        instruction: revisionInstruction,
        dialogueDensity: director.input.dialogueDensity,
        productionMode: director.input.productionMode,
        writingProvider: director.input.writingProvider,
        writingModel: director.input.writingModel,
        writingBaseUrl: director.input.writingBaseUrl,
      })
      const state = useComicStore.getState()
      const current = state.project.director!
      const revisedPlan = normalizeComicPlan(result.plan, current.input.dialogueDensity)
      revisedPlan.pages.forEach(page => page.panels.forEach(panel => {
        panel.videoOverrideFields = []
      }))
      state.patchProject(simplifyDirectorText({
        ...state.project,
        title: result.plan.title,
        synopsis: result.plan.synopsis,
        director: {
          ...current,
          plan: revisedPlan,
          scriptApprovedAt: undefined,
          scriptVersion: (current.scriptVersion || 1) + 1,
        },
      }))
      notify('ok', 'Story revised. Review and approve the new script version before generating artwork.')
    } catch (error) {
      notify('error', (error as Error).message)
    } finally {
      setRevising(false)
    }
  }
  return (
    <div className="space-y-3">
      <div className={`rounded-lg border p-3 ${director.scriptApprovedAt ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-amber-500/40 bg-amber-500/5'}`}>
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">{director.scriptApprovedAt ? <Check size={14} className="text-emerald-400" /> : <Sparkles size={14} className="text-amber-300" />} Script v{director.scriptVersion || 1}</div>
        <p className="mt-1 text-[10px] text-text-muted">
          {storyboard
            ? 'Review dramatic beats, first-frame prompts and ready-to-render I2V prompts before generating expensive artwork.'
            : 'Review the dramatic beats and complete lettering before generating expensive artwork.'}
        </p>
      </div>
      <ComicWritingProviderFields
        value={director.input}
        disabled={revising}
        onChange={(key, value) => {
          const state = useComicStore.getState()
          const current = state.project.director!
          state.patchProject({ director: { ...current, input: { ...current.input, [key]: value } } })
        }}
      />
      <input className={input} value={director.plan.title} onChange={event => patchPlan({ title: event.target.value })} placeholder="Title" />
      <textarea className={input} rows={2} value={director.plan.logline} onChange={event => patchPlan({ logline: event.target.value })} placeholder="Logline" />
      <textarea className={input} rows={4} value={director.plan.synopsis} onChange={event => patchPlan({ synopsis: event.target.value })} placeholder="Synopsis" />
      {!!director.plan.storyStructure?.length && <div className="space-y-2"><strong className="text-[10px] uppercase tracking-wide text-text-muted">Page beats</strong>{director.plan.storyStructure.map((beat, index) => <div key={beat.pageNumber} className="space-y-1.5 rounded border border-border p-2"><input className={input} value={beat.stage} onChange={event => patchBeat(index, { stage: event.target.value })} /><textarea className={input} rows={2} value={beat.goal} onChange={event => patchBeat(index, { goal: event.target.value })} /><textarea className={input} rows={2} value={beat.turningPoint} onChange={event => patchBeat(index, { turningPoint: event.target.value })} /></div>)}</div>}
      <div className="space-y-2 rounded-lg border border-border bg-bg-tertiary/30 p-2.5"><strong className="text-[10px] uppercase tracking-wide text-text-muted">Improve story with the LLM</strong><textarea className={input} rows={3} value={revisionInstruction} onChange={event => setRevisionInstruction(event.target.value)} placeholder="Optional direction: clarify the protagonist's goal, make the midpoint reverse the plan, pay off the opening image…" /><button className={`${button} w-full border-purple-400/40 text-purple-300`} disabled={revising} onClick={improveStory}>{revising ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />} Revise full story</button></div>
      <div className="space-y-2">
        <strong className="text-[10px] uppercase tracking-wide text-text-muted">
          {storyboard ? 'Shot list and video prompts' : 'Full script'}
        </strong>
        {director.plan.pages.map((page, pageIndex) => (
          <details
            key={`${page.pageNumber}-${director.scriptVersion || 1}`}
            className="rounded border border-border bg-bg-tertiary/30"
            style={{ contentVisibility: 'auto', containIntrinsicSize: '400px' }}
            open={pageIndex === 0}
          >
            <summary className="cursor-pointer p-2 text-xs text-text-primary">
              {storyboard ? `Shot ${page.pageNumber}` : `Page ${page.pageNumber} · ${page.panels.length} panels`}
            </summary>
            <div className="space-y-2 p-2 pt-0">
              {page.panels.map((panel, panelIndex) => storyboard ? (
                <div key={`${panel.id}-${director.scriptVersion || 1}`} className="space-y-2 rounded border border-border p-2">
                  <label className="block text-[10px] text-text-muted">
                    First-frame image prompt
                    <textarea
                      className={`${input} mt-1`}
                      rows={4}
                      value={panel.imagePrompt}
                      onChange={event => {
                        const plan = structuredClone(useComicStore.getState().project.director!.plan)
                        plan.pages[pageIndex].panels[panelIndex].imagePrompt = event.target.value
                        patchPlan({ pages: plan.pages })
                      }}
                    />
                  </label>
                  <label className="block text-[10px] text-text-muted">
                    I2V motion / performance prompt
                    <textarea
                      className={`${input} mt-1`}
                      rows={6}
                      value={panel.videoPrompt || ''}
                      onChange={event => {
                        const plan = structuredClone(useComicStore.getState().project.director!.plan)
                        const editedPanel = plan.pages[pageIndex].panels[panelIndex]
                        editedPanel.videoPrompt = event.target.value
                        editedPanel.videoOverrideFields = mergeComicVideoOverrideFields(
                          editedPanel.videoOverrideFields,
                          ['video_prompt'],
                        )
                        patchPlan({ pages: plan.pages })
                      }}
                    />
                  </label>
                </div>
              ) : (
                <label key={`${panel.id}-${director.scriptVersion || 1}`} className="block text-[10px] text-text-muted">
                  Panel {panelIndex + 1} · {panel.narrativeRole}
                  <textarea className={`${input} mt-1`} rows={3} defaultValue={scriptForPanel(panel)} onBlur={event => patchPanel(pageIndex, panelIndex, event.target.value)} placeholder="Silent panel" />
                </label>
              ))}
            </div>
          </details>
        ))}
      </div>
      <button className={`${button} w-full border-emerald-500/50 text-emerald-300`} onClick={approve}><ShieldCheck size={13} /> Approve this script</button>
    </div>
  )
}

type QualityIssue = { level: 'error' | 'warning' | 'tip'; text: string }

export function ComicQualityPanel({ notify }: { notify: (kind: 'ok' | 'error', text: string) => void }) {
  const project = useComicStore(state => state.project)
  const [draft, setDraft] = useState<ComicGlossaryEntry>({ source: '', translation: '', note: '' })
  const issues = useMemo<QualityIssue[]>(() => {
    const found: QualityIssue[] = []
    const director = project.director
    if (!director) return [{ level: 'error', text: 'No Director plan is attached to this comic.' }]
    if (!director.scriptApprovedAt) found.push({ level: 'warning', text: 'The current script version has not been approved.' })
    if (!director.plan.storyStructure?.length) found.push({ level: 'warning', text: 'The comic has no explicit dramatic page structure.' })
    const known = new Set(project.characters.map(character => character.id))
    director.plan.pages.forEach((page, pageIndex) => {
      const seen = new Set<string>()
      page.panels.forEach((panel, panelIndex) => {
        const blocks = panel.captions.length + panel.dialogue.length + panel.soundEffects.length
        if (blocks > (page.panels.length >= 7 ? 1 : 2)) found.push({ level: 'error', text: `Page ${pageIndex + 1}, panel ${panelIndex + 1} has ${blocks} text blocks.` })
        if (!(panel.continuityNotes || '').trim()) found.push({ level: 'tip', text: `Page ${pageIndex + 1}, panel ${panelIndex + 1} has no continuity note.` })
        panel.characters.filter(id => !known.has(id)).forEach(id => found.push({ level: 'error', text: `Unknown character “${id}” in page ${pageIndex + 1}.` }))
        ;[...panel.captions, ...panel.dialogue.map(line => line.text)].forEach(line => {
          const key = String(line || '').trim().toLocaleLowerCase()
          if (key && seen.has(key)) found.push({ level: 'warning', text: `Repeated line on page ${pageIndex + 1}: “${line}”.` })
          seen.add(key)
        })
      })
    })
    project.characters.forEach(character => {
      if (!character.personality?.trim()) found.push({ level: 'tip', text: `${character.name} has no personality definition.` })
      if (!character.referenceAssetId) found.push({ level: 'warning', text: `${character.name} has no primary visual reference.` })
    })
    return found
  }, [project])
  const score = Math.max(0, 100 - issues.reduce((sum, issue) => sum + (issue.level === 'error' ? 15 : issue.level === 'warning' ? 7 : 2), 0))
  const addGlossary = () => {
    if (!draft.source.trim() || !draft.translation.trim()) return
    useComicStore.getState().patchProject({ translationGlossary: [...(project.translationGlossary || []), { source: draft.source.trim(), translation: draft.translation.trim(), note: draft.note?.trim() }] })
    setDraft({ source: '', translation: '', note: '' })
  }
  return <div className="space-y-3"><div className="rounded-lg border border-border bg-bg-tertiary/30 p-3"><div className="flex items-center justify-between"><span className="text-xs font-semibold text-text-primary">Preflight score</span><span className={`text-xl font-bold ${score >= 80 ? 'text-emerald-400' : score >= 55 ? 'text-amber-300' : 'text-red-400'}`}>{score}</span></div><p className="text-[10px] text-text-muted">Story, lettering, characters and continuity checks.</p></div><div className="space-y-1.5">{issues.length ? issues.slice(0, 40).map((issue, index) => <div key={`${issue.text}-${index}`} className={`rounded border px-2 py-1.5 text-[10px] ${issue.level === 'error' ? 'border-red-500/30 text-red-300' : issue.level === 'warning' ? 'border-amber-500/30 text-amber-300' : 'border-border text-text-muted'}`}>{issue.text}</div>) : <div className="rounded border border-emerald-500/30 p-2 text-xs text-emerald-300">No obvious continuity or lettering problems found.</div>}</div><button className={`${button} w-full`} disabled={!project.director} onClick={() => { const state = useComicStore.getState(); state.patchProject(simplifyDirectorText(state.project)); notify('ok', 'Safe lettering limits and layout were reapplied without changing images.') }}><Sparkles size={12} /> Apply safe fixes</button><div className="border-t border-border pt-3 space-y-2"><strong className="text-[10px] uppercase tracking-wide text-text-muted">Translation glossary</strong><p className="text-[9px] text-text-muted">Names and terms here are enforced during translated export.</p>{(project.translationGlossary || []).map((entry, index) => <div key={`${entry.source}-${index}`} className="flex items-center gap-1 rounded border border-border p-1.5 text-[10px]"><span className="text-text-primary">{entry.source}</span><span className="text-text-muted">→</span><span className="text-accent-blue">{entry.translation}</span><button className="ml-auto text-red-300" onClick={() => useComicStore.getState().patchProject({ translationGlossary: (project.translationGlossary || []).filter((_, itemIndex) => itemIndex !== index) })}><Trash2 size={11} /></button></div>)}<input className={input} value={draft.source} onChange={event => setDraft(value => ({ ...value, source: event.target.value }))} placeholder="Source term" /><input className={input} value={draft.translation} onChange={event => setDraft(value => ({ ...value, translation: event.target.value }))} placeholder="Required translation" /><input className={input} value={draft.note || ''} onChange={event => setDraft(value => ({ ...value, note: event.target.value }))} placeholder="Optional context" /><button className={`${button} w-full`} onClick={addGlossary}><Plus size={12} /> Add term</button></div></div>
}

export function ComicVideoPanel({ notify }: { notify: (kind: 'ok' | 'error', text: string) => void }) {
  const project = useComicStore(state => state.project)
  const refreshOutputs = useStore(state => state.refreshOutputs)
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const selectedVideoModel = useStore(state => state.selectedModelPerMode.video)
  const videoModels = useStore(state => state.models)
  const enabledModels = useStore(state => state.enabledModels)
  const selectDirectorVideoModel = useStore(state => state.selectDirectorVideoModel)
  const savedVideoLoras = useStore(state => state.savedLoraPerMode.video)
  const savedVideoParams = useStore(state => state.savedParamsPerMode.video)
  const movieSpatialUpsampling = useStore(state => state.directorVideoSpatialUpsampling)
  const movieFilmGrainIntensity = useStore(state => state.directorVideoFilmGrainIntensity)
  const movieFilmGrainSaturation = useStore(state => state.directorVideoFilmGrainSaturation)
  const movieSelfRefiner = useStore(state => state.directorVideoSelfRefiner)
  const movieAudioScale = useStore(state => state.directorAudioScale)
  const setMovieSelfRefiner = useStore(state => state.setDirectorVideoSelfRefiner)
  const storyboard = project.director?.input.productionMode === 'storyboard'
  const restoredSettings = readComicVideoSettings(activeWorkspace, project.id)
  const [aspect, setAspect] = useState<ComicMovieAspect>(() =>
    restoredSettings.aspect || project.director?.input.storyboardAspect || 'landscape')
  const [defaultDuration, setDefaultDuration] = useState(
    restoredSettings.defaultDuration || 3,
  )
  const [targetFilmShots, setTargetFilmShots] = useState(
    Number.isFinite(Number(restoredSettings.targetFilmShots))
      ? Math.max(0, Math.min(200, Math.trunc(Number(restoredSettings.targetFilmShots))))
      : 0,
  )
  const [transition, setTransition] = useState('none')
  const [animaticMotion, setAnimaticMotion] = useState<'none' | 'shot-settings'>('none')
  const [movieQuality, setMovieQuality] = useState<ComicMovieQuality>(
    restoredSettings.quality || '720p',
  )
  const [movieMotionMode, setMovieMotionMode] = useState<'contextual' | 'living-still' | 'action'>(
    restoredSettings.motionMode || (storyboard ? 'action' : 'contextual'),
  )
  const [movieImageFit, setMovieImageFit] = useState<'reframe' | 'cover' | 'contain'>(
    restoredSettings.imageFit === 'reframe' ? 'contain' : restoredSettings.imageFit || 'contain',
  )
  const [movieEndFrameMode, setMovieEndFrameMode] = useState<'none' | 'smart' | 'all'>(
    restoredSettings.endFrameMode || 'none',
  )
  const [movieFidelity, setMovieFidelity] = useState<'faithful' | 'balanced' | 'expressive'>(
    restoredSettings.fidelity || 'faithful',
  )
  const [settingsScope, setSettingsScope] = useState(() =>
    comicVideoSettingsKey(activeWorkspace, project.id))
  const [videoTab, setVideoTab] = useState<'settings' | 'shots'>('settings')
  const [busy, setBusy] = useState<'animatic' | 'movie' | 'preflight' | null>(null)
  const [progress, setProgress] = useState('')
  const [result, setResult] = useState<{ name: string; url: string } | null>(null)
  const [preflightPipelineId, setPreflightPipelineId] = useState<string | null>(null)
  const [preflightStatus, setPreflightStatus] = useState<api.PipelineStatus | null>(null)
  const [preflightBuiltFingerprint, setPreflightBuiltFingerprint] = useState('')
  const preflightStorageKey = `maestro-comic-preflight:${activeWorkspace}:${project.id}`
  const preflightFingerprintStorageKey = `${preflightStorageKey}:fingerprint`
  useEffect(() => {
    const saved = readComicVideoSettings(activeWorkspace, project.id)
    setAspect(saved.aspect || project.director?.input.storyboardAspect || 'landscape')
    setDefaultDuration(saved.defaultDuration || 3)
    setTargetFilmShots(
      Number.isFinite(Number(saved.targetFilmShots))
        ? Math.max(0, Math.min(200, Math.trunc(Number(saved.targetFilmShots))))
        : 0,
    )
    setMovieQuality(saved.quality || '720p')
    setMovieMotionMode(saved.motionMode || (storyboard ? 'action' : 'contextual'))
    setMovieImageFit(saved.imageFit === 'reframe' ? 'contain' : saved.imageFit || 'contain')
    setMovieEndFrameMode(saved.endFrameMode || 'none')
    setMovieFidelity(saved.fidelity || 'faithful')
    setSettingsScope(comicVideoSettingsKey(activeWorkspace, project.id))
    setVideoTab('settings')
  }, [
    activeWorkspace,
    project.id,
    storyboard,
    project.director?.input.storyboardAspect,
    project.director?.input.storyboardQuality,
  ])
  useEffect(() => {
    try {
      window.localStorage.setItem(
        settingsScope,
        JSON.stringify({
          aspect,
          defaultDuration,
          targetFilmShots,
          quality: movieQuality,
          motionMode: movieMotionMode,
          imageFit: movieImageFit,
          endFrameMode: movieEndFrameMode,
          fidelity: movieFidelity,
        } satisfies SavedComicVideoSettings),
      )
    } catch {
      // Private browsing may disable persistence; the live configuration remains valid.
    }
  }, [
    aspect,
    defaultDuration,
    movieEndFrameMode,
    movieFidelity,
    movieImageFit,
    movieMotionMode,
    movieQuality,
    settingsScope,
    targetFilmShots,
  ])
  useEffect(() => {
    let cancelled = false

    const recover = async () => {
      const remembered = window.localStorage.getItem(preflightStorageKey)
      const candidates: string[] = remembered ? [remembered] : []
      try {
        const { pipelines } = await api.fetchPipelineList()
        pipelines
          .filter(item =>
            item.pipeline_type === 'comic_movie'
            && item.status === 'preview_ready'
            && item.comic_id === project.id,
          )
          .forEach(item => {
            if (!candidates.includes(item.id)) candidates.push(item.id)
          })
      } catch {
        // A remembered checkpoint can still be recovered directly while the
        // dashboard list is temporarily unavailable.
      }
      for (const pipelineId of candidates) {
        try {
          const status = await api.fetchPipelineStatus(pipelineId)
          if (cancelled || status.status !== 'preview_ready') continue
          setPreflightPipelineId(pipelineId)
          setPreflightStatus(status)
          setPreflightBuiltFingerprint(
            window.localStorage.getItem(preflightFingerprintStorageKey) || '',
          )
          window.localStorage.setItem(preflightStorageKey, pipelineId)
          return
        } catch {
          // Try the next durable checkpoint.
        }
      }
      if (!cancelled) {
        setPreflightPipelineId(null)
        setPreflightStatus(null)
        setPreflightBuiltFingerprint('')
        if (remembered) window.localStorage.removeItem(preflightStorageKey)
      }
    }
    void recover()
    return () => { cancelled = true }
  }, [
    activeWorkspace,
    preflightFingerprintStorageKey,
    preflightStorageKey,
    project.id,
  ])
  const panelCount = project.pages.reduce(
    (total, page) => total + page.elements.filter(element => element.type === 'panel' && !element.parentId).length,
    0,
  )
  const videoShotRows = useMemo(() => {
    const rows = (project.director?.plan.pages || []).flatMap((page, pageIndex) =>
      page.panels.map((planned, panelIndex) => ({
        planned,
        pageIndex,
        panelIndex,
        naturalOrder: pageIndex * 1000 + panelIndex,
      })),
    )
    return rows.sort((left, right) => {
      const leftOrder = Number.isFinite(Number(left.planned.videoOrder))
        ? Number(left.planned.videoOrder)
        : left.naturalOrder
      const rightOrder = Number.isFinite(Number(right.planned.videoOrder))
        ? Number(right.planned.videoOrder)
        : right.naturalOrder
      return leftOrder - rightOrder || left.naturalOrder - right.naturalOrder
    })
  }, [project.director?.plan.pages])
  const includedVideoShots = videoShotRows.filter(row => row.planned.videoIncluded !== false)
  const selectedTestShots = includedVideoShots.filter(row => row.planned.videoTestSelected)
  const selectableVideoModels = useMemo(
    () => videoModels
      .filter(model => model.is_i2v && enabledModels.has(model.model_type))
      .sort((left, right) => left.name.localeCompare(right.name)),
    [enabledModels, videoModels],
  )
  const effectiveVideoModel = selectedVideoModel || 'ltx2_22B_distilled_1_1'
  const effectiveVideoModelName = videoModels.find(
    model => model.model_type === effectiveVideoModel,
  )?.name || effectiveVideoModel
  const movieResolutionOptions = useMemo(
    () => comicMovieResolutions(effectiveVideoModel, aspect),
    [aspect, effectiveVideoModel],
  )
  const selectedMovieResolution = movieResolutionOptions.find(
    option => option.quality === movieQuality,
  ) || movieResolutionOptions.find(option => option.recommended) || movieResolutionOptions[0]
  useEffect(() => {
    if (movieResolutionOptions.some(option => option.quality === movieQuality)) return
    setMovieQuality(
      movieResolutionOptions.find(option => option.recommended)?.quality
      || movieResolutionOptions[0].quality,
    )
  }, [movieQuality, movieResolutionOptions])
  const resolution = aspect === 'portrait'
    ? { width: 1080, height: 1920 }
    : aspect === 'square' ? { width: 1080, height: 1080 } : { width: 1920, height: 1080 }
  const preflightFingerprint = JSON.stringify({
    comicId: project.id,
    updatedAt: project.updatedAt,
    aspect,
    defaultDuration,
    movieQuality,
    movieResolution: selectedMovieResolution.value,
    movieMotionMode,
    movieImageFit,
    movieEndFrameMode,
    movieFidelity,
    movieSelfRefiner,
    selectedVideoModel: effectiveVideoModel,
    savedVideoLoras,
    targetFilmShots,
    videoRuntime: {
      savedVideoParams,
      spatialUpsampling: movieSpatialUpsampling,
      filmGrainIntensity: movieFilmGrainIntensity,
      filmGrainSaturation: movieFilmGrainSaturation,
      audioScale: movieAudioScale,
    },
    shots: videoShotRows.map(({ planned }) => ({
      id: planned.id,
      included: planned.videoIncluded !== false,
      order: planned.videoOrder,
      renderer: planned.videoRenderer || 'auto',
      fit: planned.videoFit,
      action: planned.videoAction,
      prompt: planned.videoPrompt,
      motion: planned.videoMotion,
      motionLevel: planned.videoMotionLevel,
      duration: planned.durationSeconds,
      camera: planned.cameraMove,
      endFrame: planned.videoEndFrame,
      seed: planned.videoSeed,
      sources: planned.videoSourcePanelIds,
      overrides: planned.videoOverrideFields,
    })),
  })
  const preflightIsStale = Boolean(
    preflightStatus?.status === 'preview_ready'
    && preflightBuiltFingerprint !== preflightFingerprint,
  )
  const updateShot = (
    pageIndex: number,
    panelIndex: number,
    patch: Partial<ComicPlanPanel>,
    overrideChanges = overrideChangesForPatch(patch),
  ) => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const plan = structuredClone(director.plan)
    const panel = plan.pages[pageIndex].panels[panelIndex]
    Object.assign(panel, patch)
    panel.videoOverrideFields = mergeComicVideoOverrideFields(
      panel.videoOverrideFields,
      overrideChanges.add,
      overrideChanges.remove,
    )
    state.patchProject({ director: { ...director, plan } })
  }
  const updateAllShots = (
    patch: Partial<ComicPlanPanel>,
    message: string,
    overrideChanges = overrideChangesForPatch(patch),
  ) => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const plan = structuredClone(director.plan)
    plan.pages.forEach(page => page.panels.forEach(planned => {
      Object.assign(planned, patch)
      planned.videoOverrideFields = mergeComicVideoOverrideFields(
        planned.videoOverrideFields,
        overrideChanges.add,
        overrideChanges.remove,
      )
    }))
    state.patchProject({ director: { ...director, plan } })
    notify('ok', message)
  }
  const moveShot = (rowIndex: number, direction: -1 | 1) => {
    const destination = rowIndex + direction
    if (destination < 0 || destination >= videoShotRows.length) return
    const reordered = [...videoShotRows]
    ;[reordered[rowIndex], reordered[destination]] = [reordered[destination], reordered[rowIndex]]
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const plan = structuredClone(director.plan)
    reordered.forEach((row, index) => {
      const planned = plan.pages[row.pageIndex]?.panels[row.panelIndex]
      if (planned) {
        planned.videoOrder = index
        planned.videoOverrideFields = mergeComicVideoOverrideFields(
          planned.videoOverrideFields,
          ['order'],
        )
      }
    })
    state.patchProject({ director: { ...director, plan } })
  }
  const selectRepresentativeTests = () => {
    if (!videoShotRows.length) return
    const targetRatio = aspect === 'portrait' ? 9 / 16 : aspect === 'square' ? 1 : 16 / 9
    const score = (row: (typeof videoShotRows)[number], kind: string) => {
      const panel = row.planned
      const text = `${panel.framing} ${panel.narrativeRole} ${panel.sceneDescription}`.toLowerCase()
      const canvasPage = project.pages[row.pageIndex]
      const canvasPanel = canvasPage?.elements
        .filter(element => element.type === 'panel' && !element.parentId)
        .at(row.panelIndex)
      const ratio = canvasPanel ? canvasPanel.width / Math.max(1, canvasPanel.height) : 1
      if (kind === 'aspect') return Math.abs(Math.log(Math.max(.01, ratio) / targetRatio))
      if (kind === 'face') return /close|portrait|rostro|primer plano/.test(text) ? 10 : 0
      if (kind === 'multi') return panel.characters.length
      if (kind === 'action') return /(run|fight|jump|fall|cross|attack|correr|lucha|salta|cae|cruza)/.test(text) ? 10 : (panel.videoMotionLevel || 0)
      if (kind === 'quiet') return /(wide|landscape|establish|panoram|silence|quiet|paisaje|silencio)/.test(text) ? 10 : 0
      return 0
    }
    const selected = new Set<string>()
    ;['aspect', 'face', 'multi', 'action', 'quiet'].forEach(kind => {
      const candidate = includedVideoShots
        .filter(row => !selected.has(row.planned.id))
        .sort((left, right) => score(right, kind) - score(left, kind))[0]
      if (candidate) selected.add(candidate.planned.id)
    })
    if (selected.size < Math.min(4, includedVideoShots.length)) {
      includedVideoShots.forEach(row => {
        if (selected.size < Math.min(4, includedVideoShots.length)) selected.add(row.planned.id)
      })
    }
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const plan = structuredClone(director.plan)
    plan.pages.forEach(page => page.panels.forEach(planned => {
      planned.videoTestSelected = selected.has(planned.id)
      planned.videoOverrideFields = mergeComicVideoOverrideFields(
        planned.videoOverrideFields,
        ['test_selected'],
      )
    }))
    state.patchProject({ director: { ...director, plan } })
    notify('ok', `Selected ${selected.size} representative shots: aspect risk, face, ensemble, action and quiet detail.`)
  }
  const resolvedMotionMode = (planned?: ComicPlanPanel): 'contextual' | 'living-still' | 'action' =>
    planned?.videoMotion === 'contextual'
      || planned?.videoMotion === 'living-still'
      || planned?.videoMotion === 'action'
      ? planned.videoMotion
      : movieMotionMode
  const resolvedRenderer = (planned?: ComicPlanPanel) => planned?.videoRenderer
  const resolvedFit = (planned?: ComicPlanPanel) =>
    planned?.videoOverrideFields?.includes('fit') && planned.videoFit
      ? planned.videoFit
      : movieImageFit
  const resolvedMovieDuration = (planned?: ComicPlanPanel) =>
    planned?.durationSeconds || defaultDuration
  const motionTreatmentLabel = (mode: 'contextual' | 'living-still' | 'action') =>
    mode === 'contextual'
      ? 'context-aware performance with a fixed camera'
      : mode === 'living-still'
        ? 'deterministic living still with a fixed camera'
        : 'authored story action and camera'
  const create = async () => {
    if (panelCount > 200) {
      notify('error', `This animatic has ${panelCount} panels; the safe limit is 200.`)
      return
    }
    if (!window.confirm(
      `Render a quick non-generative storyboard preview from ${panelCount} still panels? `
      + 'This does not call the selected video model or animate characters; it only holds the drawings and optionally applies FFmpeg pans, zooms and transitions.',
    )) return
    setBusy('animatic')
    setResult(null)
    try {
      const panels: Array<{
        source: string
        page_number: number
        panel_number: number
        duration: number
        duration_seconds: number
        motion: string
        script: string
      }> = []
      await forEachComicPanelCapture(async (capture, current, total) => {
        setProgress(`Uploading shot ${current}/${total}`)
        const blob = await (await fetch(capture.dataUrl)).blob()
        const upload = await api.uploadImage(new File(
          [blob],
          `comic-${capture.pageNumber}-${capture.panelNumber}.png`,
          { type: 'image/png' },
        ))
        const planned = project.director?.plan.pages[capture.pageNumber - 1]?.panels[capture.panelNumber - 1]
        panels.push({
          source: upload.url,
          page_number: capture.pageNumber,
          panel_number: capture.panelNumber,
          duration: planned?.durationSeconds || defaultDuration,
          duration_seconds: planned?.durationSeconds || defaultDuration,
          motion: animaticMotion === 'shot-settings'
            ? (planned?.cameraMove || 'none')
            : 'none',
          script: planned ? scriptForPanel(planned) : '',
        })
      }, (current, total) => setProgress(`Capturing panel ${current}/${total}`))
      setProgress('Starting FFmpeg animatic…')
      const started = await api.startComicAnimatic({
        comic_id: project.id,
        comic_title: project.title,
        ...resolution,
        fps: 30,
        transition,
        transition_duration: .35,
        panels,
      })
      for (;;) {
        await new Promise(resolve => window.setTimeout(resolve, 1000))
        const job = await api.fetchVideoEditorExport(started.job_id)
        setProgress(`${job.message} · ${job.progress}%`)
        if (job.status === 'failed') throw new Error(job.error || job.message)
        if (job.status === 'completed' && job.url && job.filename) {
          const completed = { name: job.filename, url: job.url }
          setResult(completed)
          try { window.localStorage.setItem('maestro-video-editor-pending-source', JSON.stringify(completed)) } catch { /* optional hand-off */ }
          await refreshOutputs()
          notify('ok', 'Animatic created. It is ready in the gallery and Video Editor.')
          break
        }
      }
    } catch (error) {
      notify('error', (error as Error).message)
    } finally {
      setBusy(null)
      setProgress('')
    }
  }

  const convertToMovie = async (
    clipLimit?: number,
    preflightOnly = false,
    selectedPanelIds?: string[],
  ) => {
    const selected = new Set(selectedPanelIds || [])
    const requestedRows = includedVideoShots
      .filter(row => !selected.size || selected.has(row.planned.id))
      .slice(
        0,
        Number.isFinite(Number(clipLimit))
          ? Math.max(1, Math.floor(Number(clipLimit)))
          : undefined,
      )
    const requestedPanelCount = requestedRows.length
    if (!requestedPanelCount) {
      notify('error', selected.size
        ? 'None of the selected test shots is enabled.'
        : 'The film adaptation has no enabled shots.')
      return
    }
    if (requestedPanelCount > 200) {
      notify('error', `This conversion has ${requestedPanelCount} panels; the safe limit is 200.`)
      return
    }
    const plannedForRun = requestedRows.map(row => row.planned)
    const totalSeconds = Math.round(
      plannedForRun.reduce((sum, planned) => sum + resolvedMovieDuration(planned), 0)
      || requestedPanelCount * defaultDuration,
    )
    const isTestRun = (clipLimit !== undefined || selected.size > 0) && !preflightOnly
    if (!preflightOnly && !window.confirm(
      `${isTestRun ? 'Create a selected quality test from' : 'Adapt'} ${requestedPanelCount} `
      + `source beat${requestedPanelCount === 1 ? '' : 's'} into an estimated ${totalSeconds}s film edit? `
      + `Global motion treatment: ${motionTreatmentLabel(movieMotionMode)}; per-shot overrides are shown in the shot plan. `
      + `${isTestRun ? 'This uses the final model, resolution, prompts and shot settings; it is not a lower-quality preview. ' : ''}`
      + `Selected video engine: ${effectiveVideoModelName} (${effectiveVideoModel}). `
      + `Exact output request: ${selectedMovieResolution.value}. `
      + 'Director may omit or fuse source beats. Only model-driven and AI-living-still shots use I2V; holds and subtle centered pushes are deterministic.',
    )) return

    const activityId = `comic-video:${project.id}:${Date.now()}`
    const reportActivity = (
      message: string,
      phase = 'preparing_comic_video',
      current = 0,
      total = 0,
    ) => {
      setProgress(message)
      useStore.getState().setForegroundActivity({
        id: activityId,
        status: 'running',
        phase,
        message,
        current,
        total,
      })
    }
    let activityFailed = false
    setBusy(preflightOnly ? 'preflight' : 'movie')
    setResult(null)
    reportActivity('Preparing comic video…')
    if (preflightOnly) {
      setPreflightPipelineId(null)
      setPreflightStatus(null)
    }
    try {
      const comicShots: Array<{
        comic_title: string
        image_path: string
        page_number: number
        panel_number: number
        capture_width: number
        capture_height: number
        duration: number
        duration_seconds: number
        camera_move: string
        narrative_role: string
        scene_description: string
        image_prompt: string
        framing: string
        characters: string[]
        script: string
        visual_style: string
        video_prompt: string
        motion_mode: 'contextual' | 'living-still' | 'action'
        end_frame_mode: 'auto' | 'none' | 'next-panel'
        panel_id: string
        source_panel_ids: string[]
        included: boolean
        renderer?: 'hold' | 'parallax' | 'cinemagraph' | 'ltx'
        fit_mode: 'reframe' | 'cover' | 'contain'
        motion_level: number
        test_selected: boolean
        seed: number
        action_override: boolean
        renderer_override: boolean
        fit_override: boolean
        motion_mode_override: boolean
        motion_level_override: boolean
        duration_override: boolean
        camera_override: boolean
        video_prompt_override: boolean
        seed_override: boolean
        end_frame_override: boolean
        test_selected_override: boolean
      }> = []
      const rowByPosition = new Map(
        requestedRows.map(row => [`${row.pageIndex + 1}.${row.panelIndex + 1}`, row]),
      )
      const rowOrder = new Map(requestedRows.map((row, index) => [row.planned.id, index]))
      await forEachComicPanelCapture(async (capture, current, total) => {
        const row = rowByPosition.get(`${capture.pageNumber}.${capture.panelNumber}`)
        if (!row) return
        reportActivity(`Preparing artwork ${current}/${total}`, 'uploading_artwork', current, total)
        const blob = await (await fetch(capture.dataUrl)).blob()
        const upload = await api.uploadImage(new File(
          [blob],
          `comic-movie-${capture.pageNumber}-${capture.panelNumber}.png`,
          { type: 'image/png' },
        ))
        const planned = row.planned
        const motionMode = resolvedMotionMode(planned)
        const renderer = resolvedRenderer(planned)
        const overrides = new Set(planned.videoOverrideFields || [])
        comicShots.push({
          comic_title: project.title,
          image_path: upload.path,
          page_number: capture.pageNumber,
          panel_number: capture.panelNumber,
          capture_width: capture.width,
          capture_height: capture.height,
          duration: resolvedMovieDuration(planned),
          duration_seconds: resolvedMovieDuration(planned),
          camera_move: (!renderer || renderer === 'ltx') && overrides.has('camera')
            ? (planned.cameraMove || 'none')
            : 'none',
          narrative_role: planned?.narrativeRole || `Panel ${capture.pageNumber}.${capture.panelNumber}`,
          scene_description: planned?.videoAction || planned?.sceneDescription || '',
          image_prompt: planned?.imagePrompt || '',
          framing: planned?.framing || 'match comic panel',
          characters: planned?.characters || [],
          script: planned ? scriptForPanel(planned) : '',
          video_prompt: planned?.videoPrompt || planned?.videoAction || '',
          motion_mode: renderer === 'hold'
            || renderer === 'parallax'
            || renderer === 'cinemagraph'
            ? 'living-still'
            : motionMode,
          end_frame_mode: planned?.videoEndFrame || 'auto',
          panel_id: planned.id,
          source_panel_ids: planned.videoSourcePanelIds?.length
            ? planned.videoSourcePanelIds
            : [planned.id],
          included: true,
          renderer,
          fit_mode: resolvedFit(planned),
          motion_level: planned.videoMotionLevel ?? (renderer === 'hold' ? 0 : 1),
          test_selected: Boolean(planned.videoTestSelected),
          seed: Number.isFinite(Number(planned.videoSeed))
            ? Number(planned.videoSeed)
            : Math.abs([...planned.id].reduce((hash, character) =>
              ((hash * 31) + character.charCodeAt(0)) | 0, 2166136261)),
          action_override: overrides.has('action'),
          renderer_override: overrides.has('renderer'),
          fit_override: overrides.has('fit'),
          motion_mode_override: overrides.has('motion_mode'),
          motion_level_override: overrides.has('motion_level'),
          duration_override: overrides.has('duration'),
          camera_override: overrides.has('camera'),
          video_prompt_override: overrides.has('video_prompt'),
          seed_override: overrides.has('seed'),
          end_frame_override: overrides.has('end_frame'),
          test_selected_override: overrides.has('test_selected'),
          visual_style: [
            project.style.name,
            project.style.promptSuffix,
            project.director?.plan.styleBible || '',
          ].filter(Boolean).join('. '),
        })
      }, (current, total) => reportActivity(
        `Capturing clean artwork ${current}/${total}`,
        'preparing_comic_video',
        current,
        total,
      ), {
        // Lettering remains in the comic/script but is removed from I2V first
        // frames so the video model cannot warp speech bubbles or captions.
        includeLettering: false,
      })
      comicShots.sort((left, right) =>
        (rowOrder.get(left.panel_id) ?? Number.MAX_SAFE_INTEGER)
        - (rowOrder.get(right.panel_id) ?? Number.MAX_SAFE_INTEGER))

      const movieContext = [
        `TITLE: ${project.title}`,
        `SYNOPSIS: ${project.synopsis}`,
        `LANGUAGE: ${project.language}`,
        `COMIC STYLE: ${project.style.name}. ${project.style.promptSuffix}`,
        project.director?.plan.logline ? `LOGLINE: ${project.director.plan.logline}` : '',
        project.director?.plan.synopsis ? `DIRECTOR SYNOPSIS: ${project.director.plan.synopsis}` : '',
        project.director?.plan.styleBible ? `STYLE BIBLE: ${project.director.plan.styleBible}` : '',
        `CHARACTERS:\n${project.characters.map(character => [
          character.id,
          character.name,
          character.description,
          character.personality,
          character.motivation,
          character.voice,
          character.wardrobe,
          character.visualNotes,
        ].filter(Boolean).join(' · ')).join('\n')}`,
        project.director?.plan.storyStructure?.length
          ? `STORY STRUCTURE:\n${JSON.stringify(project.director.plan.storyStructure)}`
          : '',
        project.director?.input.storyContext ? `MASTER STORY CANON:\n${project.director.input.storyContext}` : '',
        project.director?.input.worldContext ? `WORLD CONTINUITY:\n${project.director.input.worldContext}` : '',
        project.director?.input.forbiddenElements ? `NEVER INTRODUCE: ${project.director.input.forbiddenElements}` : '',
      ].filter(Boolean).join('\n\n')

      const before = useStore.getState()
      const videoModel = before.selectedModelPerMode.video || 'ltx2_22B_distilled_1_1'
      await before.loadModelOptions(videoModel)
      const state = useStore.getState()
      if (
        movieEndFrameMode !== 'none'
        && state.modelOptions
        && !state.modelOptions.supports_end_frame
      ) {
        throw new Error(
          'The selected video model does not support end frames. '
          + 'Choose a model with end-frame support or use “No end frame”.',
        )
      }
      const qualityResolution = selectedMovieResolution.value
      const fps = state.modelOptions?.fps || 16
      const savedVideoSteps = Number(state.savedParamsPerMode.video?.num_inference_steps ?? 8)
      const validVideoSteps = Number.isFinite(savedVideoSteps) ? savedVideoSteps : 8
      const isLtxDistilled = videoModel.includes('ltx2') && videoModel.includes('distilled')
      const videoSteps = isLtxDistilled
        ? 8
        : validVideoSteps
      const plannedClips = comicShots.reduce<PlannedClip[]>((clips, shot, index) => {
        const start = index === 0 ? 0 : Number(clips[index - 1].end)
        clips.push({
          start,
          end: start + shot.duration,
          section_label: `${shot.page_number}.${shot.panel_number}`,
          energy: 0.5,
          suggested_prompt_hint: shot.narrative_role,
          beat_count: 0,
          duration_frames: Math.max(1, Math.round(shot.duration * fps)),
        })
        return clips
      }, [])

      reportActivity('Submitting comic movie to Director…', 'planning')
      const { pipeline_id } = await api.startPipeline({
        pipeline_type: 'comic_movie',
        comic_id: project.id,
        auto_mode: true,
        comic_preflight_only: preflightOnly,
        workspace: state.activeWorkspace,
        scene_description: movieContext,
        comic_shots: comicShots,
        // A storyboard is already a deliberate shot list. Preserve its
        // one-frame/one-shot contract; only printed-comic mode receives the
        // editorial fusion/omission pass.
        comic_adapt_to_film: !storyboard,
        comic_target_shots: targetFilmShots > 0 ? targetFilmShots : undefined,
        provided_clip_image_paths: comicShots.map(shot => shot.image_path),
        video_image_fit: movieImageFit,
        comic_end_frame_mode: movieEndFrameMode,
        // Assembly is deliberately independent from I2V end-frame
        // conditioning. Director joins the completed clips with hard cuts;
        // edit transitions belong to the Video Editor afterwards.
        comic_edit_transition: 'none',
        comic_motion_fidelity: movieFidelity,
        comic_motion_treatment: movieMotionMode,
        planned_clips: plannedClips,
        seamless: false,
        visual_style: [
          project.style.name,
          project.style.promptSuffix,
          project.director?.plan.styleBible || '',
        ].filter(Boolean).join('. '),
        preserve_visual_style: true,
        fps,
        frames_steps: state.modelOptions?.frames_steps || 8,
        frames_minimum: state.modelOptions?.frames_minimum || 41,
        use_director_v2: true,
        llm_model_id: state.servicesConfig?.llm_model_id || state.llmStatus?.model_id,
        llm_device: state.servicesConfig?.llm_device || state.llmStatus?.device,
        llm_provider: state.servicesConfig?.llm_provider || 'local',
        writing_provider: project.director?.input.writingProvider || 'maestro',
        writing_model: project.director?.input.writingModel || '',
        writing_base_url: project.director?.input.writingBaseUrl || '',
        characters: project.characters.map(character => ({
          name: character.name,
          description: character.description,
        })),
        target_duration: totalSeconds,
        narrative_mode: true,
        image_model: state.selectedModelPerMode.image || 'flux2_klein_9b',
        image_params: {
          ...(state.savedParamsPerMode.image || { num_inference_steps: 4, guidance_scale: 1 }),
          resolution: qualityResolution,
        },
        image_loras: state.savedLoraPerMode.image || {},
        video_model: videoModel,
        video_params: {
          ...(state.savedParamsPerMode.video || { num_inference_steps: 8, guidance_scale: 1 }),
          // LTX Distilled is designed around its 8-step first stage plus the
          // model's canonical 3-step second stage. Do not let an old preview
          // preset silently undercut that path for comic films.
          num_inference_steps: videoSteps,
          resolution: qualityResolution,
          ...(isLtxDistilled ? {
            single_stage_pipeline: 0,
            progressive_pipeline: 0,
            stage2_steps: 3,
          } : {}),
          input_video_strength: movieFidelity === 'faithful'
            ? .9
            : Number(state.savedParamsPerMode.video?.input_video_strength ?? .8),
        },
        video_loras: state.savedLoraPerMode.video || {},
        video_spatial_upsampling: state.directorVideoSpatialUpsampling,
        video_film_grain_intensity: state.directorVideoFilmGrainIntensity,
        video_film_grain_saturation: state.directorVideoFilmGrainSaturation,
        video_self_refiner: movieSelfRefiner,
        audio_scale: state.directorAudioScale,
      })

      if (preflightOnly) {
        setPreflightPipelineId(pipeline_id)
        for (;;) {
          await new Promise(resolve => window.setTimeout(resolve, 900))
          const status = await api.fetchPipelineStatus(pipeline_id)
          setPreflightStatus(status)
          reportActivity(
            status.progress?.message || 'Preparing comic video PRE…',
            status.phase,
            status.progress?.current || status.progress?.step || 0,
            status.progress?.total || status.progress?.total_steps || 0,
          )
          if (status.status === 'preview_ready') {
            window.localStorage.setItem(preflightStorageKey, pipeline_id)
            window.localStorage.setItem(
              preflightFingerprintStorageKey,
              preflightFingerprint,
            )
            setPreflightBuiltFingerprint(preflightFingerprint)
            notify(
              'ok',
              `PRE ready for ${status.preview_clips?.length || 0} clips. No video was generated.`,
            )
            window.dispatchEvent(new CustomEvent('maestro:comic-pre-open', {
              detail: { pipelineId: pipeline_id },
            }))
            break
          }
          if (status.status === 'failed' || status.status === 'cancelled') {
            throw new Error(status.error || 'Comic video PRE stopped.')
          }
        }
        return
      }

      state.setGenerationMode('video')
      state.setSidebarMode('director')
      state.setDirectorSkill('short_film')
      state.setMediaFilter('all')
      useStore.setState({
        pipelineId: pipeline_id,
        pipelineStatus: null,
        pipelinePolling: true,
        directorStep: 'plan',
        directorLoading: true,
        directorError: null,
        directorSceneDescription: movieContext,
        directorPlannedClips: plannedClips,
        directorClipPlans: [],
        directorClipImages: [],
        directorAutoMode: true,
        directorSeamless: false,
        shortFilmPath: 'story',
        shortFilmTargetDuration: totalSeconds,
      })
      useStore.getState().setForegroundActivity(null)
      useStore.getState().pollPipelineStatus()
      window.dispatchEvent(new Event('maestro:director-open'))
      notify(
        'ok',
        isTestRun
          ? `${requestedPanelCount}-clip quality test started at ${selectedMovieResolution.value} with the real ${effectiveVideoModelName} settings. The remaining ${panelCount - requestedPanelCount} panels were not submitted.`
          : movieEndFrameMode === 'none'
            ? 'Comic movie started. Panels without an explicit end-frame override are independent I2V shots; completed clips are joined with clean cuts.'
            : 'Comic movie started. End-frame conditioning is enabled for selected shots, but completed clips are still joined with clean cuts.',
      )
    } catch (error) {
      activityFailed = true
      const message = (error as Error).message
      useStore.getState().setForegroundActivity({
        id: activityId,
        status: 'failed',
        phase: 'preparing_comic_video',
        message,
        error: message,
      })
      notify('error', (error as Error).message)
    } finally {
      const foregroundActivity = useStore.getState().foregroundActivity
      if (!activityFailed && foregroundActivity?.id === activityId) {
        useStore.getState().setForegroundActivity(null)
      }
      setBusy(null)
      setProgress('')
    }
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-purple-400/30 bg-purple-400/5 p-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-text-primary">
          <Film size={14} className="text-purple-300" /> Convert {storyboard ? 'storyboard' : 'comic'} to AI film
        </div>
        <p className="mt-1 text-[10px] text-text-muted">
          {storyboard
            ? 'Each approved first frame and its editable I2V prompt go directly to Director. Missing prompts alone are completed by the LLM.'
            : 'Adapt the comic into a film shot list first. Shots can be omitted, reordered or routed to an exact hold, deterministic subtle push, AI living still or model-driven I2V without changing the printed comic.'}
        </p>
      </div>
      <label className="block rounded-lg border border-accent-blue/35 bg-accent-blue/5 p-3 text-[10px] text-text-muted">
        <span className="flex items-center justify-between gap-2">
          <b className="text-xs text-text-primary">Video engine for this movie</b>
          <span className="rounded-full border border-emerald-400/35 bg-emerald-400/10 px-2 py-0.5 text-[9px] text-emerald-200">
            Selected
          </span>
        </span>
        <select
          className={`${input} mt-2`}
          value={effectiveVideoModel}
          disabled={Boolean(busy)}
          onChange={event => selectDirectorVideoModel(event.target.value)}
        >
          {!selectableVideoModels.some(model => model.model_type === effectiveVideoModel) && (
            <option value={effectiveVideoModel}>{effectiveVideoModelName}</option>
          )}
          {selectableVideoModels.map(model => (
            <option key={model.model_type} value={model.model_type}>
              {model.name}{model.is_downloaded === false ? ' · not installed' : ''}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-[9px] text-accent-blue">
          Director will submit <b>{effectiveVideoModelName}</b> · <code>{effectiveVideoModel}</code>
        </span>
        <span className="mt-1 block text-[9px] text-text-primary">
          Current output: <b>{selectedMovieResolution.label}</b>
        </span>
        <span className="mt-1 block text-[9px] text-text-muted">
          {effectiveVideoModel.includes('ltx2')
            ? 'LTX Distilled uses Maestro’s validated two-stage 8+3 recipe.'
            : effectiveVideoModel.includes('minimax')
              ? 'MiniMax is the actual generative engine; “model-driven I2V” below describes a shot method, not a different model.'
              : 'The selected engine is frozen into PRE and shown again before generation.'}
        </span>
      </label>
      <div className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-bg-tertiary/30 p-1">
        <button
          className={`${button} border-0 ${videoTab === 'settings' ? 'bg-accent-blue/15 text-accent-blue' : ''}`}
          onClick={() => setVideoTab('settings')}
        >
          <Settings2 size={12} /> Configuration
        </button>
        <button
          className={`${button} border-0 ${videoTab === 'shots' ? 'bg-purple-400/15 text-purple-300' : ''}`}
          onClick={() => setVideoTab('shots')}
        >
          <Clapperboard size={12} /> Source beats · {includedVideoShots.length}
        </button>
      </div>

      {videoTab === 'settings' && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-[10px] text-text-muted">Movie format
              <select className={`${input} mt-1`} value={aspect} onChange={event => setAspect(event.target.value as ComicMovieAspect)}>
                <option value="landscape">Landscape · TV</option>
                <option value="portrait">Portrait · mobile</option>
                <option value="square">Square</option>
              </select>
            </label>
            <label className="block text-[10px] text-text-muted">Output resolution
              <select className={`${input} mt-1`} value={movieQuality} onChange={event => setMovieQuality(event.target.value as ComicMovieQuality)}>
                {movieResolutionOptions.map(option => (
                  <option key={option.value} value={option.quality}>{option.label}</option>
                ))}
              </select>
              <span className="mt-1 block text-[9px] text-text-muted">
                Exact request: <b className="text-text-primary">{selectedMovieResolution.value.replace('x', '×')}</b>
                {effectiveVideoModel === 'minimax_h3'
                  ? ' · MiniMax H3-compatible, 32-pixel aligned and below its Base canvas limit.'
                  : ' · compatible preset for the selected engine.'}
              </span>
            </label>
          </div>
          <label className="block text-[10px] text-text-muted">Global AI motion direction
            <select className={`${input} mt-1`} value={movieMotionMode} onChange={event => setMovieMotionMode(event.target.value as typeof movieMotionMode)}>
              <option value="contextual">Context-aware performance · fixed camera · recommended</option>
              <option value="living-still">Living still · micro-motion only</option>
              <option value="action">Authored action · prompt and camera</option>
            </select>
          </label>
          <label className="block text-[10px] text-text-muted">Default video framing
            <select className={`${input} mt-1`} value={movieImageFit} onChange={event => setMovieImageFit(event.target.value as typeof movieImageFit)}>
              <option value="cover">Cinematic crop · fill canvas</option>
              <option value="contain">Preserve whole panel · visible padding</option>
            </select>
            <span className="mt-1 block text-[9px] text-text-muted">Contain preserves the whole panel; Cover is an explicit crop. AI reframe import/generation is not available in this build, so it is never offered as a magical fallback.</span>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-[10px] text-text-muted">End frame
              <select className={`${input} mt-1`} value={movieEndFrameMode} onChange={event => setMovieEndFrameMode(event.target.value as typeof movieEndFrameMode)}>
                <option value="none">None · independent shots</option>
                <option value="smart">Compatible continuous actions</option>
                <option value="all">Every following panel · experimental</option>
              </select>
            </label>
            <label className="block text-[10px] text-text-muted">Fidelity
              <select className={`${input} mt-1`} value={movieFidelity} onChange={event => setMovieFidelity(event.target.value as typeof movieFidelity)}>
                <option value="faithful">Faithful · recommended</option>
                <option value="balanced">Balanced</option>
                <option value="expressive">Expressive · drift risk</option>
              </select>
            </label>
          </div>
          <label className="block text-[10px] text-text-muted">Default duration
            <input className={`${input} mt-1`} type="number" min={.8} max={20} step={.1} value={defaultDuration} onChange={event => setDefaultDuration(Number(event.target.value))} />
          </label>
          <label className="block text-[10px] text-text-muted">Target film shots
            <input
              className={`${input} mt-1`}
              type="number"
              min={0}
              max={200}
              step={1}
              value={targetFilmShots}
              onChange={event => setTargetFilmShots(Math.max(
                0,
                Math.min(200, Math.trunc(Number(event.target.value) || 0)),
              ))}
            />
            <span className="mt-1 block text-[9px] text-text-muted">
              {targetFilmShots === 0
                ? `Auto · Director will adapt these ${includedVideoShots.length} source beats into roughly ${Math.max(1, Math.round(includedVideoShots.length * .34))} purposeful film shots.`
                : `${targetFilmShots} film shots requested. PRE shows the actual adapted shot list before any video is generated.`}
            </span>
          </label>
          <label className="block text-[10px] text-text-muted">Experimental self-refiner
            <select className={`${input} mt-1`} value={movieSelfRefiner} onChange={event => setMovieSelfRefiner(Number(event.target.value))}>
              <option value={0}>Off · stable path</option>
              <option value={1}>P1-Norm · experimental</option>
              <option value={2}>P2-Norm · experimental</option>
            </select>
          </label>
          {selectedVideoModel?.includes('gguf') && <div className="rounded border border-amber-400/30 bg-amber-400/5 p-2 text-[10px] text-amber-200">Q6 saves VRAM but was slower and less faithful locally. <button className="underline" onClick={() => selectDirectorVideoModel('ltx2_22B_distilled_1_1')}>Use INT8</button></div>}
          {selectedVideoModel?.includes('fp8') && <div className="rounded border border-amber-400/30 bg-amber-400/5 p-2 text-[10px] text-amber-200">FP8 remains experimental: slower locally with more anatomy and clothing deformation.</div>}
          <details className="rounded border border-border bg-bg-tertiary/30">
            <summary className="cursor-pointer p-2 text-[10px] font-semibold text-text-primary">Video LoRAs · {savedVideoLoras?.activated_loras?.length || 0} active</summary>
            <div className="space-y-2 border-t border-border p-2">
              <p className="text-[9px] text-amber-200">Transition LoRAs are not comic/anime style LoRAs. Use only a LoRA trained for the selected video model and test it in PRE.</p>
              <DirectorLoraSelector mode="video" modelType={selectedVideoModel || 'ltx2_22B_distilled_1_1'} />
            </div>
          </details>
          <details className="border-t border-border pt-3">
            <summary className="cursor-pointer text-xs font-semibold text-text-muted">FFmpeg animatic · no generative video</summary>
            <div className="mt-2 space-y-2 rounded border border-amber-400/25 bg-amber-400/5 p-2">
              <p className="text-[10px] text-amber-100/80">Useful for timing only. Camera movement here is programmatic and does not call the selected video model.</p>
              <select className={input} value={animaticMotion} onChange={event => setAnimaticMotion(event.target.value as typeof animaticMotion)}>
                <option value="none">Static panels · recommended</option>
                <option value="shot-settings">Use programmed pan/zoom settings</option>
              </select>
              <select className={input} value={transition} onChange={event => setTransition(event.target.value)}>
                <option value="none">Hard cuts · recommended</option>
                <option value="crossfade">Crossfade</option>
                <option value="fade-black">Fade through black</option>
                <option value="wipe-left">Wipe left</option>
                <option value="dissolve">Dissolve</option>
              </select>
              <button className={`${button} w-full border-cyan-400/50 text-cyan-300`} disabled={Boolean(busy) || panelCount === 0} onClick={create}>
                {busy === 'animatic' ? <Loader2 size={13} className="animate-spin" /> : <Film size={13} />}
                {busy === 'animatic' && progress ? progress : 'Render animatic'}
              </button>
            </div>
          </details>
          {result && <div className="space-y-2 rounded border border-emerald-500/30 bg-emerald-500/5 p-2"><video src={result.url} controls className="w-full rounded" /><button className={`${button} w-full border-emerald-500/40 text-emerald-300`} onClick={() => useStore.getState().setMediaFilter('videoeditor')}>Open in Video Editor</button></div>}
        </div>
      )}

      {videoTab === 'shots' && project.director && (
        <div className="space-y-3">
          <div className="rounded border border-border bg-bg-tertiary/30 p-2 text-[10px] text-text-muted">
            <div className="flex items-center justify-between gap-2"><span><b className="text-text-primary">{includedVideoShots.length}</b> source beats enabled · {videoShotRows.length - includedVideoShots.length} omitted · {selectedTestShots.length} suggested for test</span><span>Global: <b className="text-accent-blue">{movieMotionMode}</b></span></div>
            <p className="mt-1">These are source comic beats, not the final film-shot count. Director may merge adjacent beats, so these controls are adaptation hints. PRE is the authoritative, editable list of effective film shots and render settings.</p>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <button className={`${button} border-accent-blue/40 text-accent-blue`} onClick={() => updateAllShots({ videoMotion: 'auto' }, `All ${videoShotRows.length} shots now follow the global AI motion direction.`)}>All follow global motion</button>
            <button className={`${button} border-purple-400/40 text-purple-200`} onClick={() => updateAllShots({
              videoIncluded: undefined,
              videoOrder: undefined,
              videoRenderer: undefined,
              videoFit: undefined,
              videoMotion: 'auto',
              videoMotionLevel: undefined,
              durationSeconds: undefined,
              cameraMove: undefined,
              videoEndFrame: undefined,
              videoSeed: undefined,
              videoTestSelected: undefined,
              videoOverrideFields: [],
            }, `Released every manual adaptation lock on ${videoShotRows.length} source beats.`)}>Release all manual locks</button>
            <button className={button} onClick={() => updateAllShots({ videoIncluded: true }, 'All film shots enabled.')}>Include all</button>
            <button
              className={button}
              onClick={() => updateAllShots(
                { durationSeconds: defaultDuration },
                `Applied ${defaultDuration}s as a source timing hint. Set the exact final-shot duration in PRE.`,
                { add: [], remove: ['duration'] },
              )}
            >
              Use {defaultDuration}s timing hint
            </button>
            <button className={`${button} border-cyan-400/40 text-cyan-300`} onClick={selectRepresentativeTests}><Sparkles size={12} /> Select representative test</button>
          </div>
          <div className="space-y-2">
            {videoShotRows.map((row, rowIndex) => {
              const { planned, pageIndex, panelIndex } = row
              const renderer = resolvedRenderer(planned)
              const rendererLabel = renderer || 'auto'
              const motion = resolvedMotionMode(planned)
              const overrides = new Set(planned.videoOverrideFields || [])
              return (
                <details key={planned.id} open={rowIndex < 2} className={`rounded-lg border ${planned.videoIncluded === false ? 'border-border opacity-60' : 'border-purple-400/25'} bg-bg-tertiary/20`}>
                  <summary className="cursor-pointer p-2 text-[10px] text-text-primary">
                    <span className="font-semibold">{rowIndex + 1}. Source {pageIndex + 1}.{panelIndex + 1}</span>
                    <span className="ml-1 text-text-muted">· {planned.narrativeRole}</span>
                    <span className="ml-2 rounded bg-bg-secondary px-1 py-0.5 text-[9px] text-purple-200">{motionMethodLabel(rendererLabel)}</span>
                    <span className="ml-1 rounded bg-bg-secondary px-1 py-0.5 text-[9px] text-amber-200">fit {resolvedFit(planned)}</span>
                    {overrides.size > 0 && <span className="ml-1 rounded bg-bg-secondary px-1 py-0.5 text-[9px] text-emerald-200">{overrides.size} manual lock{overrides.size === 1 ? '' : 's'}</span>}
                    {(!renderer || renderer === 'ltx') && <span className="ml-1 rounded bg-bg-secondary px-1 py-0.5 text-[9px] text-cyan-200">{overrides.has('motion_mode') ? `${motion} override` : `${motion} global`}</span>}
                  </summary>
                  <div className="space-y-2 border-t border-border p-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <label className="flex items-center gap-1 text-[9px] text-text-muted"><input type="checkbox" checked={planned.videoIncluded !== false} onChange={event => updateShot(pageIndex, panelIndex, { videoIncluded: event.target.checked })} /> Include</label>
                      <label className="flex items-center gap-1 text-[9px] text-text-muted"><input type="checkbox" checked={Boolean(planned.videoTestSelected)} disabled={planned.videoIncluded === false} onChange={event => updateShot(pageIndex, panelIndex, { videoTestSelected: event.target.checked })} /> Suggest for PRE test</label>
                      <span className="ml-auto flex gap-1"><button className={button} disabled={rowIndex === 0} onClick={() => moveShot(rowIndex, -1)} title="Move earlier"><ArrowUp size={12} /></button><button className={button} disabled={rowIndex === videoShotRows.length - 1} onClick={() => moveShot(rowIndex, 1)} title="Move later"><ArrowDown size={12} /></button></span>
                    </div>
                    <label className="block text-[9px] text-text-muted">Action hint after the first frame
                      <textarea className={`${input} mt-1`} rows={2} value={planned.videoAction || ''} onChange={event => updateShot(pageIndex, panelIndex, { videoAction: event.target.value })} placeholder="One clear chronological performance or environmental action…" />
                    </label>
                    <label className="block text-[9px] text-text-muted">I2V prompt hint
                      <textarea className={`${input} mt-1`} rows={4} value={planned.videoPrompt || ''} onChange={event => updateShot(pageIndex, panelIndex, { videoPrompt: event.target.value })} placeholder="Describe only what changes: action, restrained movement, camera and final beat…" />
                    </label>
                    <div className="grid grid-cols-2 gap-1.5">
                      <label className="text-[9px] text-text-muted">Motion method hint
                        <select
                          className={`${input} mt-1`}
                          value={rendererLabel}
                          onChange={event => {
                            const nextRenderer = event.target.value
                            const deterministic = nextRenderer === 'hold'
                              || nextRenderer === 'parallax'
                              || nextRenderer === 'cinemagraph'
                            updateShot(pageIndex, panelIndex, {
                              videoRenderer: nextRenderer === 'auto'
                                ? undefined
                                : nextRenderer as ComicPlanPanel['videoRenderer'],
                              ...(deterministic ? {
                                videoMotion: 'auto' as const,
                                videoMotionLevel: undefined,
                                cameraMove: undefined,
                              } : {}),
                            }, nextRenderer === 'auto'
                              ? { add: [], remove: ['renderer'] }
                              : {
                                add: ['renderer'],
                                remove: deterministic
                                  ? ['motion_mode', 'motion_level', 'camera']
                                  : [],
                              })
                          }}
                        >
                          <option value="auto">Auto · Director chooses for this beat</option>
                          <option value="hold">Hold · exact still</option>
                          <option value="parallax">Subtle centered push · deterministic</option>
                          <option value="cinemagraph">AI living still · subtle full-frame I2V</option>
                          <option value="ltx">Model-driven I2V · performance/action</option>
                        </select>
                      </label>
                      <label className="text-[9px] text-text-muted">Frame-fit hint
                        <select className={`${input} mt-1`} value={planned.videoFit || 'auto'} onChange={event => updateShot(pageIndex, panelIndex, { videoFit: event.target.value === 'auto' ? undefined : event.target.value as ComicPlanPanel['videoFit'] })}>
                          <option value="auto">Follow global · {movieImageFit}</option>
                          {planned.videoFit === 'reframe' && <option value="reframe" disabled>Legacy AI reframe request · change to Contain/Cover</option>}
                          <option value="cover">Cinematic crop</option>
                          <option value="contain">Whole panel + padding</option>
                        </select>
                      </label>
                      <label className="text-[9px] text-text-muted">Preferred duration
                        <input className={`${input} mt-1`} type="number" min={.8} max={20} step={.1} value={planned.durationSeconds || defaultDuration} onChange={event => updateShot(pageIndex, panelIndex, { durationSeconds: Number(event.target.value) })} />
                      </label>
                      <label className="text-[9px] text-text-muted">Motion hint · {motionLevelLabel(planned.videoMotionLevel ?? (renderer === 'hold' ? 0 : 1))}
                        <input className="mt-2 w-full" type="range" min={0} max={3} step={1} disabled={renderer === 'hold' || renderer === 'parallax' || renderer === 'cinemagraph'} value={planned.videoMotionLevel ?? (renderer === 'hold' ? 0 : 1)} onChange={event => updateShot(pageIndex, panelIndex, { videoMotionLevel: Number(event.target.value) as ComicPlanPanel['videoMotionLevel'] })} />
                      </label>
                      <label className="text-[9px] text-text-muted">Camera hint
                        <select className={`${input} mt-1`} value={planned.cameraMove || 'none'} disabled={renderer !== 'ltx'} onChange={event => updateShot(pageIndex, panelIndex, { cameraMove: event.target.value as ComicPlanPanel['cameraMove'] })}>
                          <option value="none">Locked / no requested move</option>
                          <option value="push-in">Push-in</option>
                          <option value="pull-out">Pull-out</option>
                          <option value="pan-left">Pan left</option>
                          <option value="pan-right">Pan right</option>
                        </select>
                      </label>
                      <label className="text-[9px] text-text-muted">AI motion direction hint
                        <select className={`${input} mt-1`} value={planned.videoMotion || 'auto'} disabled={renderer !== 'ltx'} onChange={event => updateShot(pageIndex, panelIndex, { videoMotion: event.target.value as ComicPlanPanel['videoMotion'] })}>
                          <option value="auto">Follow global · {movieMotionMode}</option>
                          <option value="contextual">Context-aware</option>
                          <option value="living-still">Living still</option>
                          <option value="action">Authored prompt</option>
                        </select>
                      </label>
                      <label className="text-[9px] text-text-muted">Seed
                        <input className={`${input} mt-1`} type="number" value={planned.videoSeed ?? ''} placeholder="Stable auto seed" onChange={event => updateShot(pageIndex, panelIndex, { videoSeed: event.target.value === '' ? undefined : Math.trunc(Number(event.target.value)) })} />
                      </label>
                      <label className="text-[9px] text-text-muted">End-frame hint
                        <select className={`${input} mt-1`} value={planned.videoEndFrame || 'auto'} onChange={event => updateShot(pageIndex, panelIndex, { videoEndFrame: event.target.value as ComicPlanPanel['videoEndFrame'] })}>
                          <option value="auto">Follow global</option>
                          <option value="none">None</option>
                          <option value="next-panel">Use next compatible panel</option>
                        </select>
                      </label>
                    </div>
                  </div>
                </details>
              )
            })}
          </div>
        </div>
      )}

      <div className="space-y-2 border-t border-border pt-3">
        <button className={`${button} w-full border-red-400/60 bg-red-400/5 text-red-200`} disabled={Boolean(busy) || includedVideoShots.length === 0} onClick={() => convertToMovie(undefined, true)}>
          {busy === 'preflight' ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} />}
          {busy === 'preflight' && progress ? progress : `Prepare PRE for ${includedVideoShots.length} enabled film shots`}
        </button>
        <p className="text-[9px] text-red-200/80">PRE opens as its own full comic workspace tab. It shows the exact source, prepared frame, prompt, motion method, seed and video-model parameters before any generation.</p>
        <p className="text-[9px] text-accent-blue">Current engine: <b>{effectiveVideoModelName}</b> · <code>{effectiveVideoModel}</code></p>
        {preflightStatus?.status === 'preview_ready' && (
          <button className={`${button} w-full ${preflightIsStale ? 'border-amber-400/50 text-amber-200' : 'border-emerald-400/50 text-emerald-300'}`} onClick={() => window.dispatchEvent(new CustomEvent('maestro:comic-pre-open', { detail: { pipelineId: preflightPipelineId } }))}>
            {preflightIsStale ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}
            {preflightIsStale ? 'Open stale PRE · rebuild before approval' : `Open prepared PRE · ${preflightStatus.preview_clips?.length || 0} shots · ${preflightStatus.preview_clips?.[0]?.video_model || effectiveVideoModel}`}
          </button>
        )}
        {preflightStatus?.status === 'failed' && <div className="rounded border border-red-500/40 bg-red-500/10 p-2 text-[10px] text-red-200">{preflightStatus.error || 'Comic video PRE failed.'}</div>}
      </div>
    </div>
  )
}

type PreviewDraft = api.PipelinePreviewClip & {
  included: boolean
  order: number
  renderer: 'hold' | 'parallax' | 'cinemagraph' | 'ltx'
  fit_mode: 'reframe' | 'cover' | 'contain'
  test_selected: boolean
  camera_move: string
  prompt_override_update?: boolean
}

type StoredPreviewRecovery = {
  fingerprint?: string
  drafts?: api.PipelinePreviewClip[]
  dirty?: boolean
  waiverReason?: string
  reviewedTestIndices?: number[]
}

const previewRatio = (value: string): number => {
  const [width, height] = String(value || '').split('x').map(Number)
  return width > 0 && height > 0 ? width / height : 16 / 9
}

const normalizePreviewDrafts = (clips: api.PipelinePreviewClip[]): PreviewDraft[] =>
  clips.map((clip, position) => {
    const renderer = ['hold', 'parallax', 'cinemagraph', 'ltx'].includes(String(clip.renderer))
      ? clip.renderer as PreviewDraft['renderer']
      : 'ltx'
    const index = Number.isFinite(Number(clip.index)) ? Number(clip.index) : position
    return {
      ...clip,
      index,
      label: String(clip.label || `Shot ${index + 1}`),
      image_filename: String(clip.image_filename || ''),
      end_image_filename: String(clip.end_image_filename || ''),
      source_resolution: String(clip.source_resolution || clip.input_resolution || ''),
      input_resolution: String(clip.input_resolution || clip.output_resolution || ''),
      output_resolution: String(clip.output_resolution || clip.input_resolution || ''),
      prompt: String(clip.prompt || clip.base_prompt || ''),
      base_prompt: clip.base_prompt === undefined ? undefined : String(clip.base_prompt || ''),
      negative_prompt: String(clip.negative_prompt || ''),
      dialogue: String(clip.dialogue || ''),
      included: clip.included !== false,
      order: Number.isFinite(Number(clip.order)) ? Number(clip.order) : position,
      renderer,
      fit_mode: ['reframe', 'cover', 'contain'].includes(String(clip.fit_mode))
        ? clip.fit_mode as PreviewDraft['fit_mode']
        : clip.fit_mode === 'crop'
          ? 'cover'
          : 'contain',
      duration_seconds: Number.isFinite(Number(clip.duration_seconds))
        ? Math.max(.8, Math.min(20, Number(clip.duration_seconds)))
        : 3,
      motion_level: Number.isFinite(Number(clip.motion_level))
        ? Math.max(0, Math.min(3, Number(clip.motion_level)))
        : renderer === 'hold' ? 0 : 1,
      seed: Number.isFinite(Number(clip.seed)) ? Math.trunc(Number(clip.seed)) : -1,
      test_selected: Boolean(clip.test_selected),
      camera_move: String(clip.camera_move || (clip.camera_locked ? 'none' : 'authored')),
      activated_loras: Array.isArray(clip.activated_loras) ? clip.activated_loras : [],
      source_panel_ids: Array.isArray(clip.source_panel_ids)
        ? clip.source_panel_ids.map(value => String(value)).filter(Boolean)
        : [],
      risk_tags: Array.isArray(clip.risk_tags)
        ? clip.risk_tags.map(value => String(value)).filter(Boolean)
        : [],
      prompt_override_update: typeof (clip as PreviewDraft).prompt_override_update === 'boolean'
        ? (clip as PreviewDraft).prompt_override_update
        : undefined,
    }
  }).sort((left, right) => left.order - right.order || left.index - right.index)

export function ComicVideoPreflightPanel({
  notify,
  onDirtyChange,
}: {
  notify: (kind: 'ok' | 'error', text: string) => void
  onDirtyChange?: (dirty: boolean) => void
}) {
  const project = useComicStore(state => state.project)
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const selectedVideoModel = useStore(state => state.selectedModelPerMode.video)
  const savedVideoLoras = useStore(state => state.savedLoraPerMode.video)
  const savedVideoParams = useStore(state => state.savedParamsPerMode.video)
  const movieSpatialUpsampling = useStore(state => state.directorVideoSpatialUpsampling)
  const movieFilmGrainIntensity = useStore(state => state.directorVideoFilmGrainIntensity)
  const movieFilmGrainSaturation = useStore(state => state.directorVideoFilmGrainSaturation)
  const movieSelfRefiner = useStore(state => state.directorVideoSelfRefiner)
  const movieAudioScale = useStore(state => state.directorAudioScale)
  const [pipelineId, setPipelineId] = useState<string | null>(null)
  const [status, setStatus] = useState<api.PipelineStatus | null>(null)
  const [drafts, setDrafts] = useState<PreviewDraft[]>([])
  const [loading, setLoading] = useState(true)
  const [dirty, setDirty] = useState(false)
  const dirtyRef = useRef(false)
  const [waiverReason, setWaiverReason] = useState('')
  const [bulkDuration, setBulkDuration] = useState(3)
  const [reviewedTestIndices, setReviewedTestIndices] = useState<number[]>([])
  const [busy, setBusy] = useState<'save' | 'approve' | 'accept' | 'test' | 'all' | number | null>(null)
  const storageKey = `maestro-comic-preflight:${activeWorkspace}:${project.id}`
  const hasUnsavedLocalChanges = dirty
    || waiverReason !== (status?.quality_gate?.waiver_reason || '')
    || (status?.quality_gate?.status === 'review_required' && reviewedTestIndices.length > 0)
  const frontendSourceStale = (() => {
    const builtValue = window.localStorage.getItem(`${storageKey}:fingerprint`)
    // The backend fingerprint freezes the PRE itself; this companion signature
    // proves that it was built from the comic/config currently open in the UI.
    // Without both pieces of evidence a recovered PRE remains view-only.
    if (!builtValue) return true
    try {
      const built = JSON.parse(builtValue) as Record<string, unknown>
      const saved = readComicVideoSettings(activeWorkspace, project.id)
      const savedAspect = (
        saved.aspect || project.director?.input.storyboardAspect || 'landscape'
      ) as ComicMovieAspect
      const savedQuality = saved.quality || '720p'
      const currentVideoModel = selectedVideoModel || 'ltx2_22B_distilled_1_1'
      const currentResolutionOptions = comicMovieResolutions(currentVideoModel, savedAspect)
      const currentResolution = currentResolutionOptions.find(
        option => option.quality === savedQuality,
      ) || currentResolutionOptions.find(option => option.recommended) || currentResolutionOptions[0]
      return built.comicId !== project.id
        || built.updatedAt !== project.updatedAt
        || built.aspect !== savedAspect
        || Number(built.defaultDuration || 3) !== Number(saved.defaultDuration || 3)
        || built.movieQuality !== savedQuality
        || built.movieResolution !== currentResolution.value
        || built.movieMotionMode !== (
          saved.motionMode
          || (project.director?.input.productionMode === 'storyboard' ? 'action' : 'contextual')
        )
        || built.movieImageFit !== (saved.imageFit || 'contain')
        || built.movieEndFrameMode !== (saved.endFrameMode || 'none')
        || built.movieFidelity !== (saved.fidelity || 'faithful')
        || Number(built.targetFilmShots || 0) !== Number(saved.targetFilmShots || 0)
        || built.movieSelfRefiner !== movieSelfRefiner
        || built.selectedVideoModel !== currentVideoModel
        || JSON.stringify(built.savedVideoLoras || {}) !== JSON.stringify(savedVideoLoras || {})
        || JSON.stringify(built.videoRuntime || {}) !== JSON.stringify({
          savedVideoParams,
          spatialUpsampling: movieSpatialUpsampling,
          filmGrainIntensity: movieFilmGrainIntensity,
          filmGrainSaturation: movieFilmGrainSaturation,
          audioScale: movieAudioScale,
        })
    } catch {
      return true
    }
  })()

  useEffect(() => {
    dirtyRef.current = hasUnsavedLocalChanges
    onDirtyChange?.(hasUnsavedLocalChanges)
  }, [hasUnsavedLocalChanges, onDirtyChange])

  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange])

  useEffect(() => {
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedLocalChanges) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeLeaving)
    return () => window.removeEventListener('beforeunload', warnBeforeLeaving)
  }, [hasUnsavedLocalChanges])

  useEffect(() => {
    const fingerprint = status?.preview_fingerprint || ''
    if (loading || !pipelineId || !fingerprint) return
    const recoveryKey = `${storageKey}:unsaved:${pipelineId}:${fingerprint}`
    try {
      if (hasUnsavedLocalChanges) {
        window.localStorage.setItem(recoveryKey, JSON.stringify({
          fingerprint,
          drafts,
          dirty,
          waiverReason,
          reviewedTestIndices,
          savedAt: new Date().toISOString(),
        }))
      } else {
        window.localStorage.removeItem(recoveryKey)
      }
    } catch {
      // Durable server PRE remains available if browser storage is disabled.
    }
  }, [
    dirty,
    drafts,
    hasUnsavedLocalChanges,
    loading,
    pipelineId,
    reviewedTestIndices,
    status?.preview_fingerprint,
    storageKey,
    waiverReason,
  ])

  const loadPreview = async (requestedId?: string | null) => {
    setLoading(true)
    try {
      const candidates: string[] = []
      if (requestedId) candidates.push(requestedId)
      const remembered = window.localStorage.getItem(storageKey)
      if (remembered && !candidates.includes(remembered)) candidates.push(remembered)
      try {
        const listed = await api.fetchPipelineList()
        listed.pipelines
          .filter(item =>
            item.pipeline_type === 'comic_movie'
            && item.status === 'preview_ready'
            && item.comic_id === project.id)
          .forEach(item => {
            if (!candidates.includes(item.id)) candidates.push(item.id)
          })
      } catch {
        // The durable ID remains enough when list recovery is temporarily unavailable.
      }
      for (const candidate of candidates) {
        try {
          const recovered = await api.fetchPipelineStatus(candidate)
          if (recovered.status !== 'preview_ready') continue
          const serverDrafts = normalizePreviewDrafts(recovered.preview_clips || [])
          const fingerprint = recovered.preview_fingerprint || ''
          let localRecovery: StoredPreviewRecovery | null = null
          if (fingerprint) {
            try {
              localRecovery = JSON.parse(
                window.localStorage.getItem(
                  `${storageKey}:unsaved:${candidate}:${fingerprint}`,
                ) || 'null',
              ) as StoredPreviewRecovery | null
            } catch {
              localRecovery = null
            }
          }
          const canRestore = localRecovery?.fingerprint === fingerprint
            && Array.isArray(localRecovery?.drafts)
          setPipelineId(candidate)
          setStatus(recovered)
          setDrafts(canRestore
            ? normalizePreviewDrafts(localRecovery!.drafts!)
            : serverDrafts)
          setDirty(canRestore && Boolean(localRecovery?.dirty))
          setWaiverReason(canRestore
            ? String(localRecovery?.waiverReason
              ?? recovered.quality_gate?.waiver_reason
              ?? '')
            : recovered.quality_gate?.waiver_reason || '')
          setReviewedTestIndices(canRestore
            ? (localRecovery?.reviewedTestIndices || [])
              .filter(value => Number.isInteger(value))
            : [])
          window.localStorage.setItem(storageKey, candidate)
          if (canRestore) {
            notify('ok', 'Recovered unsaved PRE edits from this browser for the exact same fingerprint.')
          }
          return
        } catch {
          // Try the next durable PRE.
        }
      }
      setPipelineId(null)
      setStatus(null)
      setDrafts([])
      setDirty(false)
      setWaiverReason('')
      setReviewedTestIndices([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadPreview()
    const open = (event: Event) => {
      const detail = (event as CustomEvent<{ pipelineId?: string }>).detail
      if (dirtyRef.current && !window.confirm(
        'Discard unsaved PRE edits and open the requested prepared shot list?',
      )) return
      if (dirtyRef.current) {
        const currentPipelineId = window.localStorage.getItem(storageKey)
        const prefix = currentPipelineId
          ? `${storageKey}:unsaved:${currentPipelineId}:`
          : ''
        if (prefix) {
          const keys = Array.from(
            { length: window.localStorage.length },
            (_, index) => window.localStorage.key(index),
          ).filter((key): key is string => Boolean(key?.startsWith(prefix)))
          keys.forEach(key => window.localStorage.removeItem(key))
        }
      }
      void loadPreview(detail?.pipelineId)
    }
    window.addEventListener('maestro:comic-pre-open', open)
    return () => window.removeEventListener('maestro:comic-pre-open', open)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspace, project.id, storageKey])

  const patchDraft = (index: number, patch: Partial<PreviewDraft>) => {
    if (frontendSourceStale) {
      notify('error', 'This recovered PRE is view-only. Rebuild it from the current comic before editing.')
      return
    }
    setDrafts(current => current.map(clip => clip.index === index ? { ...clip, ...patch } : clip))
    setDirty(true)
  }
  const moveDraft = (position: number, direction: -1 | 1) => {
    if (frontendSourceStale) {
      notify('error', 'This recovered PRE is view-only. Rebuild it from the current comic before reordering.')
      return
    }
    const destination = position + direction
    if (destination < 0 || destination >= drafts.length) return
    setDrafts(current => {
      const next = [...current]
      ;[next[position], next[destination]] = [next[destination], next[position]]
      return next.map((clip, order) => ({ ...clip, order }))
    })
    setDirty(true)
  }
  const updatePayload = (
    values = drafts,
  ): api.PipelinePreviewClipUpdate[] => values.map((clip, order) => ({
    index: clip.index,
    included: clip.included,
    order,
    renderer: clip.renderer,
    motion_level: Math.max(0, Math.min(3, Number(clip.motion_level) || 0)),
    fit_mode: clip.fit_mode,
    duration_seconds: Math.max(.8, Math.min(20, Number(clip.duration_seconds) || 3)),
    camera_move: clip.camera_move || 'none',
    seed: Number.isFinite(Number(clip.seed)) ? Math.trunc(Number(clip.seed)) : -1,
    test_selected: clip.test_selected,
    // Approval is evidence-based: the browser never claims that an AI reframe
    // exists unless the frozen PRE already points to a real prepared keyframe.
    reframe_approved: Boolean(
      clip.reframe_approved && clip.used_prepared_keyframe,
    ),
    ...(typeof clip.prompt_override_update === 'boolean'
      ? {
        prompt_override: clip.prompt_override_update,
        ...(clip.prompt_override_update ? { prompt: clip.prompt } : {}),
      }
      : {}),
  }))
  const save = async ({
    approvePreview = false,
    qualityWaiver = false,
  }: {
    approvePreview?: boolean
    qualityWaiver?: boolean
  } = {}) => {
    if (!pipelineId) return false
    if (frontendSourceStale) {
      notify('error', 'The comic or film configuration changed after this PRE was built. Return to Video and rebuild it.')
      return false
    }
    const expectedFingerprint = status?.preview_fingerprint || ''
    if (!expectedFingerprint) {
      notify('error', 'This legacy PRE has no backend fingerprint. Rebuild it from Video before editing or generating.')
      return false
    }
    const unresolved = drafts.filter(clip =>
      clip.included
      && clip.needs_reframe
      && !(clip.reframe_approved && clip.used_prepared_keyframe))
    if (approvePreview && unresolved.length) {
      notify(
        'error',
        `${unresolved.length} enabled shot${unresolved.length === 1 ? '' : 's'} requested AI reframe but has no real prepared keyframe. Reframe import/generation is not available yet; change each to Contain/Cover and save.`,
      )
      return false
    }
    const normalizedWaiverReason = waiverReason.trim()
    if (qualityWaiver && !normalizedWaiverReason) {
      notify('error', 'Explain why the representative quality test is being waived. The reason is stored with the PRE.')
      return false
    }
    if (qualityWaiver && !status?.preview_approved) {
      notify('error', 'Approve this exact PRE first; only an approved fingerprint can receive a quality-test waiver.')
      return false
    }
    if (qualityWaiver && !window.confirm(
      'Waive the representative quality test for this exact PRE fingerprint? '
      + 'This is an auditable exception, not a successful quality test.',
    )) return false
    setBusy(approvePreview || qualityWaiver ? 'approve' : 'save')
    try {
      await api.updatePipelinePreview(
        pipelineId,
        approvePreview || qualityWaiver ? [] : updatePayload(drafts),
        {
          expectedFingerprint,
          approvePreview,
          qualityWaiver,
          waiverReason: normalizedWaiverReason,
        },
      )
      try {
        window.localStorage.removeItem(
          `${storageKey}:unsaved:${pipelineId}:${expectedFingerprint}`,
        )
      } catch {
        // Server save already succeeded; browser recovery is best-effort.
      }
      const refreshed = await api.fetchPipelineStatus(pipelineId)
      const refreshedDrafts = normalizePreviewDrafts(refreshed.preview_clips || [])
      setStatus(refreshed)
      setDrafts(refreshedDrafts)
      setDirty(false)
      setReviewedTestIndices([])
      setWaiverReason(refreshed.quality_gate?.waiver_reason || normalizedWaiverReason)
      const refreshedBlocking = refreshedDrafts.filter(clip =>
        clip.included
        && clip.needs_reframe
        && !(clip.reframe_approved && clip.used_prepared_keyframe))
      if (approvePreview && !refreshed.preview_approved) {
        notify('error', refreshedBlocking.length
          ? 'PRE was saved but not approved: at least one requested AI reframe still lacks a real prepared keyframe.'
          : 'PRE was saved but the backend did not approve this fingerprint. Reload it before generating.')
        return false
      }
      const gate = refreshed.quality_gate
      const gateReady = Boolean(
        gate
        && gate.fingerprint === refreshed.preview_fingerprint
        && (gate.status === 'passed' || gate.status === 'waived'),
      )
      if (qualityWaiver && !gateReady) {
        notify('error', 'The backend did not accept the quality waiver for this PRE fingerprint.')
        return false
      }
      let message = 'PRE changes saved and prepared inputs rebuilt. Approval and earlier quality tests were invalidated.'
      if (qualityWaiver) {
        message = 'Quality test waived with an auditable reason. Full generation is unlocked for this approved PRE.'
      } else if (approvePreview) {
        message = gateReady
          ? `PRE approved; quality gate ${gate?.status}. Full generation is unlocked for this exact fingerprint.`
          : 'PRE approved. Run the selected representative clips and pass the quality gate before full generation.'
      }
      notify('ok', message)
      return true
    } catch (error) {
      notify('error', (error as Error).message)
      return false
    } finally {
      setBusy(null)
    }
  }

  const acceptTestedClips = async () => {
    if (!pipelineId || !status?.preview_fingerprint) return
    if (frontendSourceStale || dirty || !status.preview_approved) {
      notify('error', 'Only the current saved and approved PRE can accept a representative quality test.')
      return
    }
    if (status.quality_gate?.status !== 'review_required') {
      notify('error', 'The complete required test set is not ready for review yet. Reload after the test jobs finish.')
      return
    }
    const missingReviews = (status.quality_gate.required_test_indices || [])
      .filter(index => !reviewedTestIndices.includes(index))
    if (missingReviews.length) {
      notify('error', `Review and confirm the test video for shot${missingReviews.length === 1 ? '' : 's'} ${missingReviews.map(index => index + 1).join(', ')} first.`)
      return
    }
    const testedCount = status.quality_gate.tested_indices?.length || 0
    if (!window.confirm(
      `Accept the ${testedCount} completed representative clip`
      + `${testedCount === 1 ? '' : 's'} for this exact PRE fingerprint?`,
    )) return
    setBusy('accept')
    try {
      await api.updatePipelinePreview(pipelineId, [], {
        expectedFingerprint: status.preview_fingerprint,
        acceptQualityTest: true,
      })
      const refreshed = await api.fetchPipelineStatus(pipelineId)
      setStatus(refreshed)
      if (refreshed.quality_gate?.status !== 'passed') {
        throw new Error(
          refreshed.quality_gate?.failures?.join(' · ')
          || 'The backend did not pass the quality gate for this fingerprint.',
        )
      }
      notify('ok', 'Representative clips accepted. Full generation is now unlocked for this exact approved PRE.')
    } catch (error) {
      notify('error', (error as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const sourceImageFor = (clip: PreviewDraft): string => {
    if (clip.source_image_filename) return api.getFileUrl(clip.source_image_filename)
    const page = project.pages[Math.max(0, Number(clip.page_number || 1) - 1)]
    const panels = page?.elements.filter(element => element.type === 'panel' && !element.parentId) || []
    const panel = panels[Math.max(0, Number(clip.panel_number || 1) - 1)]
    const image = page?.elements.find(element =>
      element.type === 'image' && panel && element.parentId === panel.id)
    if (image?.type === 'image') {
      const asset = project.assets[image.assetId]
      return asset?.source || asset?.thumbnail || ''
    }
    return ''
  }
  const aspectRisk = (clip: PreviewDraft) =>
    Math.abs(Math.log(
      Math.max(.01, previewRatio(clip.source_resolution))
      / Math.max(.01, previewRatio(clip.output_resolution)),
    )) > .38
  const enabledDrafts = drafts.filter(clip => clip.included)
  const selectedDrafts = enabledDrafts.filter(clip => clip.test_selected)
  const preparedVideoModels = [...new Set(
    drafts.map(clip => clip.video_model).filter(Boolean),
  )]
  const unresolvedRisks = enabledDrafts.filter(clip =>
    clip.needs_reframe
    && !(clip.reframe_approved && clip.used_prepared_keyframe))
  const previewFingerprint = status?.preview_fingerprint || ''
  const qualityGate = status?.quality_gate
  const qualityTestedIndices = qualityGate?.tested_indices || []
  const qualityRequiredIndices = qualityGate?.required_test_indices || selectedDrafts.map(clip => clip.index)
  const qualityResults = qualityGate?.results || {}
  const pendingVisualReviews = qualityRequiredIndices.filter(index =>
    !reviewedTestIndices.includes(index))
  const qualityGateReady = Boolean(
    qualityGate
    && qualityGate.fingerprint === previewFingerprint
    && (qualityGate.status === 'passed' || qualityGate.status === 'waived'),
  )
  const previewApproved = Boolean(status?.preview_approved && previewFingerprint)
  const fullGenerationUnlocked = Boolean(
    !dirty
    && previewApproved
    && qualityGateReady
    && !unresolvedRisks.length
    && !frontendSourceStale,
  )
  const selectRepresentativePreviewTests = () => {
    if (frontendSourceStale) {
      notify('error', 'This recovered PRE is view-only. Rebuild it before changing the test selection.')
      return
    }
    const candidates = drafts.filter(clip => clip.included)
    const selected = new Set<number>()
    const take = (predicate: (clip: PreviewDraft) => boolean) => {
      const clip = candidates.find(item => !selected.has(item.index) && predicate(item))
      if (clip) selected.add(clip.index)
    }
    take(clip => aspectRisk(clip) || Boolean(clip.needs_reframe))
    take(clip => clip.renderer === 'ltx' && (clip.motion_level || 0) >= 2)
    take(clip => clip.renderer === 'cinemagraph' || clip.renderer === 'parallax')
    take(clip => (clip.source_panel_ids?.length || 0) > 1)
    take(clip => clip.renderer === 'hold')
    candidates.forEach(clip => {
      if (selected.size < Math.min(5, candidates.length)) selected.add(clip.index)
    })
    setDrafts(current => current.map(clip => ({
      ...clip,
      test_selected: selected.has(clip.index),
    })))
    setDirty(true)
    notify('ok', `Selected ${selected.size} representative PRE shots by aspect risk, motion method and motion level.`)
  }
  const applyDurationToPreparedShots = () => {
    if (frontendSourceStale) {
      notify('error', 'This recovered PRE is view-only. Rebuild it before changing shot durations.')
      return
    }
    const duration = Math.max(.8, Math.min(20, Number(bulkDuration) || 3))
    setBulkDuration(duration)
    setDrafts(current => current.map(clip => (
      clip.included ? { ...clip, duration_seconds: duration } : clip
    )))
    setDirty(true)
    notify('ok', `Applied ${duration}s to every enabled final PRE shot. Save to freeze the new timing.`)
  }

  const handOffGeneration = (
    started: { pipeline_id: string; reused?: boolean },
    clips: PreviewDraft[],
  ) => {
    const plannedClips = clips.reduce<PlannedClip[]>((items, clip, index) => {
      const start = index === 0 ? 0 : Number(items[index - 1].end)
      items.push({
        start,
        end: start + clip.duration_seconds,
        section_label: clip.page_number && clip.panel_number
          ? `${clip.page_number}.${clip.panel_number}`
          : clip.label,
        energy: .5,
        suggested_prompt_hint: clip.label,
        beat_count: 0,
        duration_frames: clip.frames,
      })
      return items
    }, [])
    const state = useStore.getState()
    state.setGenerationMode('video')
    state.setSidebarMode('director')
    state.setDirectorSkill('short_film')
    state.setMediaFilter('all')
    useStore.setState({
      pipelineId: started.pipeline_id,
      pipelineStatus: null,
      pipelinePolling: true,
      directorStep: 'review_video',
      directorLoading: true,
      directorError: null,
      directorSceneDescription: `${project.title}\n\n${project.synopsis}`,
      directorPlannedClips: plannedClips,
      directorClipPlans: clips.map(clip => ({ video_prompt: clip.prompt, image_prompt: '' })),
      directorClipImages: clips.map((clip, index) => ({
        clipIndex: index,
        prompt: '',
        file: null as unknown as File,
        filename: clip.image_filename,
      })),
      directorAutoMode: true,
      directorSeamless: false,
      shortFilmPath: 'story',
      shortFilmTargetDuration: Math.round(
        clips.reduce((total, clip) => total + clip.duration_seconds, 0),
      ),
    })
    useStore.getState().pollPipelineStatus()
    window.dispatchEvent(new Event('maestro:director-open'))
  }
  const generate = async (mode: 'all' | 'test' | number) => {
    if (!pipelineId || dirty) return
    const chosen = typeof mode === 'number'
      ? drafts.filter(clip => clip.index === mode && clip.included)
      : mode === 'test'
        ? selectedDrafts
        : enabledDrafts
    if (!chosen.length) {
      notify('error', mode === 'test'
        ? 'Select at least one enabled PRE shot for the quality test.'
        : 'No enabled PRE shots are available.')
      return
    }
    if (!previewFingerprint) {
      notify('error', 'This PRE has no backend fingerprint. Rebuild it before generation.')
      return
    }
    if (frontendSourceStale) {
      notify('error', 'This PRE is stale relative to the current comic or film settings. Rebuild it from Video.')
      return
    }
    if (mode !== 'all' && !previewApproved) {
      notify('error', 'Approve this exact saved PRE before running representative test clips.')
      return
    }
    if (mode === 'all' && !fullGenerationUnlocked) {
      notify(
        'error',
        'Full generation requires this exact PRE fingerprint to be approved and its representative quality gate to be passed or explicitly waived.',
      )
      return
    }
    if (!window.confirm(
      `${mode === 'all' ? 'Generate the approved film' : 'Generate this quality test'} `
      + `from ${chosen.length} exact PRE shot${chosen.length === 1 ? '' : 's'} `
      + `with ${[...new Set(chosen.map(clip => clip.video_model))].join(', ')}?`,
    )) return
    setBusy(mode)
    try {
      const indices = chosen.map(clip => clip.index)
      const started = await api.generatePipelinePreview(pipelineId, {
        clipIndex: typeof mode === 'number' ? mode : undefined,
        clipIndices: typeof mode === 'number' ? undefined : indices,
        expectedFingerprint: previewFingerprint,
        runType: mode === 'all' ? 'full' : 'test',
      })
      handOffGeneration(started, chosen)
      notify('ok', started.reused
        ? 'Reconnected to the already-running PRE generation.'
        : `Started ${chosen.length} exact PRE clip${chosen.length === 1 ? '' : 's'}.`)
    } catch (error) {
      notify('error', (error as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="flex min-h-52 items-center justify-center gap-2 text-sm text-text-muted"><Loader2 size={16} className="animate-spin" /> Loading comic PRE…</div>
  if (!pipelineId || status?.status !== 'preview_ready') {
    return (
      <div className="mx-auto max-w-2xl rounded-xl border border-dashed border-border bg-bg-secondary/60 p-8 text-center">
        <Eye size={28} className="mx-auto text-text-muted" />
        <h2 className="mt-3 text-base font-semibold text-text-primary">No prepared film PRE</h2>
        <p className="mt-1 text-xs text-text-muted">Open Video → Configuration/Adaptation, prepare a PRE, and Maestro will open it here without covering the comic canvas.</p>
      </div>
    )
  }

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-4 p-3">
      <header className="sticky top-0 z-10 rounded-xl border border-red-400/35 bg-bg-primary/95 p-3 shadow-lg backdrop-blur">
        <div className="flex flex-wrap items-center gap-2">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-text-primary"><ListVideo size={16} className="text-red-300" /> Comic film PRE · {drafts.length} planned shots</div>
            <p className="mt-1 text-[10px] text-text-muted">This is a separate review workspace. Changes are saved into the durable PRE checkpoint before generation.</p>
            <p className="mt-1 text-[10px] text-accent-blue">
              Frozen video engine: <b>{preparedVideoModels.join(', ') || 'not reported'}</b>
            </p>
          </div>
          <div className="ml-auto flex flex-wrap gap-1.5">
            <button className={button} disabled={busy !== null || hasUnsavedLocalChanges} onClick={() => void loadPreview(pipelineId)}>Reload</button>
            <button className={button} disabled={busy !== null || frontendSourceStale} onClick={selectRepresentativePreviewTests}><Sparkles size={12} /> Auto-select test</button>
            <label className="flex items-center gap-1 rounded border border-border px-1.5 text-[9px] text-text-muted">
              Duration
              <input
                className="w-12 bg-transparent text-right text-text-primary outline-none"
                type="number"
                min={.8}
                max={20}
                step={.1}
                value={bulkDuration}
                onChange={event => setBulkDuration(Number(event.target.value))}
              />
              s
            </label>
            <button className={button} disabled={busy !== null || frontendSourceStale || !enabledDrafts.length} onClick={applyDurationToPreparedShots}>Apply to final shots</button>
            <button className={`${button} border-cyan-400/40 text-cyan-300`} disabled={busy !== null || dirty || frontendSourceStale || !previewApproved || !selectedDrafts.length} onClick={() => void generate('test')}><Play size={12} /> Test selected ({selectedDrafts.length})</button>
            <button className={`${button} border-emerald-400/40 text-emerald-300`} disabled={busy !== null || dirty || frontendSourceStale || !previewFingerprint || previewApproved || Boolean(unresolvedRisks.length)} onClick={() => void save({ approvePreview: true })}>{busy === 'approve' ? <Loader2 size={12} className="animate-spin" /> : previewApproved ? <CheckCircle2 size={12} /> : <ShieldCheck size={12} />} {previewApproved ? 'Exact PRE approved' : 'Approve exact PRE'}</button>
            <button className={`${button} border-purple-400/50 text-purple-200`} disabled={busy !== null || !fullGenerationUnlocked} onClick={() => void generate('all')}>{busy === 'all' ? <Loader2 size={12} className="animate-spin" /> : <Film size={12} />} Generate approved film</button>
          </div>
        </div>
        {frontendSourceStale && <div className="mt-2 rounded border border-red-400/40 bg-red-400/5 p-2 text-[10px] text-red-200"><AlertTriangle size={12} className="mr-1 inline" />This recovered PRE belongs to an older comic/configuration state. It remains viewable, but editing, approval and generation are locked. Return to Video and prepare a new PRE.</div>}
        {dirty && <div className="mt-2 flex items-center justify-between rounded border border-amber-400/35 bg-amber-400/5 p-2 text-[10px] text-amber-200"><span><AlertTriangle size={12} className="mr-1 inline" />Unsaved PRE edits. Saving rebuilds prepared inputs and invalidates approval and earlier tests.</span><button className={`${button} border-amber-400/50 text-amber-100`} disabled={busy !== null || frontendSourceStale} onClick={() => void save()}>{busy === 'save' ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} Save & rebuild PRE</button></div>}
        {!previewFingerprint && <div className="mt-2 rounded border border-red-400/40 bg-red-400/5 p-2 text-[10px] text-red-200"><AlertTriangle size={12} className="mr-1 inline" />Legacy PRE without a backend fingerprint. Rebuild it from Video; this checkpoint cannot be safely approved or generated.</div>}
        {!dirty && previewApproved && <div className={`mt-2 rounded border p-2 text-[10px] ${qualityGateReady ? 'border-emerald-400/35 bg-emerald-400/5 text-emerald-200' : 'border-cyan-400/35 bg-cyan-400/5 text-cyan-200'}`}><CheckCircle2 size={12} className="mr-1 inline" />PRE fingerprint approved. Quality gate: <b>{qualityGate?.status || 'pending'}</b>{qualityGateReady ? '; full generation is unlocked.' : '; run and review the representative test before full generation.'}</div>}
        {!dirty && previewApproved && qualityGate && !qualityGateReady && (
          <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-cyan-400/30 bg-cyan-400/5 p-2 text-[10px] text-cyan-100">
            <div className="min-w-0 flex-1">
              <span>
                Representative test: <b>{qualityTestedIndices.length}</b> completed / <b>{qualityRequiredIndices.length}</b> required.
                {!!(qualityGate.failures || []).length && <span className="ml-1 text-red-200">{qualityGate.failures.join(' · ')}</span>}
              </span>
              {!!qualityRequiredIndices.length && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-cyan-200/80">Required shots and recorded results</summary>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {qualityRequiredIndices.map(index => {
                      const result = qualityResults[String(index)]
                      const resultStatus = result?.passed === true
                        ? 'passed'
                        : result?.passed === false
                          ? 'failed'
                          : result?.status || (qualityTestedIndices.includes(index) ? 'completed' : 'pending')
                      return (
                        <span key={index} className={`rounded border px-1.5 py-0.5 ${resultStatus === 'passed' || resultStatus === 'completed' ? 'border-emerald-400/35 text-emerald-200' : resultStatus === 'failed' ? 'border-red-400/35 text-red-200' : 'border-border text-text-muted'}`}>
                          #{index + 1} · {resultStatus}
                        </span>
                      )
                    })}
                  </div>
                </details>
              )}
            </div>
            {qualityGate.status === 'review_required' && (
              <button className={`${button} ml-auto border-emerald-400/50 text-emerald-200`} disabled={busy !== null || frontendSourceStale || Boolean(pendingVisualReviews.length)} onClick={() => void acceptTestedClips()} title={pendingVisualReviews.length ? 'Review every required test video in its shot card first' : 'Accept the reviewed representative clips'}>
                {busy === 'accept' ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />} Accept tested clips
              </button>
            )}
          </div>
        )}
        {!dirty && previewApproved && !qualityGateReady && previewFingerprint && (
          <div className="mt-2 grid gap-2 rounded border border-amber-400/30 bg-amber-400/5 p-2 sm:grid-cols-[1fr_auto]">
            <label className="text-[9px] text-amber-100">
              Auditable quality-test waiver reason
              <input className={`${input} mt-1`} value={waiverReason} onChange={event => setWaiverReason(event.target.value)} placeholder="Why is a representative test unsafe, unavailable or intentionally skipped?" />
            </label>
            <button className={`${button} self-end border-amber-400/50 text-amber-100`} disabled={busy !== null || frontendSourceStale || !waiverReason.trim() || Boolean(unresolvedRisks.length)} onClick={() => void save({ qualityWaiver: true })}><ShieldCheck size={12} /> Waive quality test</button>
          </div>
        )}
        {!!unresolvedRisks.length && <div className="mt-2 rounded border border-red-400/40 bg-red-400/5 p-2 text-[10px] text-red-200"><AlertTriangle size={12} className="mr-1 inline" />{unresolvedRisks.length} enabled shot{unresolvedRisks.length === 1 ? '' : 's'} requested AI reframe but has no real prepared keyframe. Reframe import/generation is not available yet; choose Contain/Cover and save.</div>}
      </header>

      <div className="grid gap-3 xl:grid-cols-2">
        {drafts.map((clip, position) => {
          const risk = aspectRisk(clip) || Boolean(clip.needs_reframe)
          const sourceImage = sourceImageFor(clip)
          const testResult = qualityResults[String(clip.index)]
          const testVideoFilename = testResult?.video_filename || testResult?.output_files?.[0]
          const requiresVisualReview = qualityGate?.status === 'review_required'
            && qualityRequiredIndices.includes(clip.index)
          const promptIsManual = clip.prompt_override_update === true
            || (clip.prompt_override_update === undefined && clip.prompt_overridden)
          return (
            <article key={`${pipelineId}-${clip.index}`} className={`rounded-xl border ${clip.included ? risk ? 'border-amber-400/45' : 'border-border' : 'border-border opacity-55'} bg-bg-secondary/80 p-3`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-text-primary">{position + 1}. {clip.label || `Shot ${clip.index + 1}`}</span>
                <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[9px] text-purple-200">
                  {clip.effective_renderer && clip.effective_renderer !== clip.renderer
                    ? `${motionMethodLabel(clip.renderer)} → ${motionMethodLabel(clip.effective_renderer)}`
                    : motionMethodLabel(clip.effective_renderer || clip.renderer)}
                </span>
                {risk && <span className="rounded bg-amber-400/10 px-1.5 py-0.5 text-[9px] text-amber-200">aspect risk</span>}
                <div className="ml-auto flex gap-1"><button className={button} disabled={position === 0} onClick={() => moveDraft(position, -1)}><ArrowUp size={12} /></button><button className={button} disabled={position === drafts.length - 1} onClick={() => moveDraft(position, 1)}><ArrowDown size={12} /></button></div>
              </div>
              <div className="mt-1 text-[9px] text-text-muted">
                Primary <b className="text-text-primary">{clip.panel_id || `${clip.page_number || '?'}.${clip.panel_number || '?'}`}</b>
                {' · '}context from <b className="text-text-primary">{clip.source_panel_ids?.length || 1}</b> source panel{(clip.source_panel_ids?.length || 1) === 1 ? '' : 's'}
                {!!clip.source_panel_ids?.length && <span className="ml-1">({clip.source_panel_ids.join(', ')})</span>}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <figure>
                  <div className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-text-muted">Source panel · {clip.source_resolution || 'unknown'}</div>
                  <div className="relative overflow-hidden rounded border border-border bg-black" style={{ aspectRatio: previewRatio(clip.output_resolution) }}>
                    {sourceImage ? <img src={sourceImage} alt={`Source ${clip.label}`} className="h-full w-full object-contain" /> : <div className="flex h-full min-h-32 items-center justify-center text-[9px] text-text-muted">Source unavailable in this recovered PRE</div>}
                  </div>
                </figure>
                <figure>
                  <div className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-red-200">Prepared input · {clip.output_resolution}</div>
                  <div className="relative overflow-hidden rounded bg-black" style={{ aspectRatio: previewRatio(clip.output_resolution) }}>
                    <img src={api.getFileUrl(clip.image_filename)} alt={`Prepared ${clip.label}`} className="h-full w-full object-contain" />
                    <div className="pointer-events-none absolute inset-0 border-[3px] border-red-500/70 shadow-[inset_0_0_18px_rgba(239,68,68,0.18)]" />
                  </div>
                </figure>
              </div>
              {requiresVisualReview && (
                <div className="mt-2 rounded border border-cyan-400/30 bg-black/20 p-2">
                  <div className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-cyan-200">Generated representative test · human review required</div>
                  {testVideoFilename ? (
                    <>
                      <video
                        src={api.getFileUrl(testVideoFilename)}
                        controls
                        preload="metadata"
                        className="max-h-64 w-full rounded bg-black"
                        onEnded={() => setReviewedTestIndices(current =>
                          current.includes(clip.index) ? current : [...current, clip.index])}
                      />
                      <label className="mt-2 flex items-center gap-1.5 text-[9px] text-cyan-100">
                        <input
                          type="checkbox"
                          checked={reviewedTestIndices.includes(clip.index)}
                          onChange={event => setReviewedTestIndices(current =>
                            event.target.checked
                              ? current.includes(clip.index) ? current : [...current, clip.index]
                              : current.filter(index => index !== clip.index))}
                        />
                        I reviewed this exact generated clip and accept its visual quality.
                      </label>
                    </>
                  ) : (
                    <div className="rounded border border-red-400/30 p-2 text-[9px] text-red-200">The quality result has no playable video filename. Reload after the test finishes; this shot cannot be visually accepted yet.</div>
                  )}
                </div>
              )}
              {clip.needs_reframe ? (
                <div className="mt-2 rounded border border-red-400/35 bg-red-400/5 p-2 text-[9px] text-red-100">
                  AI reframe was requested, but this PRE has no real prepared keyframe. The backend used a safe contain fallback and blocks generation. Reframe import/generation is not available yet; change Fit to Contain/Cover and save.
                </div>
              ) : aspectRisk(clip) ? (
                <div className="mt-2 rounded border border-amber-400/30 bg-amber-400/5 p-2 text-[9px] text-amber-100">
                  Source and output aspect ratios differ substantially. <b>{clip.fit_mode}</b> is an explicit editorial choice; inspect the prepared input before approval.
                </div>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-3 text-[9px] text-text-muted">
                <label className="flex items-center gap-1"><input type="checkbox" checked={clip.included} onChange={event => patchDraft(clip.index, { included: event.target.checked })} /> Include</label>
                <label className="flex items-center gap-1"><input type="checkbox" checked={clip.test_selected} disabled={!clip.included} onChange={event => patchDraft(clip.index, { test_selected: event.target.checked })} /> Test sample</label>
                <span>Model <b className="text-text-primary">{clip.video_model}</b></span>
                {clip.runtime_recipe && <span>Recipe <b className="text-text-primary">{clip.runtime_recipe}</b></span>}
                <span>Steps <b className="text-text-primary">{clip.num_inference_steps}{clip.stage2_steps ? `+${clip.stage2_steps}` : ''}</b></span>
                {clip.requested_num_inference_steps !== undefined
                  && clip.requested_num_inference_steps !== clip.num_inference_steps
                  && <span>Requested steps <b className="text-text-primary">{clip.requested_num_inference_steps}</b></span>}
                {clip.requested_stage2_steps !== undefined
                  && clip.requested_stage2_steps !== clip.stage2_steps
                  && <span>Requested stage 2 <b className="text-text-primary">{clip.requested_stage2_steps}</b></span>}
                <span>CFG <b className="text-text-primary">{clip.guidance_scale}</b></span>
                {clip.requested_guidance_scale !== undefined
                  && clip.requested_guidance_scale !== clip.guidance_scale
                  && <span>Requested CFG <b className="text-text-primary">{clip.requested_guidance_scale}</b></span>}
                <span>Frames <b className="text-text-primary">{clip.frames}@{clip.fps}</b></span>
                {clip.output_frames !== undefined && <span>Output <b className="text-text-primary">{clip.output_frames} frames</b></span>}
                <span>Strength <b className="text-text-primary">{clip.input_video_strength}</b></span>
                <span>Prompt type <b className="text-text-primary">{clip.image_prompt_type || 'S'}</b></span>
                <span>Motion <b className="text-text-primary">{clip.motion_mode || 'automatic'}</b></span>
                <span>Fidelity <b className="text-text-primary">{clip.fidelity || 'default'}</b></span>
                {clip.self_refiner > 0 && <span>Self-refiner <b className="text-text-primary">{clip.self_refiner}</b></span>}
                {!!clip.activated_loras?.length && <span>LoRAs <b className="text-text-primary">{clip.activated_loras.join(', ')}</b>{clip.lora_multipliers ? ` · ${clip.lora_multipliers}` : ''}</span>}
                {clip.spatial_upsampling && <span>Upsampling <b className="text-text-primary">{clip.spatial_upsampling}</b></span>}
                {clip.film_grain_intensity > 0 && <span>Film grain <b className="text-text-primary">{clip.film_grain_intensity} / {clip.film_grain_saturation}</b></span>}
                {clip.effective_fit_mode && <span>Effective fit <b className="text-text-primary">{clip.effective_fit_mode}</b></span>}
                {clip.retained_fraction !== undefined && <span>Source retained <b className="text-text-primary">{Math.round(clip.retained_fraction * 100)}%</b></span>}
                {(clip.single_stage_pipeline > 0 || clip.progressive_pipeline > 0) && <span>Pipeline <b className="text-text-primary">{clip.single_stage_pipeline > 0 ? 'single-stage' : 'progressive'}</b></span>}
                {clip.used_prepared_keyframe && <span className="text-emerald-300">Prepared reframe verified</span>}
              </div>
              {clip.guidance_note && <p className="mt-1 rounded border border-border bg-bg-tertiary/50 px-2 py-1 text-[9px] text-text-muted">{clip.guidance_note}</p>}
              <div className="mt-2 grid grid-cols-2 gap-2">
                <label className="text-[9px] text-text-muted">Motion method<select className={`${input} mt-1`} value={clip.renderer} onChange={event => {
                  const renderer = event.target.value as PreviewDraft['renderer']
                  patchDraft(clip.index, {
                    renderer,
                    ...(renderer === 'hold'
                      ? { motion_level: 0 }
                      : renderer === 'parallax' || renderer === 'cinemagraph'
                        ? { motion_level: 1 }
                        : {}),
                  })
                }}><option value="hold">Hold · exact still</option><option value="parallax">Subtle centered push · deterministic</option><option value="cinemagraph">AI living still · subtle full-frame I2V</option><option value="ltx">Model-driven I2V · authored action</option></select></label>
                <label className="text-[9px] text-text-muted">Fit
                  <select className={`${input} mt-1`} value={clip.fit_mode} onChange={event => patchDraft(clip.index, { fit_mode: event.target.value as PreviewDraft['fit_mode'] })}>
                    {(clip.fit_mode === 'reframe' || clip.used_prepared_keyframe) && (
                      <option value="reframe" disabled={!clip.used_prepared_keyframe}>
                        {clip.used_prepared_keyframe ? 'Prepared AI reframe · verified' : 'Legacy reframe request · change to Contain/Cover'}
                      </option>
                    )}
                    <option value="cover">Cinematic crop · explicit</option>
                    <option value="contain">Whole panel + padding · safe</option>
                  </select>
                </label>
                <label className="text-[9px] text-text-muted">Duration<input className={`${input} mt-1`} type="number" min={.8} max={20} step={.1} value={clip.duration_seconds} onChange={event => patchDraft(clip.index, { duration_seconds: Number(event.target.value) })} /></label>
                <label className="text-[9px] text-text-muted">Seed<input className={`${input} mt-1`} type="number" value={clip.seed} onChange={event => patchDraft(clip.index, { seed: Math.trunc(Number(event.target.value)) })} /></label>
                <label className="text-[9px] text-text-muted">Motion level · {motionLevelLabel(clip.motion_level || 0)}<input className="mt-2 w-full" type="range" min={0} max={3} step={1} disabled={clip.renderer === 'hold' || clip.renderer === 'parallax' || clip.renderer === 'cinemagraph'} value={clip.motion_level || 0} onChange={event => patchDraft(clip.index, { motion_level: Number(event.target.value) })} /></label>
                <label className="col-span-2 text-[9px] text-text-muted">Camera<select className={`${input} mt-1`} value={clip.camera_move} disabled={clip.renderer !== 'ltx'} onChange={event => patchDraft(clip.index, { camera_move: event.target.value })}><option value="none">Locked / no move</option><option value="push-in">Push-in</option><option value="pull-out">Pull-out</option><option value="pan-left">Pan left</option><option value="pan-right">Pan right</option><option value="authored">Authored in prompt</option></select></label>
              </div>
              <label className="mt-2 block text-[9px] text-text-muted">
                <span className="flex items-center justify-between gap-2">
                  <span>Exact effective video prompt · {promptIsManual ? 'manual override' : 'automatic'}</span>
                  {promptIsManual && (
                    <button
                      type="button"
                      className={`${button} py-1 text-[9px]`}
                      onClick={() => patchDraft(clip.index, {
                        prompt: clip.base_prompt || clip.prompt,
                        prompt_override_update: false,
                      })}
                    >
                      Reset to automatic
                    </button>
                  )}
                </span>
                <textarea className={`${input} mt-1 min-h-28 resize-y font-mono text-[10px]`} value={clip.prompt} onChange={event => patchDraft(clip.index, { prompt: event.target.value, prompt_override_update: true })} />
              </label>
              {clip.dialogue && (
                <div className="mt-2 rounded border border-cyan-400/25 bg-cyan-400/5 p-2">
                  <div className="text-[9px] font-semibold uppercase tracking-wide text-cyan-200">
                    Spoken script retained
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-[10px] text-text-primary">{clip.dialogue}</p>
                  <p className="mt-1 text-[9px] text-text-muted">
                    {(clip.effective_renderer || clip.renderer) === 'ltx'
                      || (clip.effective_renderer || clip.renderer) === 'cinemagraph'
                      ? 'Automatic video-model prompts include a bounded excerpt as a performance and native-audio cue. Native model audio is not deterministic TTS: exact wording, timing and voice identity are not guaranteed. A manual prompt must include any words that must be attempted.'
                      : 'This deterministic motion method preserves the line for later dubbing or subtitles; it does not synthesize speech.'}
                  </p>
                </div>
              )}
              {clip.negative_prompt && <details className="mt-2"><summary className="cursor-pointer text-[9px] text-text-muted">Negative prompt and safeguards</summary><p className="mt-1 whitespace-pre-wrap rounded border border-border bg-bg-tertiary p-2 text-[9px] text-text-muted">{clip.negative_prompt}</p></details>}
              <button className={`${button} mt-2 w-full border-red-400/45 text-red-200`} disabled={busy !== null || dirty || frontendSourceStale || !clip.included || !previewApproved || Boolean(clip.needs_reframe && !(clip.reframe_approved && clip.used_prepared_keyframe))} onClick={() => void generate(clip.index)}>{busy === clip.index ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Generate only this approved test clip</button>
            </article>
          )
        })}
      </div>
    </div>
  )
}
