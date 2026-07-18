import { useEffect, useRef, useState } from 'react'
import {
  BookOpen, Copy, Download, Eye, EyeOff, FileJson,
  ImagePlus, Loader2, Lock, PanelTop, Plus, Redo2, Save, Sparkles, Trash2,
  Type, Undo2, Unlock, Upload, WandSparkles,
} from 'lucide-react'
import { useStore } from '../../stores/useStore'
import * as api from '../../api/client'
import { ComicCanvas } from './ComicCanvas'
import { comicId, COMIC_FORMATS, createComicProject, normalizeComicProject, panelsForCount, projectFromPlan } from './model'
import { useComicStore } from './store'
import { captureComicPage, exportComicCbz, exportComicJson, exportComicPagePng, exportComicPdf } from './export'
import type {
  ComicAsset, ComicCharacter, ComicDirectorRequest, ComicElement, ComicImageElement,
  ComicPanelElement, ComicPlanPanel, ComicTextElement,
} from './types'

type SideTab = 'assets' | 'inspector' | 'director'
type Notice = { kind: 'ok' | 'error'; text: string } | null

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
const input = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue'

const fileName = (path: string) => path.split(/[\\/]/).pop() || path

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

async function runLocalImage(prompt: string, modelType?: string): Promise<ComicAsset> {
  const maestro = useStore.getState()
  const selected = modelType || maestro.selectedModelPerMode.image || maestro.params.model_type
  if (!selected) throw new Error('Select an image model in Maestro first')
  const result = await api.submitGeneration({
    ...maestro.params,
    prompt,
    model_type: selected,
    image_mode: 1,
    generation_mode: 'image',
    repeat_generation: 1,
    workspace: maestro.activeWorkspace,
  })
  for (;;) {
    await new Promise(resolve => setTimeout(resolve, 1500))
    const status = await api.fetchJobStatus(result.job_id)
    if (status.status === 'failed' || status.status === 'cancelled') {
      throw new Error(status.error || status.message || 'Local image generation failed')
    }
    if (status.status === 'completed') {
      const path = status.output_files.find(value => /\.(png|jpe?g|webp)$/i.test(value))
      if (!path) throw new Error('Image job completed without an image')
      const name = fileName(path)
      maestro.loadOutputs()
      return {
        id: comicId('asset'),
        name,
        kind: 'local',
        source: `/api/v1/file/${encodeURIComponent(name)}`,
        prompt,
        provider: 'maestro',
        model: selected,
        createdAt: new Date().toISOString(),
        metadata: { jobId: result.job_id },
      }
    }
  }
}

