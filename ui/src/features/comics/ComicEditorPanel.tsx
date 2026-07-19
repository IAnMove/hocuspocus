import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Copy, Download, Eye, EyeOff, FileJson,
  ImagePlus, Loader2, Lock, PanelTop, Plus, Redo2, Save, Sparkles, Trash2,
  Maximize2, Type, Undo2, Unlock, Upload, WandSparkles,
} from 'lucide-react'
import { getModelMode, useStore } from '../../stores/useStore'
import * as api from '../../api/client'
import { ComicCanvas } from './ComicCanvas'
import {
  comicId, COMIC_FORMATS, createComicProject, normalizeComicProject, panelsForCount,
  normalizeComicPlan, planWithCanvasText, projectFromPlan, repairComicText, repairMojibake,
  simplifyDirectorText, varyDirectorLayouts,
} from './model'
import { COMIC_EFFECTS, COMIC_LAYOUTS, createEffect } from './presets'
import { useComicStore } from './store'
import { captureComicPage, exportComicCbz, exportComicJson, exportComicPagePng, exportComicPdf } from './export'
import type {
  ComicAsset, ComicCharacter, ComicDirectorRequest, ComicElement, ComicImageElement,
  ComicPanelElement, ComicPlan, ComicPlanPanel, ComicProject, ComicTextElement,
} from './types'

type SideTab = 'assets' | 'inspector' | 'director'
type Notice = { kind: 'ok' | 'error'; text: string } | null
type DirectorActivity = {
  state: 'idle' | 'running' | 'complete' | 'error'
  message: string
  current?: number
  total?: number
  steps: string[]
}

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
const input = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue'

const fileName = (path: string) => path.split(/[\\/]/).pop() || path
const wait = (milliseconds: number) => new Promise(resolve => window.setTimeout(resolve, milliseconds))

function panelScript(panel: ComicPlanPanel): string {
  return [
    ...panel.captions.map(text => `[Caption] ${text}`),
    ...panel.dialogue.map(line => `[${line.speakerId || 'Dialogue'}] ${line.text}`),
    ...panel.soundEffects.map(text => `[SFX] ${text}`),
  ].join('\n')
}

function parsePanelScript(value: string): Pick<ComicPlanPanel, 'captions' | 'dialogue' | 'soundEffects'> {
  const captions: string[] = []
  const dialogue: ComicPlanPanel['dialogue'] = []
  const soundEffects: string[] = []
  value.split(/\r?\n/).map(line => line.trim()).filter(Boolean).forEach(line => {
    const tagged = line.match(/^\[([^\]]+)\]\s*(.+)$/)
    const colon = !tagged ? line.match(/^([^:]{1,40}):\s*(.+)$/) : null
    const tag = (tagged?.[1] || colon?.[1] || 'Dialogue').trim()
    const text = (tagged?.[2] || colon?.[2] || line).trim()
    if (/^capt(?:ion|ura)$/i.test(tag)) captions.push(text)
    else if (/^(?:sfx|fx|efecto)$/i.test(tag)) soundEffects.push(text)
    else dialogue.push({
      speakerId: /^dialogue|diálogo$/i.test(tag) ? undefined : tag,
      text,
      bubbleType: 'speech',
    })
  })
  return { captions, dialogue, soundEffects }
}

function PanelScriptEditor({
  panel,
  onCommit,
}: {
  panel: ComicPlanPanel
  onCommit: (value: string) => void
}) {
  const canonical = panelScript(panel)
  const [value, setValue] = useState(canonical)
  useEffect(() => setValue(canonical), [canonical])
  return (
    <textarea
      className={input}
      rows={3}
      value={value}
      placeholder="Leave empty for a silent panel. Use [Caption], [Dialogue], [SFX] or [Character]."
      onChange={event => setValue(event.target.value)}
      onBlur={() => value !== canonical && onCommit(value)}
    />
  )
}

function buildDirectorImagePrompt(
  director: ComicProject['director'],
  panelPrompt: string,
  promptSuffix: string,
): string {
  const input = director?.input
  const removePageLayoutInstructions = (value: string) => repairMojibake(value)
    .replace(/\b(?:estructura|structure|layout)\s*:\s*[^.!?]*(?:p[aá]ginas?|pages?|paneles?|panels?|viñetas?)[^.!?]*[.!?]*/gi, ' ')
    .replace(/[^.!?]*(?:\d+\s+)?(?:p[aá]ginas?|pages?)[^.!?]*(?:paneles?|panels?|viñetas?)[^.!?]*[.!?]*/gi, ' ')
    .replace(/\bprofessional sequential comic art\b/gi, 'single comic-panel illustration')
    .replace(/\s+/g, ' ')
    .trim()
  const visualBible = removePageLayoutInstructions(director?.plan.styleBible || '')
  const repairedPanelPrompt = removePageLayoutInstructions(panelPrompt)
  return [
    'SINGLE IMAGE LOCK: Create exactly one full-bleed illustration for one comic panel. No comic page, panel grid, collage, split screen, inset panels, frames, borders, speech bubbles, captions, sound effects, text, logos, watermarks or lettering.',
    input?.artStyle ? `VISUAL STYLE LOCK: ${removePageLayoutInstructions(input.artStyle)}.` : '',
    input?.worldContext ? `WORLD AND PERIOD LOCK: ${removePageLayoutInstructions(input.worldContext)}.` : '',
    visualBible && !repairedPanelPrompt.includes(visualBible)
      ? `VISUAL CONTINUITY BIBLE: ${visualBible}.`
      : '',
    input?.forbiddenElements
      ? `STRICTLY FORBIDDEN: ${repairMojibake(input.forbiddenElements)}. No anachronisms.`
      : '',
    repairedPanelPrompt,
    removePageLayoutInstructions(promptSuffix),
  ].filter(Boolean).join(' ')
}

function assetFromOutput(output: { name: string; url: string; thumbnail_url?: string | null }): ComicAsset {
  return {
    id: comicId('asset'),
    name: output.name,
    kind: 'maestro-output',
    source: output.url,
    thumbnail: output.thumbnail_url || output.url,
    createdAt: new Date().toISOString(),
  }
}

type LocalImageOptions = {
  panelId?: string
  existingJobId?: string
  onJobSubmitted?: (jobId: string) => void
  onPollRetry?: (attempt: number, error: string) => void
}

function localAsset(
  name: string,
  prompt: string,
  model: string,
  jobId?: string,
): ComicAsset {
  return {
    id: comicId('asset'),
    name,
    kind: 'local',
    source: `/api/v1/file/${encodeURIComponent(name)}`,
    prompt,
    provider: 'maestro',
    model,
    createdAt: new Date().toISOString(),
    metadata: jobId ? { jobId } : undefined,
  }
}

async function findCompletedLocalImage(
  prompt: string,
  model: string,
  excludedNames: Set<string>,
): Promise<ComicAsset | null> {
  const { outputs } = await api.fetchOutputs(50, 0)
  const candidates = outputs.filter(output =>
    output.type === 'image' && !excludedNames.has(output.name))
  for (const output of candidates) {
    try {
      const metadata = await api.fetchOutputMetadata(output.name)
      if (
        metadata.params?.prompt === prompt &&
        metadata.params?.model_type === model
      ) {
        return localAsset(output.name, prompt, model, metadata.job_id)
      }
    } catch {
      // One unreadable gallery sidecar must not prevent recovery from the rest.
    }
  }
  return null
}

async function runLocalImage(
  prompt: string,
  modelType?: string,
  options: LocalImageOptions = {},
): Promise<ComicAsset> {
  const maestro = useStore.getState()
  const selected = modelType || maestro.selectedModelPerMode.image || maestro.params.model_type
  if (!selected) throw new Error('Select an image model in Maestro first')
  const model = maestro.models.find(item => item.model_type === selected)
  if (model && getModelMode(model.model_type, model.family) !== 'image') {
    throw new Error(`"${selected}" is a video model. Select a Maestro image model or MiniMax for comic panels`)
  }
  const imageParams = maestro.savedParamsPerMode.image || {}
  const jobId = options.existingJobId || (await api.submitGeneration({
      ...maestro.params,
      ...imageParams,
      prompt,
      model_type: selected,
      image_mode: 1,
      generation_mode: 'image',
      comic_panel: true,
      comic_panel_id: options.panelId,
      provider: 'maestro',
      repeat_generation: 1,
      workspace: maestro.activeWorkspace,
    })).job_id
  if (!options.existingJobId) options.onJobSubmitted?.(jobId)
  let consecutivePollFailures = 0
  for (;;) {
    await wait(consecutivePollFailures ? Math.min(10000, 1500 * consecutivePollFailures) : 1500)
    let status: api.ApiJobStatus
    try {
      status = await api.fetchJobStatus(jobId)
      consecutivePollFailures = 0
    } catch (error) {
      consecutivePollFailures += 1
      options.onPollRetry?.(consecutivePollFailures, (error as Error).message)
      if (consecutivePollFailures >= 20) {
        throw new Error(`Could not reconnect to Maestro job ${jobId}; the job ID was preserved`)
      }
      continue
    }
    if (status.status === 'failed' || status.status === 'cancelled') {
      throw new Error(status.error || status.message || 'Local image generation failed')
    }
    if (status.status === 'completed') {
      const path = status.output_files.find(value => /\.(png|jpe?g|webp)$/i.test(value))
      if (!path) throw new Error('Image job completed without an image')
      const name = fileName(path)
      maestro.loadOutputs()
      return localAsset(name, prompt, selected, jobId)
    }
  }
}

async function generatePanelAsset(
  provider: 'maestro' | 'minimax',
  prompt: string,
  model?: string,
  reference?: string,
  options?: LocalImageOptions,
): Promise<ComicAsset> {
  if (provider === 'minimax') {
    const result = await api.generateComicWithMiniMax({
      prompt,
      aspect_ratio: '1:1',
      subject_reference: reference,
    })
    return result.asset
  }
  return runLocalImage(prompt, model, options)
}

