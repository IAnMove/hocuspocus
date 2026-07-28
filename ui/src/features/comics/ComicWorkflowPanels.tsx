import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Check, Film, ImagePlus, Loader2, Plus, ShieldCheck, Sparkles, Trash2, Upload,
} from 'lucide-react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import type { PlannedClip } from '../../types'
import { forEachComicPanelCapture } from './export'
import { comicId, normalizeComicPlan, simplifyDirectorText } from './model'
import { useComicStore } from './store'
import type { ComicAsset, ComicCharacter, ComicDirectorRequest, ComicGlossaryEntry, ComicPlanPanel } from './types'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
const input = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue'

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
      state.patchProject(simplifyDirectorText({
        ...state.project,
        title: result.plan.title,
        synopsis: result.plan.synopsis,
        director: {
          ...current,
          plan: normalizeComicPlan(result.plan, current.input.dialogueDensity),
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
                        plan.pages[pageIndex].panels[panelIndex].videoPrompt = event.target.value
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
  const selectedVideoModel = useStore(state => state.selectedModelPerMode.video)
  const videoModels = useStore(state => state.models)
  const enabledModels = useStore(state => state.enabledModels)
  const selectDirectorVideoModel = useStore(state => state.selectDirectorVideoModel)
  const storyboard = project.director?.input.productionMode === 'storyboard'
  const [aspect, setAspect] = useState<'landscape' | 'portrait' | 'square'>(() =>
    project.director?.input.storyboardAspect || 'landscape')
  const [defaultDuration, setDefaultDuration] = useState(3)
  const [transition, setTransition] = useState('none')
  const [animaticMotion, setAnimaticMotion] = useState<'none' | 'shot-settings'>('none')
  const [movieQuality, setMovieQuality] = useState<'480p' | '720p'>(() =>
    project.director?.input.storyboardQuality === 'final' ? '720p' : '480p')
  const [movieImageFit, setMovieImageFit] = useState<'smart' | 'crop'>('smart')
  const [movieAnchorMode, setMovieAnchorMode] = useState<'start_only' | 'smart' | 'chain'>('start_only')
  const [movieFidelity, setMovieFidelity] = useState<'faithful' | 'balanced' | 'expressive'>('faithful')
  const [busy, setBusy] = useState<'animatic' | 'movie' | null>(null)
  const [progress, setProgress] = useState('')
  const [result, setResult] = useState<{ name: string; url: string } | null>(null)
  useEffect(() => {
    setAspect(project.director?.input.storyboardAspect || 'landscape')
    setMovieQuality(
      project.director?.input.storyboardQuality === 'final' ? '720p' : '480p',
    )
  }, [
    project.id,
    project.director?.input.storyboardAspect,
    project.director?.input.storyboardQuality,
  ])
  const panelCount = project.pages.reduce(
    (total, page) => total + page.elements.filter(element => element.type === 'panel' && !element.parentId).length,
    0,
  )
  const selectableVideoModels = useMemo(
    () => videoModels
      .filter(model => model.is_i2v && enabledModels.has(model.model_type))
      .sort((left, right) => left.name.localeCompare(right.name)),
    [enabledModels, videoModels],
  )
  const resolution = aspect === 'portrait'
    ? { width: 1080, height: 1920 }
    : aspect === 'square' ? { width: 1080, height: 1080 } : { width: 1920, height: 1080 }
  const updateShot = (pageIndex: number, panelIndex: number, patch: Partial<ComicPlanPanel>) => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const plan = structuredClone(director.plan)
    Object.assign(plan.pages[pageIndex].panels[panelIndex], patch)
    state.patchProject({ director: { ...director, plan } })
  }
  const updateAllShots = (
    patch: Partial<Pick<ComicPlanPanel, 'durationSeconds' | 'cameraMove' | 'videoTransition'>>,
    message: string,
  ) => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const plan = structuredClone(director.plan)
    plan.pages.forEach(page => page.panels.forEach(planned => Object.assign(planned, patch)))
    state.patchProject({ director: { ...director, plan } })
    notify('ok', message)
  }
  const create = async () => {
    if (panelCount > 200) {
      notify('error', `This animatic has ${panelCount} panels; the safe limit is 200.`)
      return
    }
    if (!window.confirm(
      `Render a quick non-generative storyboard preview from ${panelCount} still panels? `
      + 'This does not call LTX or animate characters; it only holds the drawings and optionally applies FFmpeg pans, zooms and transitions.',
    )) return
    setBusy('animatic')
    setResult(null)
    try {
      const panels: Array<{
        source: string
        page_number: number
        panel_number: number
        duration: number
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

  const convertToMovie = async () => {
    if (panelCount > 200) {
      notify('error', `This comic has ${panelCount} panels; the safe conversion limit is 200.`)
      return
    }
    const totalSeconds = Math.round(project.director?.plan.pages.reduce(
      (sum, page) => sum + page.panels.reduce(
        (pageSum, planned) => pageSum + (planned.durationSeconds || defaultDuration),
        0,
      ),
      0,
    ) || panelCount * defaultDuration)
    if (!window.confirm(
      `Convert ${panelCount} comic panels into about ${totalSeconds}s of generated video? `
      + 'The existing artwork will be reused, so no new panel images are generated, but this starts one image-to-video shot per panel and may consume substantial video credits/time.',
    )) return

    setBusy('movie')
    setResult(null)
    try {
      const comicShots: Array<{
        comic_title: string
        image_path: string
        page_number: number
        panel_number: number
        duration: number
        camera_move: string
        narrative_role: string
        scene_description: string
        image_prompt: string
        framing: string
        characters: string[]
        script: string
        visual_style: string
        video_prompt: string
        transition_to_next: 'auto' | 'cut' | 'interpolate'
      }> = []
      await forEachComicPanelCapture(async (capture, current, total) => {
        setProgress(`Preparing artwork ${current}/${total}`)
        const blob = await (await fetch(capture.dataUrl)).blob()
        const upload = await api.uploadImage(new File(
          [blob],
          `comic-movie-${capture.pageNumber}-${capture.panelNumber}.png`,
          { type: 'image/png' },
        ))
        const planned = project.director?.plan.pages[capture.pageNumber - 1]?.panels[capture.panelNumber - 1]
        comicShots.push({
          comic_title: project.title,
          image_path: upload.path,
          page_number: capture.pageNumber,
          panel_number: capture.panelNumber,
          duration: planned?.durationSeconds || defaultDuration,
          camera_move: planned?.cameraMove || 'push-in',
          narrative_role: planned?.narrativeRole || `Panel ${capture.pageNumber}.${capture.panelNumber}`,
          scene_description: planned?.sceneDescription || '',
          image_prompt: planned?.imagePrompt || '',
          framing: planned?.framing || 'match comic panel',
          characters: planned?.characters || [],
          script: planned ? scriptForPanel(planned) : '',
          video_prompt: planned?.videoPrompt || '',
          transition_to_next: planned?.videoTransition || 'auto',
          visual_style: [
            project.style.name,
            project.style.promptSuffix,
            project.director?.plan.styleBible || '',
          ].filter(Boolean).join('. '),
        })
      }, (current, total) => setProgress(`Capturing clean artwork ${current}/${total}`), {
        // Lettering remains in the comic/script but is removed from I2V first
        // frames so the video model cannot warp speech bubbles or captions.
        includeLettering: false,
      })

      const movieContext = [
        `TITLE: ${project.title}`,
        `SYNOPSIS: ${project.synopsis}`,
        `LANGUAGE: ${project.language}`,
        `COMIC STYLE: ${project.style.name}. ${project.style.promptSuffix}`,
        project.director?.plan.logline ? `LOGLINE: ${project.director.plan.logline}` : '',
        project.director?.plan.synopsis ? `DIRECTOR SYNOPSIS: ${project.director.plan.synopsis}` : '',
        project.director?.plan.styleBible ? `STYLE BIBLE: ${project.director.plan.styleBible}` : '',
        project.director?.input.storyContext ? `MASTER STORY CANON:\n${project.director.input.storyContext}` : '',
        project.director?.input.worldContext ? `WORLD CONTINUITY:\n${project.director.input.worldContext}` : '',
        project.director?.input.forbiddenElements ? `NEVER INTRODUCE: ${project.director.input.forbiddenElements}` : '',
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
      ].filter(Boolean).join('\n\n')

      const before = useStore.getState()
      const videoModel = before.selectedModelPerMode.video || 'ltx2_22B_distilled_1_1'
      await before.loadModelOptions(videoModel)
      const state = useStore.getState()
      if (
        movieAnchorMode !== 'start_only'
        && state.modelOptions
        && !state.modelOptions.supports_end_frame
      ) {
        throw new Error(
          'The selected video model does not support end frames. '
          + 'Choose an LTX model or use “First frame only”.',
        )
      }
      const qualityResolution = movieQuality === '720p'
        ? (aspect === 'portrait' ? '704x1280' : aspect === 'square' ? '1024x1024' : '1280x704')
        : (aspect === 'portrait' ? '448x832' : aspect === 'square' ? '640x640' : '832x448')
      const fps = state.modelOptions?.fps || 16
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

      setProgress('Submitting comic movie to Director…')
      const { pipeline_id } = await api.startPipeline({
        pipeline_type: 'comic_movie',
        auto_mode: true,
        workspace: state.activeWorkspace,
        scene_description: movieContext,
        comic_shots: comicShots,
        provided_clip_image_paths: comicShots.map(shot => shot.image_path),
        video_image_fit: movieImageFit,
        comic_anchor_mode: movieAnchorMode,
        comic_motion_fidelity: movieFidelity,
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
          resolution: qualityResolution,
          input_video_strength: movieFidelity === 'faithful'
            ? 1
            : Number(state.savedParamsPerMode.video?.input_video_strength ?? .8),
        },
        video_loras: state.savedLoraPerMode.video || {},
        video_spatial_upsampling: state.directorVideoSpatialUpsampling,
        video_film_grain_intensity: state.directorVideoFilmGrainIntensity,
        video_film_grain_saturation: state.directorVideoFilmGrainSaturation,
        video_self_refiner: state.directorVideoSelfRefiner,
        audio_scale: state.directorAudioScale,
      })

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
      useStore.getState().pollPipelineStatus()
      window.dispatchEvent(new Event('maestro:director-open'))
      notify(
        'ok',
        movieAnchorMode === 'start_only'
          ? 'Comic movie started. Every panel is animated as an independent I2V shot, then joined with a clean cut.'
          : 'Comic movie started. Compatible shots also use the following approved panel as an I2V end-frame anchor.',
      )
    } catch (error) {
      notify('error', (error as Error).message)
    } finally {
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
            : 'The LLM reads the comic canon and every scene, then writes one motion/performance prompt per panel. Clean panel artwork becomes the real first frame of each I2V shot; speech bubbles stay in the script instead of being distorted by the video model.'}
        </p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block text-[10px] text-text-muted">Movie format
          <select className={`${input} mt-1`} value={aspect} onChange={event => setAspect(event.target.value as typeof aspect)}>
            <option value="landscape">Landscape</option>
            <option value="portrait">Portrait</option>
            <option value="square">Square</option>
          </select>
        </label>
        <label className="block text-[10px] text-text-muted">I2V quality
          <select className={`${input} mt-1`} value={movieQuality} onChange={event => setMovieQuality(event.target.value as typeof movieQuality)}>
            <option value="480p">480p · faster test</option>
            <option value="720p">720p · final</option>
          </select>
        </label>
      </div>
      <label className="block text-[10px] text-text-muted">Video model
        <select
          className={`${input} mt-1`}
          value={selectedVideoModel || 'ltx2_22B_distilled_1_1'}
          onChange={event => selectDirectorVideoModel(event.target.value)}
        >
          {!selectableVideoModels.some(model => model.model_type === selectedVideoModel) && selectedVideoModel && (
            <option value={selectedVideoModel}>{selectedVideoModel}</option>
          )}
          {selectableVideoModels.map(model => (
            <option key={model.model_type} value={model.model_type}>
              {model.name}{model.is_downloaded === false ? ' · not installed' : ''}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-[9px] text-text-muted">
          LTX-2.3 Distilled INT8 is the measured recommendation for this RTX 4090: it preserved the reference better than Q6 and rendered diffusion faster.
        </span>
      </label>
      <label className="block text-[10px] text-text-muted">Panel fit
        <select className={`${input} mt-1`} value={movieImageFit} onChange={event => setMovieImageFit(event.target.value as typeof movieImageFit)}>
          <option value="smart">Smart fill · keep the whole panel</option>
          <option value="crop">Crop to fill · no borders</option>
        </select>
        <span className="mt-1 block text-[9px] text-text-muted">
          Smart fill preserves the complete panel and fills spare space with a subdued blurred edge copy. Every shot keeps one fixed movie resolution, which is required for reliable joining.
        </span>
      </label>
      {selectedVideoModel?.includes('gguf') && (
        <div className="rounded border border-amber-400/30 bg-amber-400/5 px-2 py-1.5 text-[10px] text-amber-200">
          Q6 is the low-VRAM/compatibility option. It was slower and preserved the reference less faithfully than INT8 in the local RTX 4090 comparison.
          <button
            className="ml-1 underline"
            type="button"
            onClick={() => selectDirectorVideoModel('ltx2_22B_distilled_1_1')}
          >
            Use recommended INT8
          </button>
        </div>
      )}
      {selectedVideoModel?.includes('fp8') && (
        <div className="rounded border border-amber-400/30 bg-amber-400/5 px-2 py-1.5 text-[10px] text-amber-200">
          FP8 remains experimental here: the local comparison took longer and introduced visible anatomy/clothing deformation. INT8 is the quality recommendation.
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className="block text-[10px] text-text-muted">Panel anchors
          <select
            className={`${input} mt-1`}
            value={movieAnchorMode}
            onChange={event => setMovieAnchorMode(event.target.value as typeof movieAnchorMode)}
          >
            <option value="start_only">Animate each panel · hard cut · recommended</option>
            <option value="smart">Smart start → end · continuity shots only</option>
            <option value="chain">Every panel → next · experimental</option>
          </select>
        </label>
        <label className="block text-[10px] text-text-muted">Motion fidelity
          <select
            className={`${input} mt-1`}
            value={movieFidelity}
            onChange={event => setMovieFidelity(event.target.value as typeof movieFidelity)}
          >
            <option value="faithful">Faithful · preserve art, perform action</option>
            <option value="balanced">Balanced</option>
            <option value="expressive">Expressive · more drift risk</option>
          </select>
        </label>
      </div>
      <p className="text-[9px] text-text-muted">
        “Animate each panel” performs the scene inside its own composition and then cuts. Smart interpolation is only for deliberately continuous actions whose next panel is the intended final frame.
      </p>
      <label className="block text-[10px] text-text-muted">Default action duration per panel
        <input className={`${input} mt-1`} type="number" min={.8} max={20} step={.1} value={defaultDuration} onChange={event => setDefaultDuration(Number(event.target.value))} />
      </label>
      {project.director && (
        <div className="space-y-1.5 rounded border border-border bg-bg-tertiary/30 p-2">
          <p className="text-[9px] text-text-muted">
            Existing shots keep their individual timing. Apply the value above when you want to update the whole film.
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            <button
              className={button}
              type="button"
              onClick={() => updateAllShots(
                { durationSeconds: defaultDuration },
                `Applied ${defaultDuration}s to all ${panelCount} shots.`,
              )}
            >
              Apply {defaultDuration}s to all
            </button>
            <button
              className={`${button} border-emerald-400/40 text-emerald-300`}
              type="button"
              onClick={() => updateAllShots(
                {
                  durationSeconds: defaultDuration,
                  videoTransition: 'cut',
                },
                `Applied independent-shot defaults to all ${panelCount} shots: ${defaultDuration}s of action followed by a clean cut.`,
              )}
            >
              Independent shots for all
            </button>
          </div>
        </div>
      )}
      {project.director && (
        <details className="rounded border border-border bg-bg-tertiary/30">
          <summary className="cursor-pointer p-2 text-xs text-text-primary">Shot timing and camera moves</summary>
          <div className="space-y-2 p-2 pt-0">
            {project.director.plan.pages.flatMap((page, pageIndex) => page.panels.map((planned, panelIndex) => (
              <div key={planned.id} className="grid grid-cols-[1fr_70px] gap-1.5 rounded border border-border p-1.5">
                <span className="text-[10px] text-text-muted">{pageIndex + 1}.{panelIndex + 1} · {planned.narrativeRole}</span>
                <input className={input} type="number" min={.8} max={20} step={.1} value={planned.durationSeconds || defaultDuration} onChange={event => updateShot(pageIndex, panelIndex, { durationSeconds: Number(event.target.value) })} />
                <select className={`${input} col-span-2`} value={planned.cameraMove || 'push-in'} onChange={event => updateShot(pageIndex, panelIndex, { cameraMove: event.target.value as ComicPlanPanel['cameraMove'] })}>
                  <option value="none">Static</option>
                  <option value="push-in">Slow push-in</option>
                  <option value="pull-out">Slow pull-out</option>
                  <option value="pan-left">Pan left</option>
                  <option value="pan-right">Pan right</option>
                </select>
                <select
                  className={`${input} col-span-2`}
                  value={planned.videoTransition || 'auto'}
                  onChange={event => updateShot(pageIndex, panelIndex, {
                    videoTransition: event.target.value as ComicPlanPanel['videoTransition'],
                  })}
                  title="How this shot reaches the following panel"
                >
                  <option value="auto">Transition · follow panel-anchor mode</option>
                  <option value="cut">Transition to next · force cut</option>
                  <option value="interpolate">Transition to next · force end-frame interpolation</option>
                </select>
                <textarea
                  className={`${input} col-span-2`}
                  rows={5}
                  value={planned.videoPrompt || ''}
                  onChange={event => updateShot(pageIndex, panelIndex, {
                    videoPrompt: event.target.value,
                  })}
                  placeholder={storyboard
                    ? 'Chronological action, performance, camera and final beat…'
                    : 'Optional manual action inside this panel. Leave blank for the LLM to write it from the scene and script…'}
                />
              </div>
            )))}
          </div>
        </details>
      )}
      <button className={`${button} w-full border-purple-400/50 text-purple-300`} disabled={Boolean(busy) || panelCount === 0} onClick={convertToMovie}>
        {busy === 'movie' ? <Loader2 size={13} className="animate-spin" /> : <Film size={13} />}
        {busy === 'movie' && progress
          ? progress
          : `Generate ${panelCount} real I2V shots with ${selectedVideoModel || 'the selected model'}`}
      </button>
      <p className="text-[9px] text-purple-200/80">
        This is the generative option: it submits one image-to-video job per panel to the selected model.
      </p>

      <details className="border-t border-border pt-3">
        <summary className="cursor-pointer text-xs font-semibold text-text-muted">
          FFmpeg storyboard preview · still images only
        </summary>
        <div className="mt-2 space-y-2 rounded border border-amber-400/25 bg-amber-400/5 p-2">
          <p className="text-[10px] text-amber-100/80">
            This preview never calls LTX and cannot animate characters or environments. It only holds the existing drawings; optional camera moves and transitions are programmatic.
          </p>
          <label className="block text-[10px] text-text-muted">Preview motion
            <select className={`${input} mt-1`} value={animaticMotion} onChange={event => setAnimaticMotion(event.target.value as typeof animaticMotion)}>
              <option value="none">Static panels · recommended</option>
              <option value="shot-settings">Use programmed pan/zoom settings</option>
            </select>
          </label>
          <label className="block text-[10px] text-text-muted">Preview transition
            <select className={`${input} mt-1`} value={transition} onChange={event => setTransition(event.target.value)}>
              <option value="none">Hard cuts · recommended</option>
              <option value="crossfade">Crossfade</option>
              <option value="fade-black">Fade through black</option>
              <option value="wipe-left">Wipe left</option>
              <option value="dissolve">Dissolve</option>
              <option value="zoom-in">Zoom portal</option>
            </select>
          </label>
          <button className={`${button} w-full border-cyan-400/50 text-cyan-300`} disabled={Boolean(busy) || panelCount === 0} onClick={create}>
            {busy === 'animatic' ? <Loader2 size={13} className="animate-spin" /> : <Film size={13} />}
            {busy === 'animatic' && progress ? progress : 'Render non-AI storyboard preview'}
          </button>
        </div>
      </details>
      {result && (
        <div className="space-y-2 rounded border border-emerald-500/30 bg-emerald-500/5 p-2">
          <video src={result.url} controls className="w-full rounded" />
          <button className={`${button} w-full border-emerald-500/40 text-emerald-300`} onClick={() => useStore.getState().setMediaFilter('videoeditor')}>Open in Video Editor</button>
        </div>
      )}
    </div>
  )
}