async function generatePanelAsset(
  provider: 'maestro' | 'minimax',
  prompt: string,
  model?: string,
  reference?: string,
): Promise<ComicAsset> {
  if (provider === 'minimax') {
    const result = await api.generateComicWithMiniMax({
      prompt,
      aspect_ratio: '1:1',
      subject_reference: reference,
    })
    return result.asset
  }
  return runLocalImage(prompt, model)
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
  const remove = useComicStore(state => state.removeElement)
  const addElement = useComicStore(state => state.addElement)
  const page = project.pages.find(item => item.id === pageId)
  const element = page?.elements.find(item => item.id === selectedId)
  const patch = (next: Partial<ComicElement>) => element && update(pageId, element.id, next, true)

  const addText = () => {
    if (!page) return
    const selectedPanel = element?.type === 'panel' ? element : undefined
    const text: ComicTextElement = {
      id: comicId('text'), type: 'text', parentId: selectedPanel?.id ?? null,
      x: selectedPanel ? selectedPanel.width * .15 : page.width * .25,
      y: selectedPanel ? selectedPanel.height * .7 : page.height * .4,
      width: selectedPanel ? selectedPanel.width * .7 : page.width * .5,
      height: 100, rotation: 0, zIndex: 30, visible: true,
      content: 'Your text', fontSize: 22, fontFamily: project.style.fontFamily,
      color: '#111111', bold: false, italic: false, align: 'center',
      bubble: 'speech', bubbleBackground: '#ffffff', bubbleStrokeColor: '#111111', bubbleStrokeWidth: 3,
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
        <button className={button} onClick={addText}><Type size={13} /> Add text</button>
      </div>
      <div className="grid grid-cols-4 gap-1">
        {[1, 3, 6, 9].map(count => <button key={count} className={button} onClick={() => addPanels(count)}>{count}</button>)}
      </div>
      {!element ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-text-muted">
          Select an element to edit it.
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <strong className="text-xs capitalize text-text-primary">{element.type}</strong>
            <div className="flex gap-1">
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
          {element.type === 'panel' && (
            <div className="space-y-2">
              <Field label="Border width"><input className={input} type="number" min={0} max={30} value={element.borderWidth} onChange={event => patch({ borderWidth: Number(event.target.value) })} /></Field>
              <Field label="Border color"><input className="w-full h-8" type="color" value={element.borderColor} onChange={event => patch({ borderColor: event.target.value })} /></Field>
              <Field label="Corner radius"><input className={input} type="number" value={element.borderRadius} onChange={event => patch({ borderRadius: Number(event.target.value) })} /></Field>
            </div>
          )}
          {element.type === 'image' && (
            <div className="space-y-2">
              <Field label="Fit"><select className={input} value={element.objectFit} onChange={event => patch({ objectFit: event.target.value as ComicImageElement['objectFit'] })}><option value="cover">Fill panel</option><option value="contain">Show entire image</option></select></Field>
              <Field label="Filter"><select className={input} value={element.filter} onChange={event => patch({ filter: event.target.value as ComicImageElement['filter'] })}><option value="none">None</option><option value="bw">Black & white</option><option value="sepia">Sepia</option><option value="contrast">Comic contrast</option><option value="halftone">Halftone</option></select></Field>
              <Field label="Opacity"><input className={input} type="range" min={0} max={1} step={.05} value={element.opacity ?? 1} onChange={event => patch({ opacity: Number(event.target.value) })} /></Field>
            </div>
          )}
          {element.type === 'text' && (
            <div className="space-y-2">
              <Field label="Text"><textarea className={input} rows={4} value={element.content} onChange={event => patch({ content: event.target.value })} /></Field>
              <Field label="Bubble"><select className={input} value={element.bubble} onChange={event => patch({ bubble: event.target.value as ComicTextElement['bubble'] })}><option value="none">None / SFX</option><option value="speech">Speech</option><option value="thought">Thought</option><option value="caption">Caption</option><option value="scream">Scream</option></select></Field>
              <Field label="Font size"><input className={input} type="number" value={element.fontSize} onChange={event => patch({ fontSize: Number(event.target.value) })} /></Field>
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
  artStyle: 'modern graphic novel',
  dialogueDensity: 'medium',
  provider: 'maestro',
  imageModel: useStore.getState().selectedModelPerMode.image || '',
  characters: [],
})

function DirectorPanel({ notify }: { notify: (notice: Notice) => void }) {
  const project = useComicStore(state => state.project)
  const [request, setRequest] = useState<ComicDirectorRequest>(() => ({ ...initialDirector(), characters: project.characters }))
  const [busy, setBusy] = useState<'plan' | 'images' | null>(null)
  const [progress, setProgress] = useState('')
  const [newCharacter, setNewCharacter] = useState({ name: '', description: '' })
  const patch = <K extends keyof ComicDirectorRequest>(key: K, value: ComicDirectorRequest[K]) =>
    setRequest(current => ({ ...current, [key]: value }))

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

  const makePlan = async () => {
    if (!request.premise.trim()) return
    setBusy('plan')
    try {
      const { plan } = await api.planComic(request)
      const next = projectFromPlan(plan, {
        ...project,
        format: {
          ...project.format,
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
      }
      useComicStore.getState().setProject(next)
      notify({ kind: 'ok', text: `Director created ${plan.pages.length} pages. Review the plan before generating images.` })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setBusy(null)
    }
  }

  const generateAll = async () => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const tasks: Array<{ pageId: string; panel: ComicPanelElement; plan: ComicPlanPanel }> = []
    director.plan.pages.forEach((planPage, pageIndex) => {
      const page = state.project.pages[pageIndex]
      const panels = page?.elements.filter((element): element is ComicPanelElement => element.type === 'panel' && !element.parentId)
        .sort((a, b) => a.zIndex - b.zIndex) || []
      planPage.panels.forEach((planned, index) => {
        if (!director.completedPanelIds.includes(planned.id) && panels[index]) {
          tasks.push({ pageId: page.id, panel: panels[index], plan: planned })
        }
      })
    })
    setBusy('images')
    try {
      for (let index = 0; index < tasks.length; index++) {
        const task = tasks[index]
        setProgress(`Generating panel ${index + 1} / ${tasks.length}`)
        const character = director.plan.characters.find(item => task.plan.characters.includes(item.id))
        const reference = character?.referenceAssetId
          ? useComicStore.getState().project.assets[character.referenceAssetId]?.source
          : undefined
        const asset = await generatePanelAsset(
          director.provider,
          `${task.plan.imagePrompt}. ${state.project.style.promptSuffix}`,
          director.imageModel,
          reference,
        )
        const latest = useComicStore.getState()
        latest.addAsset(asset)
        latest.addElement(task.pageId, {
          id: comicId('image'), type: 'image', assetId: asset.id, parentId: task.panel.id,
          x: 0, y: 0, width: task.panel.width, height: task.panel.height,
          rotation: 0, zIndex: 2, objectFit: 'cover', filter: 'none', opacity: 1, visible: true,
        })
        latest.patchProject({
          director: {
            ...latest.project.director!,
            completedPanelIds: [...latest.project.director!.completedPanelIds, task.plan.id],
          },
        })
      }
      notify({ kind: 'ok', text: 'All Director panels were generated and placed.' })
    } catch (error) {
      notify({ kind: 'error', text: `${(error as Error).message}. Completed panels are preserved; run again to resume.` })
    } finally {
      setBusy(null)
      setProgress('')
    }
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-accent-blue/30 bg-accent-blue/5 p-3">
        <div className="flex items-center gap-2 text-xs font-medium text-text-primary"><WandSparkles size={14} /> Comic Director</div>
        <p className="text-[10px] text-text-muted mt-1">Plan exact pages, editable dialogue and image prompts, then generate every panel locally or with MiniMax.</p>
      </div>
      <Field label="Story premise"><textarea className={input} rows={5} value={request.premise} onChange={event => patch('premise', event.target.value)} placeholder="What happens in the comic?" /></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Pages"><input className={input} type="number" min={1} max={100} value={request.pageCount} onChange={event => patch('pageCount', Math.max(1, Number(event.target.value)))} /></Field>
        <Field label="Panels / page"><input className={input} type="number" min={1} max={12} value={request.panelsPerPage} onChange={event => patch('panelsPerPage', Math.max(1, Number(event.target.value)))} /></Field>
        <Field label="Language"><input className={input} value={request.language} onChange={event => patch('language', event.target.value)} /></Field>
        <Field label="Format"><select className={input} value={request.format} onChange={event => patch('format', event.target.value as ComicDirectorRequest['format'])}>{Object.entries(COMIC_FORMATS).map(([id, value]) => <option key={id} value={id}>{value.label}</option>)}</select></Field>
        <Field label="Genre"><input className={input} value={request.genre} onChange={event => patch('genre', event.target.value)} /></Field>
        <Field label="Tone"><input className={input} value={request.tone} onChange={event => patch('tone', event.target.value)} /></Field>
      </div>
      <Field label="Art style"><input className={input} value={request.artStyle} onChange={event => patch('artStyle', event.target.value)} /></Field>
      <Field label="Image provider"><select className={input} value={request.provider} onChange={event => patch('provider', event.target.value as 'maestro' | 'minimax')}><option value="maestro">Maestro local</option><option value="minimax">MiniMax image-01</option></select></Field>
      {request.provider === 'maestro' && <Field label="Image model"><input className={input} value={request.imageModel || ''} onChange={event => patch('imageModel', event.target.value)} placeholder="Uses Maestro's selected image model" /></Field>}
      <div className="border-t border-border pt-3 space-y-2">
        <strong className="text-[10px] uppercase tracking-wide text-text-muted">Characters</strong>
        {request.characters.map(character => (
          <div key={character.id} className="rounded border border-border p-2 text-[10px]">
            <div className="flex justify-between"><b className="text-text-primary">{character.name}</b><button onClick={() => patch('characters', request.characters.filter(item => item.id !== character.id))}><Trash2 size={11} /></button></div>
            <p className="text-text-muted mt-1">{character.description}</p>
          </div>
        ))}
        <input className={input} value={newCharacter.name} onChange={event => setNewCharacter(value => ({ ...value, name: event.target.value }))} placeholder="Character name" />
        <textarea className={input} value={newCharacter.description} onChange={event => setNewCharacter(value => ({ ...value, description: event.target.value }))} placeholder="Canonical visual description and wardrobe" />
        <button className={`${button} w-full`} onClick={addCharacter}><Plus size={12} /> Add character</button>
      </div>
      <button className={`${button} w-full border-accent-blue text-accent-blue`} disabled={busy !== null || !request.premise.trim()} onClick={makePlan}>
        {busy === 'plan' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Create editable comic plan
      </button>
      {project.director && (
        <button className={`${button} w-full border-emerald-500/50 text-emerald-400`} disabled={busy !== null} onClick={generateAll}>
          {busy === 'images' ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
          {progress || `Generate images (${project.director.completedPanelIds.length} complete)`}
        </button>
      )}
    </div>
  )
}

export function ComicEditorPanel() {
  const project = useComicStore(state => state.project)
  const persistedName = useComicStore(state => state.persistedName)
  const dirty = useComicStore(state => state.dirty)
  const zoom = useComicStore(state => state.zoom)
  const setZoom = useComicStore(state => state.setZoom)
  const patchProject = useComicStore(state => state.patchProject)
  const undo = useComicStore(state => state.undo)
  const redo = useComicStore(state => state.redo)
  const history = useComicStore(state => state.history)
  const [sideTab, setSideTab] = useState<SideTab>('assets')
  const [notice, setNotice] = useState<Notice>(null)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState('')
  const importRef = useRef<HTMLInputElement>(null)
  const maestroOutputs = useStore(state => state.outputs)
  const comicOutputs = maestroOutputs.filter(output => output.type === 'comic')
  const notify = (value: Notice) => {
    setNotice(value)
    if (value) setTimeout(() => setNotice(null), 5000)
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
      useComicStore.getState().setProject(parsed)
      notify({ kind: 'ok', text: parsed.version === 2 ? 'Comic imported.' : 'Legacy comic migrated.' })
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
    <div className="h-[calc(100vh-112px)] min-h-[680px] flex flex-col rounded-xl border border-border bg-bg-primary overflow-hidden">
      <header className="shrink-0 border-b border-border bg-bg-secondary px-3 py-2 flex items-center gap-2 flex-wrap">
        <BookOpen size={17} className="text-accent-blue" />
        <input
          value={project.title}
          onChange={event => patchProject({ title: event.target.value })}
          className="w-48 bg-transparent text-sm font-semibold text-text-primary focus:outline-none border-b border-transparent focus:border-accent-blue"
        />
        {dirty && <span className="text-[10px] text-yellow-400">Unsaved</span>}
        <div className="h-5 border-l border-border mx-1" />
        <button className={button} onClick={newProject}><Plus size={13} /> New</button>
        <select className={`${input} w-40`} value="" onChange={event => openSaved(event.target.value)} title="Open a saved comic">
          <option value="">Open saved…</option>
          {comicOutputs.map(output => <option key={output.name} value={output.name}>{output.name}</option>)}
        </select>
        <button className={button} onClick={() => importRef.current?.click()}><Upload size={13} /> Import</button>
        <input ref={importRef} type="file" accept=".json,.comic.json" className="hidden" onChange={event => importProject(event.target.files?.[0])} />
        <button className={button} disabled={saving} onClick={save}>{saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save</button>
        <button className={button} disabled={!history.past.length} onClick={undo}><Undo2 size={13} /></button>
        <button className={button} disabled={!history.future.length} onClick={redo}><Redo2 size={13} /></button>
        <div className="ml-auto flex items-center gap-1">
          <button className={button} onClick={exportComicJson}><FileJson size={13} /> JSON</button>
          <button className={button} disabled={!!exporting} onClick={() => runExport('png')}>PNG</button>
          <button className={button} disabled={!!exporting} onClick={() => runExport('cbz')}>CBZ</button>
          <button className={`${button} border-accent-blue/50`} disabled={!!exporting} onClick={() => runExport('pdf')}>
            {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />} {exporting || 'PDF'}
          </button>
        </div>
      </header>
      {notice && (
        <div className={`shrink-0 px-3 py-1.5 text-xs ${notice.kind === 'ok' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'}`}>{notice.text}</div>
      )}
      <div className="flex flex-1 min-h-0">
        <PagesRail />
        <section className="flex-1 min-w-0 flex flex-col bg-[#15171b]">
          <div className="shrink-0 border-b border-border p-2 flex items-center justify-center gap-2 text-xs text-text-muted">
            <button className={button} onClick={() => setZoom(zoom - .1)}>-</button>
            <span className="w-12 text-center">{Math.round(zoom * 100)}%</span>
            <button className={button} onClick={() => setZoom(zoom + .1)}>+</button>
            <span className="ml-2">{project.format.width} × {project.format.height}</span>
          </div>
          <div className="flex-1 overflow-auto p-8 flex items-start justify-center">
            <ComicCanvas />
          </div>
        </section>
        <aside className="w-72 xl:w-80 shrink-0 border-l border-border bg-bg-secondary flex flex-col min-h-0">
          <div className="grid grid-cols-3 border-b border-border">
            {([
              ['assets', 'Assets'],
              ['inspector', 'Inspector'],
              ['director', 'Director'],
            ] as const).map(([id, label]) => (
              <button key={id} className={`py-2 text-[11px] ${sideTab === id ? 'text-accent-blue border-b-2 border-accent-blue' : 'text-text-muted'}`} onClick={() => setSideTab(id)}>{label}</button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {sideTab === 'assets' && <AssetsPanel />}
            {sideTab === 'inspector' && <InspectorPanel />}
            {sideTab === 'director' && <DirectorPanel notify={notify} />}
          </div>
        </aside>
      </div>
    </div>
  )
}