function insertAssetIntoPage(asset: ComicAsset) {
  const state = useComicStore.getState()
  const page = state.project.pages.find(item => item.id === state.currentPageId)
  if (!page) return
  state.addAsset(asset)
  const selected = page.elements.find(element => element.id === state.selectedId)
  const panel = selected?.type === 'panel'
    ? selected
    : page.elements.find(element => element.id === selected?.parentId && element.type === 'panel') as ComicPanelElement | undefined
  const image: ComicImageElement = {
    id: comicId('image'),
    type: 'image',
    assetId: asset.id,
    parentId: panel?.id ?? null,
    x: panel ? 0 : page.width * 0.15,
    y: panel ? 0 : page.height * 0.15,
    width: panel?.width ?? page.width * 0.7,
    height: panel?.height ?? page.height * 0.7,
    rotation: 0,
    zIndex: panel ? 2 : Math.max(1, ...page.elements.map(item => item.zIndex + 1)),
    objectFit: 'cover',
    filter: 'none',
    opacity: 1,
    visible: true,
  }
  state.addElement(page.id, image)
}

function PagesRail() {
  const project = useComicStore(state => state.project)
  const current = useComicStore(state => state.currentPageId)
  const setCurrent = useComicStore(state => state.setCurrentPage)
  const addPage = useComicStore(state => state.addPage)
  const duplicate = useComicStore(state => state.duplicatePage)
  const movePage = useComicStore(state => state.movePage)
  const remove = useComicStore(state => state.deletePage)
  return (
    <aside className="w-36 shrink-0 border-r border-border bg-bg-secondary p-2 overflow-y-auto">
      <button className={`${button} w-full mb-2`} onClick={addPage}><Plus size={13} /> Add page</button>
      <div className="space-y-2">
        {project.pages.map((page, index) => (
          <div key={page.id} className={`rounded-lg border p-1 ${page.id === current ? 'border-accent-blue bg-accent-blue/10' : 'border-border'}`}>
            <button className="w-full" onClick={() => setCurrent(page.id)}>
              <div className="bg-white mx-auto overflow-hidden relative" style={{
                width: 80,
                height: Math.min(110, 80 * page.height / page.width),
              }}>
                {page.elements.filter(el => el.type === 'panel' && !el.parentId).map(el => (
                  <span key={el.id} className="absolute border border-black/60 bg-gray-100" style={{
                    left: `${el.x / page.width * 100}%`,
                    top: `${el.y / page.height * 100}%`,
                    width: `${el.width / page.width * 100}%`,
                    height: `${el.height / page.height * 100}%`,
                  }} />
                ))}
              </div>
              <span className="block text-[10px] text-text-muted mt-1">Page {index + 1}</span>
            </button>
            <div className="flex justify-center gap-1 mt-1">
              <button title="Move up" disabled={index === 0} onClick={() => movePage(page.id, -1)} className="p-1 text-text-muted hover:text-text-primary disabled:opacity-30">↑</button>
              <button title="Move down" disabled={index === project.pages.length - 1} onClick={() => movePage(page.id, 1)} className="p-1 text-text-muted hover:text-text-primary disabled:opacity-30">↓</button>
              <button title="Duplicate" onClick={() => duplicate(page.id)} className="p-1 text-text-muted hover:text-text-primary"><Copy size={11} /></button>
              <button title="Delete" disabled={project.pages.length === 1} onClick={() => remove(page.id)} className="p-1 text-text-muted hover:text-red-400 disabled:opacity-30"><Trash2 size={11} /></button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}

function AssetsPanel() {
  const outputs = useStore(state => state.outputs)
  const loadOutputs = useStore(state => state.loadOutputs)
  const assets = useComicStore(state => state.project.assets)
  const fileRef = useRef<HTMLInputElement>(null)
  const [source, setSource] = useState<'maestro' | 'project'>('maestro')
  const [busy, setBusy] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [provider, setProvider] = useState<'maestro' | 'minimax'>('maestro')
  const [generationError, setGenerationError] = useState('')
  const images = outputs.filter(output => output.type === 'image')
  useEffect(() => { if (!outputs.length) loadOutputs() }, [loadOutputs, outputs.length])

  const uploadFiles = async (files: FileList | null) => {
    if (!files?.length) return
    setBusy(true)
    try {
      for (const file of Array.from(files)) {
        const uploaded = await api.uploadImage(file)
        insertAssetIntoPage({
          id: comicId('asset'),
          name: file.name,
          kind: 'upload',
          source: uploaded.url,
          createdAt: new Date().toISOString(),
        })
      }
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const generateOne = async () => {
    if (!prompt.trim()) return
    setBusy(true)
    setGenerationError('')
    try {
      const model = useStore.getState().selectedModelPerMode.image
      insertAssetIntoPage(await generatePanelAsset(provider, prompt.trim(), model))
      await useStore.getState().loadOutputs()
      setPrompt('')
    } catch (error) {
      setGenerationError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-1">
        <button className={`${button} ${source === 'maestro' ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setSource('maestro')}>Maestro</button>
        <button className={`${button} ${source === 'project' ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setSource('project')}>Project</button>
      </div>
      <button className={`${button} w-full`} onClick={() => fileRef.current?.click()} disabled={busy}>
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} Upload images
      </button>
      <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={event => uploadFiles(event.target.files)} />
      <div className="rounded-lg border border-border bg-bg-tertiary/40 p-2 space-y-2">
        <div className="grid grid-cols-2 gap-1">
          <button className={`${button} ${provider === 'maestro' ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setProvider('maestro')}>Maestro local</button>
          <button className={`${button} ${provider === 'minimax' ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setProvider('minimax')}>MiniMax</button>
        </div>
        <textarea className={input} rows={3} value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="Describe this panel image…" />
        <button className={`${button} w-full`} disabled={busy || !prompt.trim()} onClick={generateOne}>
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Generate into selection
        </button>
        {generationError && <p className="text-[10px] text-red-400">{generationError}</p>}
      </div>
      <p className="text-[10px] text-text-muted">Select a panel first to fill it. Without a panel, the image is placed freely.</p>
      <div className="grid grid-cols-2 gap-2 max-h-[58vh] overflow-y-auto pr-1">
        {(source === 'maestro' ? images : Object.values(assets)).map(item => {
          const asset = 'kind' in item ? item : assetFromOutput(item)
          return (
            <button
              key={'kind' in item ? item.id : item.name}
              onClick={() => insertAssetIntoPage(asset)}
              className="rounded-md overflow-hidden border border-border bg-bg-tertiary hover:border-accent-blue text-left"
              title={asset.name}
            >
              <img src={asset.thumbnail || asset.source} alt="" className="w-full aspect-square object-cover" loading="lazy" />
              <span className="block truncate p-1 text-[9px] text-text-muted">{asset.name}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-[10px] text-text-muted"><span className="mb-1 block">{label}</span>{children}</label>
}

function InspectorPanel() {
  const project = useComicStore(state => state.project)
  const pageId = useComicStore(state => state.currentPageId)
  const selectedId = useComicStore(state => state.selectedId)
  const update = useComicStore(state => state.updateElement)
  const updatePage = useComicStore(state => state.updatePage)
  const patchProject = useComicStore(state => state.patchProject)
  const remove = useComicStore(state => state.removeElement)
  const addElement = useComicStore(state => state.addElement)
  const page = project.pages.find(item => item.id === pageId)
  const element = page?.elements.find(item => item.id === selectedId)
  const patch = (next: Partial<ComicElement>) => element && update(pageId, element.id, next, true)
  const detachFromPanel = () => {
    if (!page || !element?.parentId) return
    const parent = page.elements.find(item => item.id === element.parentId && item.type === 'panel')
    update(pageId, element.id, {
      parentId: null,
      x: element.x + (parent?.x ?? 0),
      y: element.y + (parent?.y ?? 0),
    }, true)
  }

  const addText = (
    bubble: ComicTextElement['bubble'] = 'speech',
    content = 'Your text',
  ) => {
    if (!page) return
    const selectedPanel = element?.type === 'panel' ? element : undefined
    const text: ComicTextElement = {
      id: comicId('text'), type: 'text', parentId: selectedPanel?.id ?? null,
      x: selectedPanel ? selectedPanel.width * .15 : page.width * .25,
      y: selectedPanel ? selectedPanel.height * .7 : page.height * .4,
      width: selectedPanel ? selectedPanel.width * .7 : page.width * .5,
      height: 100, rotation: 0, zIndex: 30, visible: true,
      content, fontSize: bubble === 'scream' || bubble === 'electric' ? 34 : 22, fontFamily: project.style.fontFamily,
      color: '#111111', bold: false, italic: bubble === 'thought' || bubble === 'whisper', align: 'center',
      bubble,
      bubbleBackground: bubble === 'caption' ? '#fff2a8' : bubble === 'electric' ? '#fde047' : '#ffffff',
      bubbleStrokeColor: '#111111', bubbleStrokeWidth: 3,
      tail: bubble === 'speech' || bubble === 'thought' ? 'bottom' : 'none',
    }
    addElement(page.id, text)
  }
  const addPanels = (count: number) => {
    if (!page) return
    const withoutPanels = page.elements.filter(item => item.type !== 'panel' && !item.parentId)
    useComicStore.getState().updatePage(page.id, { elements: [...withoutPanels, ...panelsForCount(page, count)] })
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-1">
        <button className={button} onClick={() => addPanels(4)}><PanelTop size={13} /> 4 panels</button>
        <button className={button} onClick={() => addText()}><Type size={13} /> Add text</button>
      </div>
      <div className="grid grid-cols-4 gap-1">
        {[1, 3, 6, 9].map(count => <button key={count} className={button} onClick={() => addPanels(count)}>{count}</button>)}
      </div>
      <div className="grid grid-cols-2 gap-1">
        <button className={button} onClick={() => addText('thought', 'I am thinking…')}>Thought</button>
        <button className={button} onClick={() => addText('caption', 'Meanwhile…')}>Caption</button>
        <button className={button} onClick={() => addText('whisper', 'Speak softly…')}>Whisper</button>
        <button className={button} onClick={() => addText('electric', 'WATCH OUT!')}>Shout</button>
      </div>
      {!element ? (
        <div className="space-y-3">
          <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-text-muted">
            Page settings · select an element for its inspector.
          </div>
          <Field label="Page preset">
            <select
              className={input}
              value=""
              onChange={event => {
                if (!page) return
                const sizes: Record<string, [number, number]> = {
                  a4: [800, 1131],
                  'a4-landscape': [1131, 800],
                  square: [1080, 1080],
                  webtoon: [800, 2400],
                }
                const size = sizes[event.target.value]
                if (size) updatePage(page.id, { width: size[0], height: size[1] })
              }}
            >
              <option value="">Choose…</option>
              <option value="a4">A4 portrait</option>
              <option value="a4-landscape">A4 landscape</option>
              <option value="square">Square</option>
              <option value="webtoon">Webtoon</option>
            </select>
          </Field>
          {page && (
            <div className="grid grid-cols-2 gap-2">
              <Field label="Width"><input className={input} type="number" value={page.width} onChange={event => updatePage(page.id, { width: Math.max(200, Number(event.target.value)) })} /></Field>
              <Field label="Height"><input className={input} type="number" value={page.height} onChange={event => updatePage(page.id, { height: Math.max(200, Number(event.target.value)) })} /></Field>
              <Field label="Background"><input className="h-8 w-full" type="color" value={page.background} onChange={event => updatePage(page.id, { background: event.target.value })} /></Field>
            </div>
          )}
          <Field label="Page numbers">
            <select className={input} value={project.pageNumbering.style} onChange={event => patchProject({ pageNumbering: { style: event.target.value as 'none' | 'plain' | 'circle' } })}>
              <option value="none">None</option>
              <option value="plain">Plain</option>
              <option value="circle">Circle</option>
            </select>
          </Field>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <strong className="text-xs capitalize text-text-primary">{element.type}</strong>
            <div className="flex gap-1">
              <button className={button} title="Duplicate (Ctrl+D)" onClick={() => useComicStore.getState().duplicateElement(pageId, element.id)}><Copy size={12} /></button>
              <button className={button} onClick={() => patch({ locked: !element.locked })}>{element.locked ? <Unlock size={12} /> : <Lock size={12} />}</button>
              <button className={`${button} hover:text-red-400`} onClick={() => remove(pageId, element.id)}><Trash2 size={12} /></button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {(['x', 'y', 'width', 'height', 'rotation', 'zIndex'] as const).map(key => (
              <Field key={key} label={key}>
                <input className={input} type="number" value={Math.round(Number(element[key]))}
                  onChange={event => patch({ [key]: Number(event.target.value) } as Partial<ComicElement>)} />
              </Field>
            ))}
          </div>
          <label className="flex items-center justify-between text-xs text-text-secondary">
            Visible
            <button onClick={() => patch({ visible: element.visible === false })}>{element.visible === false ? <EyeOff size={15} /> : <Eye size={15} />}</button>
          </label>
          <div className="grid grid-cols-2 gap-1">
            <button className={button} onClick={() => patch({ zIndex: Math.max(...(page?.elements.map(item => item.zIndex) ?? [0])) + 1 })}>Bring front</button>
            <button className={button} onClick={() => patch({ zIndex: Math.min(...(page?.elements.map(item => item.zIndex) ?? [0])) - 1 })}>Send back</button>
          </div>
          {element.type === 'panel' && (
            <div className="space-y-2">
              <Field label="Border width"><input className={input} type="number" min={0} max={30} value={element.borderWidth} onChange={event => patch({ borderWidth: Number(event.target.value) })} /></Field>
              <Field label="Border color"><input className="w-full h-8" type="color" value={element.borderColor} onChange={event => patch({ borderColor: event.target.value })} /></Field>
              <Field label="Corner radius"><input className={input} type="number" value={element.borderRadius} onChange={event => patch({ borderRadius: Number(event.target.value) })} /></Field>
              <Field label="Background"><input className="w-full h-8" type="color" value={element.background === 'transparent' ? '#ffffff' : element.background} onChange={event => patch({ background: event.target.value })} /></Field>
              <div className="grid grid-cols-2 gap-1">
                <button className={button} onClick={() => patch({ background: 'transparent' })}>Transparent</button>
                <button
                  className={`${button} ${element.points ? 'border-accent-blue text-accent-blue' : ''}`}
                  onClick={() => patch({ points: element.points ? undefined : [[0, 0], [1, 0], [1, 1], [0, 1]] })}
                >
                  {element.points ? 'Rectangle' : 'Polygon'}
                </button>
              </div>
            </div>
          )}
          {element.type === 'image' && (
            <div className="space-y-2">
              <Field label="Fit"><select className={input} value={element.objectFit} onChange={event => patch({ objectFit: event.target.value as ComicImageElement['objectFit'] })}><option value="cover">Fill panel</option><option value="contain">Show entire image</option></select></Field>
              <Field label="Filter"><select className={input} value={element.filter} onChange={event => patch({ filter: event.target.value as ComicImageElement['filter'] })}><option value="none">None</option><option value="bw">Black & white</option><option value="sepia">Sepia</option><option value="contrast">Comic contrast</option><option value="posterize">Posterize</option><option value="halftone">Halftone</option></select></Field>
              <Field label="Opacity"><input className={input} type="range" min={0} max={1} step={.05} value={element.opacity ?? 1} onChange={event => patch({ opacity: Number(event.target.value) })} /></Field>
              <div className="grid grid-cols-2 gap-1">
                <button className={`${button} ${element.flipH ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => patch({ flipH: !element.flipH })}>Flip H</button>
                <button className={`${button} ${element.flipV ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => patch({ flipV: !element.flipV })}>Flip V</button>
              </div>
              {element.parentId && (
                <button className={`${button} w-full`} onClick={detachFromPanel}>Remove from panel</button>
              )}
            </div>
          )}
          {element.type === 'text' && (
            <div className="space-y-2">
              <Field label="Text"><textarea className={input} rows={4} value={element.content} onChange={event => patch({ content: event.target.value })} /></Field>
              <Field label="Bubble"><select className={input} value={element.bubble} onChange={event => patch({ bubble: event.target.value as ComicTextElement['bubble'] })}><option value="none">None / SFX</option><option value="speech">Speech</option><option value="ellipse">Ellipse</option><option value="rect">Rounded rectangle</option><option value="thought">Thought</option><option value="whisper">Whisper</option><option value="caption">Caption</option><option value="scream">Scream</option><option value="electric">Electric</option><option value="burst">Burst</option><option value="cloud">Cloud</option></select></Field>
              <Field label="Font size"><input className={input} type="number" value={element.fontSize} onChange={event => patch({ fontSize: Number(event.target.value) })} /></Field>
              <Field label="Font"><select className={input} value={element.fontFamily} onChange={event => patch({ fontFamily: event.target.value })}><option value='"Comic Sans MS", "Trebuchet MS", sans-serif'>Comic</option><option value='"Arial Black", Impact, sans-serif'>Impact</option><option value='Georgia, serif'>Classic serif</option><option value='"Courier New", monospace'>Typewriter</option><option value='Arial, sans-serif'>Clean sans</option></select></Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Line height"><input className={input} type="number" min={0.7} max={2} step={.05} value={element.lineHeight ?? 1.08} onChange={event => patch({ lineHeight: Number(event.target.value) })} /></Field>
                <Field label="Spacing"><input className={input} type="number" min={-8} max={30} value={element.letterSpacing ?? 0} onChange={event => patch({ letterSpacing: Number(event.target.value) })} /></Field>
                <Field label="Text color"><input className="w-full h-8" type="color" value={element.color} onChange={event => patch({ color: event.target.value })} /></Field>
                <Field label="Outline"><input className={input} type="number" min={0} max={8} value={element.textStrokeWidth ?? 0} onChange={event => patch({ textStrokeWidth: Number(event.target.value) })} /></Field>
              </div>
              <Field label="Text effect"><select className={input} value={element.textEffect ?? 'none'} onChange={event => patch({ textEffect: event.target.value as ComicTextElement['textEffect'] })}><option value="none">None</option><option value="shadow">Shadow</option><option value="extrude">3D extrude</option><option value="glow">Glow</option></select></Field>
              <Field label="Fill"><select className={input} value={element.textFill ?? 'solid'} onChange={event => patch({ textFill: event.target.value as ComicTextElement['textFill'] })}><option value="solid">Solid</option><option value="gradient">Gradient</option></select></Field>
              <div className="grid grid-cols-2 gap-1">
                <button className={`${button} ${element.bold ? 'border-accent-blue' : ''}`} onClick={() => patch({ bold: !element.bold })}>Bold</button>
                <button className={`${button} ${element.italic ? 'border-accent-blue' : ''}`} onClick={() => patch({ italic: !element.italic })}>Italic</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

const initialDirector = (): ComicDirectorRequest => ({
  premise: '',
  pageCount: 4,
  language: 'English',
  format: 'a4',
  panelsPerPage: 4,
  genre: 'Adventure',
  tone: 'Cinematic',
  audience: 'General',
  artStyle: '',
  worldContext: '',
  forbiddenElements: '',
  dialogueDensity: 'medium',
  provider: 'maestro',
  imageModel: useStore.getState().selectedModelPerMode.image || 'flux2_klein_9b',
  characters: [],
})

const COMIC_GENRES = [
  'Adventure', 'Action', 'Comedy', 'Drama', 'Fantasy', 'Science fiction',
  'Horror', 'Mystery', 'Thriller', 'Romance', 'Superhero', 'Historical',
  'Crime', 'Slice of life', 'Western', 'Cyberpunk', 'Noir', 'Satire',
]

const COMIC_TONES = [
  'Cinematic', 'Epic', 'Lighthearted', 'Dark', 'Humorous', 'Dramatic',
  'Suspenseful', 'Emotional', 'Hopeful', 'Gritty', 'Whimsical', 'Mysterious',
  'Romantic', 'Melancholic', 'Satirical', 'Family-friendly',
]

function SuggestedChoice({
  value,
  options,
  onChange,
  customPlaceholder,
}: {
  value: string
  options: string[]
  onChange: (value: string) => void
  customPlaceholder: string
}) {
  const custom = !options.includes(value)
  return (
    <div className="space-y-1.5">
      <select
        className={input}
        value={custom ? '__other__' : value}
        onChange={event => onChange(event.target.value === '__other__' ? '' : event.target.value)}
      >
        {options.map(option => <option key={option} value={option}>{option}</option>)}
        <option value="__other__">Other…</option>
      </select>
      {custom && (
        <input
          className={input}
          value={value}
          onChange={event => onChange(event.target.value)}
          placeholder={customPlaceholder}
          autoFocus
        />
      )}
    </div>
  )
}

export function ComicDirectorPanel({
  notify = () => {},
  createCompleteComic = false,
}: {
  notify?: (notice: Notice) => void
  createCompleteComic?: boolean
}) {
  const project = useComicStore(state => state.project)
  const [request, setRequest] = useState<ComicDirectorRequest>(() =>
    project.director?.input ?? { ...initialDirector(), characters: project.characters })
  const [busy, setBusy] = useState<'plan' | 'images' | 'text' | 'translation' | null>(null)
  const [progress, setProgress] = useState('')
  const [textInstruction, setTextInstruction] = useState('')
  const [targetLanguage, setTargetLanguage] = useState('')
  const [activity, setActivity] = useState<DirectorActivity>({
    state: 'idle',
    message: 'Ready to create your comic.',
    steps: [],
  })
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [newCharacter, setNewCharacter] = useState({ name: '', description: '' })
  const [singleBusy, setSingleBusy] = useState<string | null>(null)
  const [pendingPlan, setPendingPlan] = useState<ComicPlan | null>(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem('maestro-last-comic-plan-result') || 'null')
      return saved?.plan ? normalizeComicPlan(saved.plan as ComicPlan, request.dialogueDensity) : null
    } catch {
      return null
    }
  })
  const [recoveryJobId, setRecoveryJobId] = useState(() => {
    try {
      return window.localStorage.getItem('maestro-last-comic-plan-job') || ''
    } catch {
      return ''
    }
  })
  const maestroModels = useStore(state => state.models)
  const servicesConfig = useStore(state => state.servicesConfig)
  const llmStatus = useStore(state => state.llmStatus)
  const maestroImageModels = useMemo(
    () => maestroModels.filter(model =>
      !model.tool_only && getModelMode(model.model_type, model.family) === 'image'),
    [maestroModels],
  )
  const installedMaestroImageModels = useMemo(
    () => maestroImageModels.filter(model => model.is_downloaded !== false),
    [maestroImageModels],
  )
  const totalPlannedPanels = project.director?.plan.pages.reduce(
    (total, page) => total + page.panels.length,
    0,
  ) ?? 0
  const remainingPanels = Math.max(
    0,
    totalPlannedPanels - (project.director?.completedPanelIds.length ?? 0),
  )
  const hasBrokenEncoding = project.director
    ? /[ÃÂâ]/.test(JSON.stringify(project.director.plan))
    : false
  const planningLlmProvider = servicesConfig?.llm_provider || llmStatus?.provider || 'local'
  const planningLlmProviderLabel: Record<string, string> = {
    local: 'Local llama-server',
    remote: 'Remote OpenAI-compatible',
    openai: 'Hosted OpenAI-compatible',
    anthropic: 'Anthropic API',
  }
  const planningLlmModel = servicesConfig?.llm_model_id || llmStatus?.model_id || 'Loading configuration…'
  const planningLlmIsActive = Boolean(
    llmStatus?.loaded
    && llmStatus.model_id === planningLlmModel
    && (!llmStatus.provider || llmStatus.provider === planningLlmProvider),
  )
  useEffect(() => {
    setRequest(project.director?.input ?? { ...initialDirector(), characters: project.characters })
  }, [project.id])
  useEffect(() => {
    if (!startedAt || busy === null) return
    const updateElapsed = () => setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000))
    updateElapsed()
    const timer = window.setInterval(updateElapsed, 1000)
    return () => window.clearInterval(timer)
  }, [busy, startedAt])
  const patch = <K extends keyof ComicDirectorRequest>(key: K, value: ComicDirectorRequest[K]) => {
    setRequest(current => ({ ...current, [key]: value }))
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const nextInput = { ...director.input, [key]: value }
    state.patchProject({
      director: {
        ...director,
        provider: key === 'provider' ? value as ComicDirectorRequest['provider'] : director.provider,
        imageModel: key === 'imageModel' ? value as string : director.imageModel,
        input: nextInput,
        // A pending Maestro job belongs to the previous provider/model choice.
        panelJobs: key === 'provider' || key === 'imageModel' ? {} : director.panelJobs,
      },
    })
  }
  useEffect(() => {
    if (request.provider !== 'maestro' || installedMaestroImageModels.length === 0) return
    const selectedIsInstalledImage = installedMaestroImageModels.some(
      model => model.model_type === request.imageModel,
    )
    if (!selectedIsInstalledImage) {
      const preferred = installedMaestroImageModels.find(
        model => model.model_type === 'flux2_klein_9b',
      ) || installedMaestroImageModels[0]
      patch('imageModel', preferred.model_type)
    }
  }, [request.provider, request.imageModel, installedMaestroImageModels])
  const report = (
    message: string,
    options: Partial<Pick<DirectorActivity, 'state' | 'current' | 'total'>> = {},
  ) => {
    setActivity(current => ({
      state: options.state ?? 'running',
      message,
      current: options.current,
      total: options.total,
      steps: current.steps.at(-1) === message
        ? current.steps
        : [...current.steps.slice(-5), message],
    }))
  }

  const addCharacter = () => {
    if (!newCharacter.name.trim() || !newCharacter.description.trim()) return
    const character: ComicCharacter = {
      id: comicId('character'),
      name: newCharacter.name.trim(),
      description: newCharacter.description.trim(),
      locked: true,
    }
    patch('characters', [...request.characters, character])
    setNewCharacter({ name: '', description: '' })
  }

  const repairCurrentPlanEncoding = () => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    state.patchProject({
      director: {
        ...director,
        plan: repairComicText(director.plan),
      },
    })
    report('Spanish text encoding repaired in the current plan.', { state: 'complete' })
  }

  const rememberPanelJob = (panelId: string, jobId?: string) => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const panelJobs = { ...(director.panelJobs || {}) }
    if (jobId) panelJobs[panelId] = jobId
    else delete panelJobs[panelId]
    state.patchProject({ director: { ...director, panelJobs } })
  }

  const generateAll = async (force = false): Promise<boolean> => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return false
    const tasks: Array<{ pageId: string; panel: ComicPanelElement; plan: ComicPlanPanel }> = []
    director.plan.pages.forEach((planPage, pageIndex) => {
      const page = state.project.pages[pageIndex]
      const panels = page?.elements.filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
        .sort((a, b) => a.zIndex - b.zIndex) || []
      planPage.panels.forEach((planned, index) => {
        if ((force || !director.completedPanelIds.includes(planned.id)) && panels[index]) {
          tasks.push({ pageId: page.id, panel: panels[index], plan: planned })
        }
      })
    })
    setBusy('images')
    if (!tasks.length) {
      report('All panels already have artwork.', { state: 'complete' })
      setBusy(null)
      return true
    }
    try {
      for (let index = 0; index < tasks.length; index++) {
        const task = tasks[index]
        report(`Generating artwork for panel ${index + 1} of ${tasks.length} with ${
          director.provider === 'minimax' ? 'MiniMax' : 'Maestro'
        }…`, { current: index + 1, total: tasks.length })
        setProgress(`Generating panel ${index + 1} / ${tasks.length}`)
        const character = director.plan.characters.find(item => task.plan.characters.includes(item.id))
        const reference = character?.referenceAssetId
          ? useComicStore.getState().project.assets[character.referenceAssetId]?.source
          : undefined
        const currentDirector = useComicStore.getState().project.director!
        const prompt = buildDirectorImagePrompt(
          currentDirector,
          task.plan.imagePrompt,
          state.project.style.promptSuffix,
        )
        const existingJobId = currentDirector.panelJobs?.[task.plan.id]
        let asset: ComicAsset | null = null
        if (
          currentDirector.provider === 'maestro' &&
          !existingJobId &&
          currentDirector.completedPanelIds.length > 0 &&
          currentDirector.imageModel
        ) {
          const assignedNames = new Set(Object.values(
            useComicStore.getState().project.assets,
          ).map(item => item.name))
          asset = await findCompletedLocalImage(
            prompt,
            currentDirector.imageModel,
            assignedNames,
          )
          if (asset) {
            report(`Recovered finished artwork for panel ${index + 1} from Maestro outputs.`, {
              current: index + 1,
              total: tasks.length,
            })
          }
        }
        if (!asset) {
          if (existingJobId) {
            report(`Reconnecting to Maestro job ${existingJobId} for panel ${index + 1}…`, {
              current: index + 1,
              total: tasks.length,
            })
          }
          asset = await generatePanelAsset(
            currentDirector.provider,
            prompt,
            currentDirector.imageModel,
            reference,
            {
              panelId: task.plan.id,
              existingJobId,
              onJobSubmitted: jobId => rememberPanelJob(task.plan.id, jobId),
              onPollRetry: attempt => report(
                `Connection interrupted while checking panel ${index + 1}; retrying (${attempt}/20)…`,
                { current: index + 1, total: tasks.length },
              ),
            },
          )
        }
        const latest = useComicStore.getState()
        const latestPage = latest.project.pages.find(page => page.id === task.pageId)
        latestPage?.elements
          .filter(element => element.parentId === task.panel.id && element.type === 'image')
          .forEach(element => latest.removeElement(task.pageId, element.id))
        latest.addAsset(asset)
        latest.addElement(task.pageId, {
          id: comicId('image'), type: 'image', assetId: asset.id, parentId: task.panel.id,
          x: 0, y: 0, width: task.panel.width, height: task.panel.height,
          rotation: 0, zIndex: 2, objectFit: 'cover', filter: 'none', opacity: 1, visible: true,
        })
        latest.patchProject({
          director: {
            ...latest.project.director!,
            completedPanelIds: Array.from(new Set([
              ...latest.project.director!.completedPanelIds,
              task.plan.id,
            ])),
            panelJobs: Object.fromEntries(
              Object.entries(latest.project.director!.panelJobs || {})
                .filter(([panelId]) => panelId !== task.plan.id),
            ),
          },
        })
        report(`Panel ${index + 1} of ${tasks.length} generated and placed.`, {
          current: index + 1,
          total: tasks.length,
        })
        await useStore.getState().loadOutputs()
      }
      report(`Comic complete: ${tasks.length} panel images generated and placed.`, {
        state: 'complete',
        current: tasks.length,
        total: tasks.length,
      })
      notify({ kind: 'ok', text: 'All Director panels were generated and placed.' })
      useStore.getState().loadOutputs()
      return true
    } catch (error) {
      const message = `${(error as Error).message}. Completed panels are preserved; run again to resume.`
      report(message, { state: 'error' })
      notify({ kind: 'error', text: message })
      return false
    } finally {
      setBusy(null)
      setProgress('')
    }
  }

  const cleanUpCurrentComicText = () => {
    const state = useComicStore.getState()
    state.patchProject(simplifyDirectorText(state.project))
    notify({ kind: 'ok', text: 'Lettering simplified without regenerating artwork.' })
    report('Lettering repaired: silent beats and compact panel text now preserve the artwork.', {
      state: 'complete',
    })
  }

  const transformTextPlan = async (mode: 'rewrite' | 'translate'): Promise<ComicPlan> => {
    const current = useComicStore.getState().project
    const captured = planWithCanvasText(current)
    if (!captured) throw new Error('This comic does not have an editable Director plan')
    const working = structuredClone(captured)
    for (let pageIndex = 0; pageIndex < working.pages.length; pageIndex += 1) {
      report(`${mode === 'translate' ? 'Translating' : 'Rewriting'} page ${pageIndex + 1} of ${working.pages.length}…`, {
        current: pageIndex + 1,
        total: working.pages.length,
      })
      const result = await api.rewriteComicTextPage({
        plan: working,
        pageIndex,
        mode,
        instruction: textInstruction,
        targetLanguage,
        dialogueDensity: current.director!.input.dialogueDensity,
      })
      working.pages[pageIndex] = result.page
    }
    if (mode === 'translate') working.language = targetLanguage.trim()
    return normalizeComicPlan(working, current.director!.input.dialogueDensity)
  }

  const applyTextOperation = async (mode: 'rewrite' | 'translate') => {
    if (mode === 'translate' && !targetLanguage.trim()) return
    setBusy(mode === 'translate' ? 'translation' : 'text')
    try {
      const state = useComicStore.getState()
      const plan = await transformTextPlan(mode)
      const translated = mode === 'translate'
      const next = simplifyDirectorText({
        ...state.project,
        language: translated ? targetLanguage.trim() : state.project.language,
        director: { ...state.project.director!, plan },
      })
      state.patchProject(next)
      report(`${translated ? `Translation to ${targetLanguage.trim()}` : 'Text rewrite'} applied without changing artwork.`, {
        state: 'complete',
      })
      notify({ kind: 'ok', text: translated
        ? `Comic text translated to ${targetLanguage.trim()} and left editable.`
        : 'Comic text rewritten without regenerating images.' })
    } catch (error) {
      report((error as Error).message, { state: 'error' })
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setBusy(null)
    }
  }

  const exportTranslatedPdf = async () => {
    if (!targetLanguage.trim()) return
    setBusy('translation')
    const state = useComicStore.getState()
    const originalPageId = state.currentPageId
    let temporaryApplied = false
    try {
      const plan = await transformTextPlan('translate')
      const translatedProject = simplifyDirectorText({
        ...state.project,
        title: `${state.project.title} — ${targetLanguage.trim()}`,
        language: targetLanguage.trim(),
        director: { ...state.project.director!, plan },
      })
      state.patchProject(translatedProject)
      temporaryApplied = true
      await wait(100)
      await exportComicPdf((current, total) =>
        report(`Exporting translated PDF page ${current} of ${total}…`, { current, total }))
      report(`PDF exported in ${targetLanguage.trim()}; the editable comic was restored.`, {
        state: 'complete',
      })
      notify({ kind: 'ok', text: `Translated PDF exported in ${targetLanguage.trim()}.` })
    } catch (error) {
      report((error as Error).message, { state: 'error' })
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      if (temporaryApplied) {
        useComicStore.getState().undo()
        if (originalPageId) useComicStore.getState().setCurrentPage(originalPageId)
      }
      setBusy(null)
    }
  }

  const commitPanelText = (pageIndex: number, panelIndex: number, value: string) => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const plan = structuredClone(director.plan)
    Object.assign(plan.pages[pageIndex].panels[panelIndex], parsePanelScript(value))
    state.patchProject(simplifyDirectorText({
      ...state.project,
      director: { ...director, plan },
    }))
  }

  const varyCurrentLayouts = () => {
    const state = useComicStore.getState()
    state.patchProject(varyDirectorLayouts(state.project))
    notify({ kind: 'ok', text: 'Page layouts varied without regenerating artwork.' })
  }

  const regenerateAllArtwork = async () => {
    if (!window.confirm(
      `Regenerate all ${totalPlannedPanels} panel images? This may use paid image-provider credits. Existing artwork is kept until each replacement succeeds.`,
    )) return
    await generateAll(true)
  }

  const placePlan = async (rawPlan: ComicPlan, withImages: boolean) => {
      const plan = normalizeComicPlan(rawPlan, request.dialogueDensity)
      setPendingPlan(plan)
      report(`Plan received: ${plan.pages.length} pages and ${
        plan.pages.reduce((total, page) => total + page.panels.length, 0)
      } panels.`)
      const currentProject = useComicStore.getState().project
      const next = projectFromPlan(plan, {
        ...currentProject,
        format: {
          ...currentProject.format,
          preset: request.format,
          ...(request.format !== 'custom' ? COMIC_FORMATS[request.format] : {}),
        },
      })
      next.director = {
        planId: plan.id,
        provider: request.provider,
        imageModel: request.imageModel,
        input: request,
        plan,
        completedPanelIds: [],
        panelJobs: {},
      }
      const comicStore = useComicStore.getState()
      comicStore.setProject(next)
      if (next.pages[0]) comicStore.setCurrentPage(next.pages[0].id)
      useStore.getState().setMediaFilter('comics')
      setPendingPlan(null)
      try {
        window.localStorage.removeItem('maestro-last-comic-plan-result')
      } catch {
        // Private browsing may block storage; the in-memory state is enough.
      }
      report('Pages, panels, dialogue and captions placed in the editor.')
      notify({ kind: 'ok', text: `Director created ${plan.pages.length} editable pages.` })
      if (withImages) {
        report('Opening the comic canvas and starting panel artwork…')
        await new Promise(resolve => window.setTimeout(resolve, 0))
        await generateAll()
      } else {
        report('Editable plan ready. Review it or generate the panel images.', { state: 'complete' })
      }
  }

  const makePlan = async (withImages = false) => {
    if (!request.premise.trim()) return
    setBusy('plan')
    setStartedAt(Date.now())
    setElapsedSeconds(0)
    setActivity({
      state: 'running',
      message: 'Submitting the planning job to Maestro…',
      steps: ['Submitting the planning job to Maestro…'],
    })
    try {
      const { plan } = await api.planComic(request, status => {
        if (status.jobId) setRecoveryJobId(status.jobId)
        report(status.message, {
          current: status.current,
          total: status.total,
        })
      })
      await placePlan(plan, withImages)
    } catch (error) {
      const message = (error as Error).message
      report(message, { state: 'error' })
      notify({ kind: 'error', text: message })
    } finally {
      setBusy(null)
    }
  }

  const recoverPlan = async () => {
    setBusy('plan')
    setStartedAt(Date.now())
    try {
      const jobId = recoveryJobId.trim()
      let plan: ComicPlan | null = null
      // An explicitly entered durable job is authoritative. A stale browser
      // result from an older session must never shadow the ID visible here.
      if (jobId) {
        report(`Recovering completed plan ${jobId} without calling the LLM again…`)
        const job = await api.fetchComicPlanJob(jobId)
        if (job.status === 'completed' && job.result?.plan) {
          plan = job.result.plan
        } else {
          report(`Resuming ${jobId} from its last saved page checkpoint…`)
          await api.resumeComicPlanJob(jobId)
          const result = await api.waitForComicPlanJob(jobId, status => report(status.message, {
            current: status.current,
            total: status.total,
          }))
          plan = result.plan
        }
      } else {
        plan = pendingPlan
      }
      if (!plan) throw new Error('Enter the comic planning job ID to recover')
      await placePlan(plan, createCompleteComic)
    } catch (error) {
      const message = (error as Error).message
      report(message, { state: 'error' })
      notify({ kind: 'error', text: message })
    } finally {
      setBusy(null)
    }
  }

  const updatePlanPanel = (pageIndex: number, panelIndex: number, patchValue: Partial<ComicPlanPanel>) => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const pages = director.plan.pages.map((page, pi) => pi !== pageIndex ? page : {
      ...page,
      panels: page.panels.map((panel, pj) => pj === panelIndex ? { ...panel, ...patchValue } : panel),
    })
    state.patchProject({ director: { ...director, plan: { ...director.plan, pages } } })
  }

  const generateSingle = async (pageIndex: number, panelIndex: number) => {
    const state = useComicStore.getState()
    const director = state.project.director
    const page = state.project.pages[pageIndex]
    const planned = director?.plan.pages[pageIndex]?.panels[panelIndex]
    const panel = page?.elements
      .filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
      .sort((a, b) => a.zIndex - b.zIndex)[panelIndex]
    if (!director || !planned || !panel) return
    setSingleBusy(planned.id)
    try {
      const character = director.plan.characters.find(item => planned.characters.includes(item.id))
      const reference = character?.referenceAssetId
        ? state.project.assets[character.referenceAssetId]?.source
        : undefined
      const existingJobId = director.completedPanelIds.includes(planned.id)
        ? undefined
        : director.panelJobs?.[planned.id]
      const asset = await generatePanelAsset(
        director.provider,
        buildDirectorImagePrompt(director, planned.imagePrompt, state.project.style.promptSuffix),
        director.imageModel,
        reference,
        {
          panelId: planned.id,
          existingJobId,
          onJobSubmitted: jobId => rememberPanelJob(planned.id, jobId),
        },
      )
      const latest = useComicStore.getState()
      const currentPage = latest.project.pages[pageIndex]
      const oldImages = currentPage.elements.filter(element => element.parentId === panel.id && element.type === 'image')
      oldImages.forEach(element => useComicStore.getState().removeElement(currentPage.id, element.id))
      useComicStore.getState().addAsset(asset)
      useComicStore.getState().addElement(currentPage.id, {
        id: comicId('image'), type: 'image', assetId: asset.id, parentId: panel.id,
        x: 0, y: 0, width: panel.width, height: panel.height,
        rotation: 0, zIndex: 2, objectFit: 'cover', filter: 'none', opacity: 1, visible: true,
      })
      const after = useComicStore.getState()
      after.patchProject({
        director: {
          ...after.project.director!,
          completedPanelIds: Array.from(new Set([...after.project.director!.completedPanelIds, planned.id])),
          panelJobs: Object.fromEntries(
            Object.entries(after.project.director!.panelJobs || {})
              .filter(([panelId]) => panelId !== planned.id),
          ),
        },
      })
      notify({ kind: 'ok', text: `Panel ${pageIndex + 1}.${panelIndex + 1} generated.` })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setSingleBusy(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-accent-blue/30 bg-accent-blue/5 p-3">
        <div className="flex items-center gap-2 text-xs font-medium text-text-primary"><WandSparkles size={14} /> Comic Director</div>
        <p className="text-[10px] text-text-muted mt-1">Plan exact pages, editable dialogue and image prompts, then generate every panel locally or with MiniMax.</p>
      </div>
      <div className="rounded-lg border border-border bg-bg-tertiary/30 p-2.5">
        <div className="text-[9px] uppercase tracking-wide text-text-muted">Planning LLM</div>
        <div className="mt-1 text-[11px] text-text-primary">
          Maestro default · {planningLlmProviderLabel[planningLlmProvider] || planningLlmProvider} · {planningLlmModel}
        </div>
        <div className="mt-0.5 text-[9px] text-text-muted">
          {planningLlmIsActive
            ? 'Active now'
            : llmStatus?.loaded
              ? `Will switch from ${llmStatus.model_id || 'the currently loaded model'} when planning starts`
              : 'Auto-loads when planning starts'}
        </div>
      </div>
      <Field label="Story premise"><textarea className={input} rows={5} value={request.premise} onChange={event => patch('premise', event.target.value)} placeholder="What happens in the comic?" /></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Pages"><input className={input} type="number" min={1} max={100} value={request.pageCount} onChange={event => patch('pageCount', Math.max(1, Number(event.target.value)))} /></Field>
        <Field label="Panels / page"><input className={input} type="number" min={1} max={12} value={request.panelsPerPage} onChange={event => patch('panelsPerPage', Math.max(1, Number(event.target.value)))} /></Field>
        <Field label="Language"><input className={input} value={request.language} onChange={event => patch('language', event.target.value)} /></Field>
        <Field label="Format"><select className={input} value={request.format} onChange={event => patch('format', event.target.value as ComicDirectorRequest['format'])}>{Object.entries(COMIC_FORMATS).map(([id, value]) => <option key={id} value={id}>{value.label}</option>)}</select></Field>
        <Field label="Genre">
          <SuggestedChoice
            value={request.genre}
            options={COMIC_GENRES}
            onChange={value => patch('genre', value)}
            customPlaceholder="Write a custom or hybrid genre"
          />
        </Field>
        <Field label="Tone">
          <SuggestedChoice
            value={request.tone}
            options={COMIC_TONES}
            onChange={value => patch('tone', value)}
            customPlaceholder="Write a custom tone"
          />
        </Field>
        <Field label="Dialogue density">
          <select
            className={input}
            value={request.dialogueDensity}
            onChange={event => patch('dialogueDensity', event.target.value as ComicDirectorRequest['dialogueDensity'])}
          >
            <option value="low">Low — text in about 30% of panels</option>
            <option value="medium">Medium — text in about 55%, with silent beats</option>
            <option value="high">High — text in about 80%, still readable</option>
          </select>
        </Field>
      </div>
      <Field label="Art style override (optional)"><input
        className={input}
        value={request.artStyle}
        onChange={event => patch('artStyle', event.target.value)}
        placeholder="Leave blank and Comic Director will choose"
      /></Field>
      <Field label="World / period / location override (optional)">
        <textarea
          className={input}
          rows={3}
          value={request.worldContext || ''}
          onChange={event => patch('worldContext', event.target.value)}
          placeholder="Example: Castile and Atlantic ports, 1492; late-15th-century ships, clothing, tools, masonry and interiors only."
        />
      </Field>
      <Field label="Forbidden elements / visual rules (optional)">
        <textarea
          className={input}
          rows={2}
          value={request.forbiddenElements || ''}
          onChange={event => patch('forbiddenElements', event.target.value)}
          placeholder="Example: no engines, electric lights, modern glass, zippers, plastics, modern typography or 18th-century uniforms."
        />
      </Field>
      <p className="text-[9px] text-text-muted">
        Blank fields delegate the decision to the LLM. It creates a visual bible only when useful;
        an empty bible is not sent to the image generator.
      </p>
      <Field label="Image generator (active queue)"><select
        disabled={busy !== null}
        className={input}
        value={request.provider === 'minimax'
          ? 'minimax:image-01'
          : `maestro:${request.imageModel || ''}`}
        onChange={event => {
          const [provider, ...modelParts] = event.target.value.split(':')
          if (provider === 'minimax') {
            patch('provider', 'minimax')
            return
          }
          patch('provider', 'maestro')
          patch('imageModel', modelParts.join(':'))
        }}
      >
        <optgroup label="External services">
          <option value="minimax:image-01">MiniMax image-01 · external API</option>
        </optgroup>
        <optgroup label="Installed locally and ready">
          {request.provider === 'maestro' && request.imageModel
            && !installedMaestroImageModels.some(model => model.model_type === request.imageModel) && (
            <option value={`maestro:${request.imageModel}`}>
              {request.imageModel} — incompatible/non-image
            </option>
          )}
          {installedMaestroImageModels.map(model => (
            <option key={model.model_type} value={`maestro:${model.model_type}`}>
              {model.name} · local
            </option>
          ))}
        </optgroup>
        {maestroImageModels.some(model => model.is_downloaded === false) && (
          <optgroup label="Not downloaded — install in Settings → Models">
            {maestroImageModels.filter(model => model.is_downloaded === false).map(model => (
              <option disabled key={model.model_type} value={`maestro:${model.model_type}`}>
                {model.name}
              </option>
            ))}
          </optgroup>
        )}
      </select>
      <p className="mt-1 text-[9px] text-text-muted">
        Local entries run through Maestro in image mode. MiniMax is an external image generator
        in the same queue and uses the configured MiniMax API key.
      </p>
      </Field>
      {request.provider === 'minimax' && (
        <p className="text-[9px] text-text-muted">
          MiniMax references preserve a character's identity; they are not a general style-reference control.
        </p>
      )}
      {project.director && (
        <p className="rounded border border-border bg-bg-tertiary/40 px-2 py-1.5 text-[9px] text-text-muted">
          Current plan will generate with <b className="text-text-primary">
            {project.director.provider === 'minimax'
              ? 'MiniMax image-01'
              : `Maestro · ${project.director.imageModel || 'no image model selected'}`}
          </b>.
        </p>
      )}
      <div className="border-t border-border pt-3 space-y-2">
        <strong className="text-[10px] uppercase tracking-wide text-text-muted">Characters</strong>
        {request.characters.map(character => (
          <div key={character.id} className="rounded border border-border p-2 text-[10px]">
            <div className="flex justify-between"><b className="text-text-primary">{character.name}</b><button onClick={() => patch('characters', request.characters.filter(item => item.id !== character.id))}><Trash2 size={11} /></button></div>
            <p className="text-text-muted mt-1">{character.description}</p>
            <select
              className={`${input} mt-2`}
              value={character.referenceAssetId || ''}
              onChange={event => patch('characters', request.characters.map(item => item.id === character.id
                ? { ...item, referenceAssetId: event.target.value || undefined }
                : item))}
            >
              <option value="">No character identity reference</option>
              {Object.values(project.assets).map(asset => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
            </select>
            <p className="mt-1 text-[9px] text-text-muted">
              MiniMax uses this image as a subject reference when the character appears in a panel.
            </p>
          </div>
        ))}
        <input className={input} value={newCharacter.name} onChange={event => setNewCharacter(value => ({ ...value, name: event.target.value }))} placeholder="Character name" />
        <textarea className={input} value={newCharacter.description} onChange={event => setNewCharacter(value => ({ ...value, description: event.target.value }))} placeholder="Canonical visual description and wardrobe" />
        <button className={`${button} w-full`} onClick={addCharacter}><Plus size={12} /> Add character</button>
      </div>
      <button
        className={`${button} w-full border-accent-blue text-accent-blue`}
        disabled={busy !== null || !request.premise.trim()}
        onClick={() => makePlan(createCompleteComic)}
      >
        {busy !== null ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
        {createCompleteComic ? 'Create complete comic' : 'Create editable comic plan'}
      </button>
      {createCompleteComic && (
        <button className={`${button} w-full`} disabled={busy !== null || !request.premise.trim()} onClick={() => makePlan(false)}>
          Create plan only
        </button>
      )}
      <details open={activity.state === 'error'} className="rounded-lg border border-border bg-bg-tertiary/30 p-2">
        <summary className="cursor-pointer text-[10px] font-medium text-text-secondary">
          Resume an interrupted comic checkpoint
        </summary>
        <p className="mt-2 text-[9px] text-text-muted">
          Restores the saved story bible, completed pages, placed panels and generated artwork instead of restarting.
        </p>
        <input
          className={`${input} mt-2`}
          value={recoveryJobId}
          onChange={event => setRecoveryJobId(event.target.value)}
          placeholder="comic-plan-job-…"
        />
        <button
          className={`${button} mt-2 w-full border-amber-500/50 text-amber-300`}
          disabled={busy !== null || (!pendingPlan && !recoveryJobId.trim())}
          onClick={recoverPlan}
        >
          {busy === 'plan' ? <Loader2 size={12} className="animate-spin" /> : <Redo2 size={12} />}
          Resume from latest checkpoint
        </button>
      </details>
      <div className={`rounded-lg border p-2.5 ${
        activity.state === 'error'
          ? 'border-red-500/40 bg-red-500/5'
          : activity.state === 'complete'
            ? 'border-emerald-500/40 bg-emerald-500/5'
            : 'border-border bg-bg-tertiary/40'
      }`}>
        <div className="flex items-center gap-2 text-[11px] text-text-primary">
          {activity.state === 'running' && <Loader2 size={13} className="animate-spin text-accent-blue" />}
          {activity.state === 'complete' && <span className="text-emerald-400">✓</span>}
          {activity.state === 'error' && <span className="font-bold text-red-400">!</span>}
          <span>{activity.message}</span>
          {startedAt && <span className="ml-auto shrink-0 tabular-nums text-[9px] text-text-muted">{elapsedSeconds}s</span>}
        </div>
        {!!activity.total && (
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-bg-primary">
            <div
              className="h-full bg-accent-blue transition-all duration-300"
              style={{ width: `${Math.max(2, ((activity.current ?? 0) / activity.total) * 100)}%` }}
            />
          </div>
        )}
        {activity.steps.length > 1 && (
          <ol className="mt-2 space-y-1 border-t border-border/60 pt-2">
            {activity.steps.map((step, index) => (
              <li key={`${index}-${step}`} className="flex gap-1.5 text-[9px] text-text-muted">
                <span className="text-accent-blue">{index + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
      {project.director && (
        <button className={`${button} w-full border-emerald-500/50 text-emerald-400`} disabled={busy !== null} onClick={() => generateAll()}>
          {busy === 'images' ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
          {progress || (remainingPanels > 0
            ? `Generate all images — sequential queue (${remainingPanels} remaining)`
            : `All ${totalPlannedPanels} panel images generated`)}
        </button>
      )}
      {project.director && (
        <div className="border-t border-border pt-3 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <button className={`${button} border-amber-500/50 text-amber-300`} disabled={busy !== null} onClick={cleanUpCurrentComicText}>
              <Type size={12} /> Repair comic and text
            </button>
            <button className={`${button} border-accent-blue/50 text-accent-blue`} disabled={busy !== null} onClick={regenerateAllArtwork}>
              <ImagePlus size={12} /> Regenerate all artwork
            </button>
            <button className={`${button} col-span-2`} disabled={busy !== null} onClick={varyCurrentLayouts}>
              <PanelTop size={12} /> Vary page layouts
            </button>
          </div>
          <p className="text-[9px] text-text-muted">
            Repair and layout changes keep every existing image. Artwork regeneration may consume provider credits.
          </p>
          <div className="rounded-lg border border-border bg-bg-tertiary/30 p-2.5 space-y-2">
            <strong className="text-[10px] uppercase tracking-wide text-text-muted">Text-only editing and translation</strong>
            <p className="text-[9px] text-text-muted">
              The LLM changes only captions, dialogue and effects. Images and visual prompts are untouched.
              Manual text edits below are used as the source of truth.
            </p>
            <textarea
              className={input}
              rows={2}
              value={textInstruction}
              onChange={event => setTextInstruction(event.target.value)}
              placeholder="Optional rewrite instruction: make it drier, shorten exposition, preserve character voices…"
            />
            <button
              className={`${button} w-full`}
              disabled={busy !== null}
              onClick={() => applyTextOperation('rewrite')}
            >
              {busy === 'text' ? <Loader2 size={12} className="animate-spin" /> : <Type size={12} />}
              Rewrite text only
            </button>
            <input
              className={input}
              list="comic-export-languages"
              value={targetLanguage}
              onChange={event => setTargetLanguage(event.target.value)}
              placeholder="Target language — type any language"
            />
            <datalist id="comic-export-languages">
              {['Español', 'English', 'Français', 'Deutsch', 'Italiano', 'Português', 'Català',
                '日本語', '한국어', '中文', 'العربية', 'हिन्दी'].map(language =>
                <option key={language} value={language} />)}
            </datalist>
            <div className="grid grid-cols-2 gap-2">
              <button
                className={button}
                disabled={busy !== null || !targetLanguage.trim()}
                onClick={() => applyTextOperation('translate')}
              >
                Translate in editor
              </button>
              <button
                className={`${button} border-emerald-500/50 text-emerald-400`}
                disabled={busy !== null || !targetLanguage.trim()}
                onClick={exportTranslatedPdf}
              >
                {busy === 'translation' ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                Export translated PDF
              </button>
            </div>
          </div>
          <div>
            <strong className="text-[10px] uppercase tracking-wide text-text-muted">Review plan</strong>
            <p className="text-[9px] text-text-muted mt-1">The queue submits one panel at a time, preserves completed artwork and resumes from the first missing panel.</p>
          </div>
          <details className="rounded-lg border border-border bg-bg-tertiary/30 p-2">
            <summary className="cursor-pointer text-[10px] font-medium text-text-secondary">
              {project.director.plan.styleBible.trim()
                ? 'Visual continuity bible created by the LLM'
                : 'No separate visual bible needed'}
            </summary>
            {project.director.plan.styleBible.trim() ? (
              <p className="mt-2 whitespace-pre-wrap text-[9px] leading-relaxed text-text-muted">
                {project.director.plan.styleBible}
              </p>
            ) : (
              <p className="mt-2 text-[9px] text-text-muted">
                Comic Director left it empty, so no visual-bible block is sent to the image generator.
              </p>
            )}
          </details>
          {hasBrokenEncoding && (
            <button className={`${button} w-full border-amber-500/50 text-amber-300`} onClick={repairCurrentPlanEncoding}>
              Repair Spanish text encoding in this plan
            </button>
          )}
          {project.director.plan.pages.map((page, pageIndex) => (
            <details key={page.pageNumber} open={pageIndex === 0} className="rounded-lg border border-border bg-bg-tertiary/30">
              <summary className="cursor-pointer px-2 py-2 text-xs font-medium text-text-primary">Page {page.pageNumber} · {page.panels.length} panels</summary>
              <div className="p-2 pt-0 space-y-2">
                {page.panels.map((panel, panelIndex) => (
                  <div key={panel.id} className="rounded border border-border bg-bg-secondary p-2 space-y-2">
                    <div className="flex justify-between text-[10px]">
                      <b className="text-text-primary">Panel {panelIndex + 1}</b>
                      <span className="text-text-muted">{panel.framing}</span>
                    </div>
                    <Field label="Image prompt">
                      <textarea className={input} rows={5} value={panel.imagePrompt}
                        onChange={event => updatePlanPanel(pageIndex, panelIndex, { imagePrompt: event.target.value })} />
                    </Field>
                    <Field label="Dialogue / captions">
                      <PanelScriptEditor
                        panel={panel}
                        onCommit={value => commitPanelText(pageIndex, panelIndex, value)}
                      />
                    </Field>
                    <button className={`${button} w-full`} disabled={singleBusy !== null || busy !== null} onClick={() => generateSingle(pageIndex, panelIndex)}>
                      {singleBusy === panel.id ? <Loader2 size={12} className="animate-spin" /> : <ImagePlus size={12} />}
                      {project.director!.completedPanelIds.includes(panel.id) ? 'Regenerate panel' : 'Generate panel'}
                    </button>
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  )
}

export function ComicEditorPanel() {
  const project = useComicStore(state => state.project)
  const persistedName = useComicStore(state => state.persistedName)
  const dirty = useComicStore(state => state.dirty)
  const currentPageId = useComicStore(state => state.currentPageId)
  const zoom = useComicStore(state => state.zoom)
  const setZoom = useComicStore(state => state.setZoom)
  const snapEnabled = useComicStore(state => state.snapEnabled)
  const setSnapEnabled = useComicStore(state => state.setSnapEnabled)
  const patchProject = useComicStore(state => state.patchProject)
  const undo = useComicStore(state => state.undo)
  const redo = useComicStore(state => state.redo)
  const history = useComicStore(state => state.history)
  const [sideTab, setSideTab] = useState<SideTab>('assets')
  const [toolbarCollapsed, setToolbarCollapsed] = useState(false)
  const [sidePanelCollapsed, setSidePanelCollapsed] = useState(false)
  const [fitMode, setFitMode] = useState(true)
  const [notice, setNotice] = useState<Notice>(null)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState('')
  const importRef = useRef<HTMLInputElement>(null)
  const canvasViewportRef = useRef<HTMLDivElement>(null)
  const maestroOutputs = useStore(state => state.outputs)
  const comicOutputs = maestroOutputs.filter(output => output.type === 'comic')
  const notify = (value: Notice) => {
    setNotice(value)
    if (value) setTimeout(() => setNotice(null), 5000)
  }
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.matches('input, textarea, select, [contenteditable="true"]')) return
      const state = useComicStore.getState()
      const page = state.project.pages.find(item => item.id === state.currentPageId)
      const element = page?.elements.find(item => item.id === state.selectedId)
      const modifier = event.ctrlKey || event.metaKey
      if (modifier && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        event.shiftKey ? state.redo() : state.undo()
        return
      }
      if (modifier && event.key.toLowerCase() === 'd' && element) {
        event.preventDefault()
        state.duplicateElement(page!.id, element.id)
        return
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && element && !element.locked) {
        event.preventDefault()
        state.removeElement(page!.id, element.id)
        return
      }
      const directions: Record<string, [number, number]> = {
        ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
      }
      const direction = directions[event.key]
      if (direction && element && !element.locked) {
        event.preventDefault()
        const amount = event.shiftKey ? 10 : 1
        state.updateElement(page!.id, element.id, {
          x: element.x + direction[0] * amount,
          y: element.y + direction[1] * amount,
        }, true)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [])
  useEffect(() => {
    if (!fitMode) return
    const viewport = canvasViewportRef.current
    const page = project.pages.find(item => item.id === currentPageId)
    if (!viewport || !page) return
    const fit = () => {
      const horizontalPadding = 32
      const verticalPadding = 32
      const nextZoom = Math.min(
        1.5,
        Math.max(.2, (viewport.clientWidth - horizontalPadding) / page.width),
        Math.max(.2, (viewport.clientHeight - verticalPadding) / page.height),
      )
      setZoom(nextZoom)
    }
    const frame = window.requestAnimationFrame(fit)
    const observer = new ResizeObserver(fit)
    observer.observe(viewport)
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [fitMode, currentPageId, project.pages, setZoom, toolbarCollapsed, sidePanelCollapsed])
  const applyLayout = (name: string) => {
    const state = useComicStore.getState()
    const page = state.project.pages.find(item => item.id === state.currentPageId)
    const preset = COMIC_LAYOUTS.find(item => item.name === name)
    if (!page || !preset) return
    const nested = page.elements.some(element => element.parentId)
    if (nested && !confirm('Replace this page layout? Content currently inside panels will be removed.')) return
    state.updatePage(page.id, {
      elements: [
        ...page.elements.filter(element => element.type !== 'panel' && !element.parentId),
        ...preset.build(page),
      ],
    })
  }
  const addEffect = (name: string) => {
    const state = useComicStore.getState()
    const page = state.project.pages.find(item => item.id === state.currentPageId)
    const preset = COMIC_EFFECTS.find(item => item.name === name)
    if (page && preset) state.addElement(page.id, createEffect(page, preset))
  }

  const save = async () => {
    setSaving(true)
    try {
      const preview = await captureComicPage(0.35)
      const result = await api.saveComicProject(useComicStore.getState().project, preview, persistedName)
      useComicStore.getState().setPersistedName(result.name)
      useComicStore.getState().markSaved()
      useStore.getState().loadOutputs()
      notify({ kind: 'ok', text: 'Comic saved in the active Maestro workspace.' })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    if (!persistedName || !dirty || saving) return
    const timer = window.setTimeout(save, 5000)
    return () => window.clearTimeout(timer)
    // save intentionally reads the current store snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, persistedName, saving, project.updatedAt])

  const importProject = async (file?: File) => {
    if (!file) return
    try {
      const parsed = normalizeComicProject(JSON.parse(await file.text()))
      // Legacy comic-generator projects embedded every library image as a
      // data URL. Persist each one through Maestro before accepting the
      // project so the migrated JSON remains small and reloadable.
      for (const asset of Object.values(parsed.assets)) {
        if (!asset.source.startsWith('data:image/')) continue
        const response = await fetch(asset.source)
        const blob = await response.blob()
        const extension = blob.type.split('/')[1]?.replace('jpeg', 'jpg') || 'png'
        const uploaded = await api.uploadImage(new File([blob], `${asset.id}.${extension}`, { type: blob.type }))
        asset.source = uploaded.url
        asset.kind = 'upload'
        asset.missing = false
      }
      useComicStore.getState().setProject(parsed)
      notify({ kind: 'ok', text: 'Comic imported; embedded legacy assets were persisted in Maestro.' })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      if (importRef.current) importRef.current.value = ''
    }
  }

  const openSaved = async (name: string) => {
    if (!name) return
    if (dirty && !confirm('Open this saved comic and discard unsaved changes?')) return
    try {
      useComicStore.getState().setProject(await api.loadComicProject(name), name)
      notify({ kind: 'ok', text: 'Comic opened from the active workspace.' })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    }
  }

  const runExport = async (kind: 'pdf' | 'cbz' | 'png') => {
    setExporting(kind)
    try {
      if (kind === 'pdf') await exportComicPdf((current, total) => setExporting(`PDF ${current}/${total}`))
      if (kind === 'cbz') await exportComicCbz((current, total) => setExporting(`CBZ ${current}/${total}`))
      if (kind === 'png') await exportComicPagePng()
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setExporting('')
    }
  }

  const newProject = () => {
    if (dirty && !confirm('Create a new comic and discard unsaved changes?')) return
    useComicStore.getState().setProject(createComicProject())
  }

  return (
    <div className="h-full min-h-0 flex flex-col rounded-xl border border-border bg-bg-primary overflow-hidden">
      <header className={`shrink-0 border-b border-border bg-bg-secondary flex items-center gap-2 ${
        toolbarCollapsed ? 'px-3 py-1.5' : 'px-3 py-2 flex-wrap'
      }`}>
        <BookOpen size={17} className="text-accent-blue" />
        {toolbarCollapsed ? (
          <>
            <span className="min-w-0 truncate text-xs font-semibold text-text-primary">{project.title}</span>
            {dirty && <span className="text-[10px] text-yellow-400">Unsaved</span>}
            <button
              className={`${button} ml-auto`}
              onClick={() => setToolbarCollapsed(false)}
              title="Expand comic toolbar"
            >
              <ChevronDown size={13} /> Tools
            </button>
          </>
        ) : (
          <>
            <input
              value={project.title}
              onChange={event => patchProject({ title: event.target.value })}
              className="w-48 bg-transparent text-sm font-semibold text-text-primary focus:outline-none border-b border-transparent focus:border-accent-blue"
            />
            {dirty && <span className="text-[10px] text-yellow-400">Unsaved</span>}
            <div className="h-5 border-l border-border mx-1" />
            <button className={button} onClick={newProject}><Plus size={13} /> New</button>
            <select className={`${input} w-36`} value="" onChange={event => applyLayout(event.target.value)} title="Apply a panel layout">
              <option value="">Layouts…</option>
              {COMIC_LAYOUTS.map(layout => <option key={layout.name} value={layout.name}>{layout.name}</option>)}
            </select>
            <select className={`${input} w-32`} value="" onChange={event => addEffect(event.target.value)} title="Add a pop-art effect">
              <option value="">Effects…</option>
              {COMIC_EFFECTS.map(effect => <option key={effect.name} value={effect.name}>{effect.name}</option>)}
            </select>
            <select className={`${input} w-40`} value="" onChange={event => openSaved(event.target.value)} title="Open a saved comic">
              <option value="">Open saved…</option>
              {comicOutputs.map(output => <option key={output.name} value={output.name}>{output.name}</option>)}
            </select>
            <button className={button} onClick={() => importRef.current?.click()}><Upload size={13} /> Import</button>
            <input ref={importRef} type="file" accept=".json,.comic.json" className="hidden" onChange={event => importProject(event.target.files?.[0])} />
            <button className={button} disabled={saving} onClick={save}>{saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save</button>
            <button className={button} disabled={!history.past.length} onClick={undo}><Undo2 size={13} /></button>
            <button className={button} disabled={!history.future.length} onClick={redo}><Redo2 size={13} /></button>
            <button className={`${button} ${snapEnabled ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setSnapEnabled(!snapEnabled)}>Grid</button>
            <div className="ml-auto flex items-center gap-1">
              <button className={button} onClick={exportComicJson}><FileJson size={13} /> JSON</button>
              <button className={button} disabled={!!exporting} onClick={() => runExport('png')}>PNG</button>
              <button className={button} disabled={!!exporting} onClick={() => runExport('cbz')}>CBZ</button>
              <button className={`${button} border-accent-blue/50`} disabled={!!exporting} onClick={() => runExport('pdf')}>
                {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />} {exporting || 'PDF'}
              </button>
              <button className={button} onClick={() => setToolbarCollapsed(true)} title="Collapse comic toolbar">
                <ChevronUp size={13} />
              </button>
            </div>
          </>
        )}
      </header>
      {notice && (
        <div className={`shrink-0 px-3 py-1.5 text-xs ${notice.kind === 'ok' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'}`}>{notice.text}</div>
      )}
      <div className="flex flex-1 min-h-0">
        <PagesRail />
        <section className="flex-1 min-w-0 flex flex-col bg-[#15171b]">
          <div className="shrink-0 border-b border-border p-2 flex items-center justify-center gap-2 text-xs text-text-muted">
            <button className={button} onClick={() => { setFitMode(false); setZoom(zoom - .1) }}>-</button>
            <span className="w-12 text-center">{Math.round(zoom * 100)}%</span>
            <button className={button} onClick={() => { setFitMode(false); setZoom(zoom + .1) }}>+</button>
            <button
              className={`${button} ${fitMode ? 'border-accent-blue text-accent-blue' : ''}`}
              onClick={() => setFitMode(true)}
              title="Fit the full comic page in the available space"
            >
              <Maximize2 size={12} /> Fit
            </button>
            <span className="ml-2">{project.format.width} × {project.format.height}</span>
          </div>
          <div ref={canvasViewportRef} className="flex-1 min-h-0 overflow-auto">
            <div className="min-w-full min-h-full flex p-4">
              <div className="m-auto">
                <ComicCanvas />
              </div>
            </div>
          </div>
        </section>
        <aside className={`shrink-0 border-l border-border bg-bg-secondary flex flex-col min-h-0 transition-[width] ${
          sidePanelCollapsed ? 'w-10' : 'w-72 xl:w-80'
        }`}>
          {sidePanelCollapsed ? (
            <button
              className="h-full flex flex-col items-center gap-2 py-3 text-[10px] text-text-muted hover:text-accent-blue"
              onClick={() => setSidePanelCollapsed(false)}
              title="Expand assets and inspector"
            >
              <ChevronLeft size={15} />
              <span className="[writing-mode:vertical-rl]">Assets · Inspector · Director</span>
            </button>
          ) : (
            <>
              <div className="flex border-b border-border">
                <div className="grid flex-1 grid-cols-3">
                  {([
                    ['assets', 'Assets'],
                    ['inspector', 'Inspector'],
                    ['director', 'Director'],
                  ] as const).map(([id, label]) => (
                    <button key={id} className={`py-2 text-[11px] ${sideTab === id ? 'text-accent-blue border-b-2 border-accent-blue' : 'text-text-muted'}`} onClick={() => setSideTab(id)}>{label}</button>
                  ))}
                </div>
                <button
                  className="w-9 border-l border-border text-text-muted hover:text-accent-blue"
                  onClick={() => setSidePanelCollapsed(true)}
                  title="Collapse assets and inspector"
                >
                  <ChevronRight size={15} className="mx-auto" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto p-3">
                {sideTab === 'assets' && <AssetsPanel />}
                {sideTab === 'inspector' && <InspectorPanel />}
                {sideTab === 'director' && <ComicDirectorPanel notify={notify} />}
              </div>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
