import { useMemo, useRef, useState } from 'react'
import {
  Check, ImagePlus, Loader2, Plus, ShieldCheck, Sparkles, Trash2, Upload,
} from 'lucide-react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
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
    ...panel.captions.map(text => `[Caption] ${text}`),
    ...panel.dialogue.map(line => `[${line.speakerId || 'Dialogue'}] ${line.text}`),
    ...panel.soundEffects.map(text => `[SFX] ${text}`),
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
        <p className="mt-1 text-[10px] text-text-muted">Review the dramatic beats and complete lettering before generating expensive artwork.</p>
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
      <div className="space-y-2"><strong className="text-[10px] uppercase tracking-wide text-text-muted">Full script</strong>{director.plan.pages.map((page, pageIndex) => <details key={`${page.pageNumber}-${director.scriptVersion || 1}`} className="rounded border border-border bg-bg-tertiary/30" style={{ contentVisibility: 'auto', containIntrinsicSize: '400px' }} open={pageIndex === 0}><summary className="cursor-pointer p-2 text-xs text-text-primary">Page {page.pageNumber} · {page.panels.length} panels</summary><div className="space-y-2 p-2 pt-0">{page.panels.map((panel, panelIndex) => <label key={`${panel.id}-${director.scriptVersion || 1}`} className="block text-[10px] text-text-muted">Panel {panelIndex + 1} · {panel.narrativeRole}<textarea className={`${input} mt-1`} rows={3} defaultValue={scriptForPanel(panel)} onBlur={event => patchPanel(pageIndex, panelIndex, event.target.value)} placeholder="Silent panel" /></label>)}</div></details>)}</div>
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
  const [aspect, setAspect] = useState<'landscape' | 'portrait' | 'square'>('landscape')
  const [defaultDuration, setDefaultDuration] = useState(3)
  const [transition, setTransition] = useState('crossfade')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [result, setResult] = useState<{ name: string; url: string } | null>(null)
  const panelCount = project.pages.reduce(
    (total, page) => total + page.elements.filter(element => element.type === 'panel' && !element.parentId).length,
    0,
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
  const create = async () => {
    if (panelCount > 200) {
      notify('error', `This animatic has ${panelCount} panels; the safe limit is 200.`)
      return
    }
    setBusy(true)
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
          motion: planned?.cameraMove || ((current - 1) % 4 === 1 ? 'pan-right' : (current - 1) % 4 === 2 ? 'pull-out' : (current - 1) % 4 === 3 ? 'pan-left' : 'push-in'),
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
      setBusy(false)
      setProgress('')
    }
  }
  return <div className="space-y-3"><div className="rounded-lg border border-cyan-400/30 bg-cyan-400/5 p-3"><div className="text-xs font-semibold text-text-primary">Comic to video</div><p className="mt-1 text-[10px] text-text-muted">Each final lettered panel becomes a shot. Panels are captured and uploaded one at a time to keep memory stable. The comic remains the script; motion, timing and transitions create an editable animatic.</p></div><label className="block text-[10px] text-text-muted">Format<select className={`${input} mt-1`} value={aspect} onChange={event => setAspect(event.target.value as typeof aspect)}><option value="landscape">Landscape 1080p</option><option value="portrait">Portrait 1080p</option><option value="square">Square 1080p</option></select></label><label className="block text-[10px] text-text-muted">Default seconds per panel<input className={`${input} mt-1`} type="number" min={.8} max={20} step={.1} value={defaultDuration} onChange={event => setDefaultDuration(Number(event.target.value))} /></label><label className="block text-[10px] text-text-muted">Transition<select className={`${input} mt-1`} value={transition} onChange={event => setTransition(event.target.value)}><option value="crossfade">Crossfade</option><option value="fade-black">Fade through black</option><option value="wipe-left">Wipe left</option><option value="dissolve">Dissolve</option><option value="zoom-in">Zoom portal</option><option value="none">Hard cuts</option></select></label>{project.director && <details className="rounded border border-border bg-bg-tertiary/30"><summary className="cursor-pointer p-2 text-xs text-text-primary">Shot timing and camera moves</summary><div className="space-y-2 p-2 pt-0">{project.director.plan.pages.flatMap((page, pageIndex) => page.panels.map((panel, panelIndex) => <div key={panel.id} className="grid grid-cols-[1fr_70px] gap-1.5 rounded border border-border p-1.5"><span className="text-[10px] text-text-muted">{pageIndex + 1}.{panelIndex + 1} · {panel.narrativeRole}</span><input className={input} type="number" min={.8} max={20} step={.1} value={panel.durationSeconds || defaultDuration} onChange={event => updateShot(pageIndex, panelIndex, { durationSeconds: Number(event.target.value) })} /><select className={`${input} col-span-2`} value={panel.cameraMove || 'push-in'} onChange={event => updateShot(pageIndex, panelIndex, { cameraMove: event.target.value as ComicPlanPanel['cameraMove'] })}><option value="none">Static</option><option value="push-in">Slow push-in</option><option value="pull-out">Slow pull-out</option><option value="pan-left">Pan left</option><option value="pan-right">Pan right</option></select></div>))}</div></details>}<button className={`${button} w-full border-cyan-400/50 text-cyan-300`} disabled={busy || panelCount === 0} onClick={create}>{busy ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {progress || 'Create video animatic'}</button>{result && <div className="space-y-2 rounded border border-emerald-500/30 bg-emerald-500/5 p-2"><video src={result.url} controls className="w-full rounded" /><button className={`${button} w-full border-emerald-500/40 text-emerald-300`} onClick={() => useStore.getState().setMediaFilter('videoeditor')}>Open in Video Editor</button></div>}</div>
}
