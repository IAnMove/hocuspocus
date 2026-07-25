import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Copy, Download, Eye, EyeOff, FileJson,
  History as HistoryIcon, ImagePlus, Loader2, Lock, PanelTop, Plus, Redo2, Save, Sparkles, Trash2,
  Maximize2, Type, Undo2, Unlock, Upload, WandSparkles, X,
} from 'lucide-react'
import { getModelMode, useStore } from '../../stores/useStore'
import * as api from '../../api/client'
import { EditableLanguageInput } from '../../components/common/EditableLanguageInput'
import { findCompletedLocalImage, generateImageAsset } from '../../lib/imageGeneration'
import { rememberPrompt } from '../../lib/promptHistory'
import { ComicCanvas } from './ComicCanvas'
import { ComicCharactersPanel, ComicQualityPanel, ComicScriptPanel, ComicVideoPanel, ComicWritingProviderFields } from './ComicWorkflowPanels'
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
  ComicPlanPage,
} from './types'

type SideTab = 'assets' | 'inspector' | 'script' | 'characters' | 'quality' | 'video' | 'director'
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

const wait = (milliseconds: number) => new Promise(resolve => window.setTimeout(resolve, milliseconds))
const comicTranslationCache = new Map<string, ComicPlanPage>()
const writingForOperation = (
  input: ComicDirectorRequest,
  mode: 'rewrite' | 'translate',
): Pick<ComicDirectorRequest, 'writingProvider' | 'writingModel' | 'writingBaseUrl'> => {
  const legacyDeepSeek = input.writingProvider === 'openai-compatible'
    && /api\.deepseek\.com/i.test(input.writingBaseUrl || '')
  if (mode === 'translate' && (input.writingProvider === 'deepseek' || legacyDeepSeek)) {
    return {
      writingProvider: 'deepseek',
      writingModel: 'deepseek-v4-flash',
      writingBaseUrl: 'https://api.deepseek.com',
    }
  }
  return {
    writingProvider: input.writingProvider,
    writingModel: input.writingModel,
    writingBaseUrl: input.writingBaseUrl,
  }
}
const translationCacheKey = (
  page: ComicPlanPage,
  language: string,
  glossary: ComicProject['translationGlossary'],
  writing?: Pick<ComicDirectorRequest, 'writingProvider' | 'writingModel' | 'writingBaseUrl'>,
) => JSON.stringify({ language: language.trim().toLocaleLowerCase(), glossary, writing, panels: page.panels.map(panel => ({
  id: panel.id, captions: panel.captions, dialogue: panel.dialogue, soundEffects: panel.soundEffects,
})) })

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
  const [draft, setDraft] = useState({ canonical, value: canonical })
  const value = draft.canonical === canonical ? draft.value : canonical
  return (
    <textarea
      className={input}
      rows={3}
      value={value}
      placeholder="Leave empty for a silent panel. Use [Caption], [Dialogue], [SFX] or [Character]."
      onChange={event => setDraft({ canonical, value: event.target.value })}
      onBlur={() => value !== canonical && onCommit(value)}
    />
  )
}

function buildDirectorImagePrompt(
  director: ComicProject['director'],
  panelPrompt: string,
  promptSuffix: string,
  plannedPanel?: ComicPlanPanel,
): string {
  const input = director?.input
  const removePageLayoutInstructions = (value: string) => repairMojibake(value)
    .replace(/\b(?:estructura|structure|layout)\s*:\s*[^.!?]*(?:p[aá]ginas?|pages?|paneles?|panels?|viñetas?)[^.!?]*[.!?]*/gi, ' ')
    .replace(/[^.!?]*(?:\d+\s+)?(?:p[aá]ginas?|pages?)[^.!?]*(?:paneles?|panels?|viñetas?)[^.!?]*[.!?]*/gi, ' ')
    .replace(/\bprofessional sequential comic art\b/gi, 'single comic-panel illustration')
    .replace(/\s+/g, ' ')
    .trim()
  const visualBible = removePageLayoutInstructions(director?.plan.styleBible || '')
  let repairedPanelPrompt = removePageLayoutInstructions(panelPrompt)
  // Older plans embedded the complete bible into every panel prompt. Keep the
  // reusable bible separate so a compact provider-specific excerpt can be used.
  if (visualBible) {
    const bibleTextIndex = repairedPanelPrompt.indexOf(visualBible)
    const bibleLabelIndex = repairedPanelPrompt
      .slice(0, Math.max(0, bibleTextIndex))
      .toLocaleLowerCase()
      .lastIndexOf('visual continuity bible:')
    if (bibleTextIndex >= 0 && bibleLabelIndex >= 0) {
      repairedPanelPrompt = `${repairedPanelPrompt.slice(0, bibleLabelIndex)} ${
        repairedPanelPrompt.slice(bibleTextIndex + visualBible.length).replace(/^[.\s]+/, '')
      }`.replace(/\s+/g, ' ').trim()
    }
  }
  const characterLocks = plannedPanel?.characters.map(characterId => {
    const character = director?.plan.characters.find(item => item.id === characterId)
    if (!character) return ''
    return [
      `${character.name}: ${character.description}`,
      character.visualNotes,
      character.wardrobe,
      character.negativePrompt ? `Never alter or add: ${character.negativePrompt}` : '',
    ].filter(Boolean).join('. ')
  }).filter(Boolean).join(' | ')
  const fullPrompt = [
    'SINGLE IMAGE LOCK: Create exactly one full-bleed illustration for one comic panel. No comic page, panel grid, collage, split screen, inset panels, frames, borders, speech bubbles, captions, sound effects, text, logos, watermarks or lettering.',
    input?.artStyle ? `VISUAL STYLE LOCK: ${removePageLayoutInstructions(input.artStyle)}.` : '',
    input?.worldContext ? `WORLD AND PERIOD LOCK: ${removePageLayoutInstructions(input.worldContext)}.` : '',
    visualBible && !repairedPanelPrompt.includes(visualBible)
      ? `VISUAL CONTINUITY BIBLE: ${visualBible}.`
      : '',
    input?.forbiddenElements
      ? `STRICTLY FORBIDDEN: ${repairMojibake(input.forbiddenElements)}. No anachronisms.`
      : '',
    characterLocks ? `CHARACTER IDENTITY LOCKS: ${characterLocks}. Keep face, body, scale, palette, wardrobe and invariant accessories identical to every prior appearance.` : '',
    plannedPanel?.continuityNotes ? `SHOT CONTINUITY: ${plannedPanel.continuityNotes}.` : '',
    repairedPanelPrompt,
    removePageLayoutInstructions(promptSuffix),
  ].filter(Boolean).join(' ')
  if (director?.provider !== 'minimax' || fullPrompt.length < 1500) return fullPrompt

  const trimSection = (value: string, limit: number) => {
    if (value.length <= limit) return value
    const prefix = value.slice(0, limit)
    const lastSpace = prefix.lastIndexOf(' ')
    const clipped = (lastSpace > limit * 0.6 ? prefix.slice(0, lastSpace) : prefix)
      .replace(/[\s,;:-]+$/, '')
    return `${clipped}.`
  }
  const compactSections = [
    'One full-bleed comic-panel illustration only. No grid, collage, border, bubbles, captions, text, logo or watermark.',
    trimSection(repairedPanelPrompt, 780),
    characterLocks ? `Character locks: ${trimSection(characterLocks, 260)}.` : '',
    input?.artStyle ? `Style: ${trimSection(removePageLayoutInstructions(input.artStyle), 140)}.` : '',
    input?.worldContext ? `World: ${trimSection(removePageLayoutInstructions(input.worldContext), 140)}.` : '',
    input?.forbiddenElements ? `Avoid: ${trimSection(repairMojibake(input.forbiddenElements), 120)}.` : '',
    plannedPanel?.continuityNotes ? `Continuity: ${trimSection(plannedPanel.continuityNotes, 120)}.` : '',
    visualBible ? `Visual continuity: ${trimSection(visualBible, 220)}.` : '',
    trimSection(removePageLayoutInstructions(promptSuffix), 100),
  ].filter(Boolean)
  let compactPrompt = ''
  for (const section of compactSections) {
    const available = 1450 - compactPrompt.length - (compactPrompt ? 1 : 0)
    if (available < 24) break
    compactPrompt += `${compactPrompt ? ' ' : ''}${trimSection(section, available)}`
  }
  return compactPrompt
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

const TRANSLATION_LANGUAGES = [
  'Español',
  'English',
  'Français',
  'Deutsch',
  'Italiano',
  'Português',
  'Català',
  '日本語',
  '한국어',
  '中文',
  'العربية',
  'हिन्दी',
]

function TranslatedPdfExport({ notify }: { notify: (notice: Notice) => void }) {
  const projectLanguage = useComicStore(state => state.project.language)
  const hasDirectorPlan = useComicStore(state => Boolean(state.project.director?.plan))
  const [language, setLanguage] = useState(projectLanguage || 'Español')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')

  const exportTranslated = async () => {
    const target = language.trim()
    if (!target || !hasDirectorPlan || busy) return
    const state = useComicStore.getState()
    const sourcePlan = planWithCanvasText(state.project)
    if (!sourcePlan) {
      notify({ kind: 'error', text: 'This comic does not have an editable Director plan.' })
      return
    }
    const originalPageId = state.currentPageId
    const translationWriting = writingForOperation(state.project.director!.input, 'translate')
    let temporaryApplied = false
    setBusy(true)
    try {
      const working = structuredClone(sourcePlan)
      for (let pageIndex = 0; pageIndex < working.pages.length; pageIndex += 1) {
        setProgress(`Translating ${pageIndex + 1}/${working.pages.length}`)
        const cacheKey = translationCacheKey(
          working.pages[pageIndex],
          target,
          state.project.translationGlossary,
          translationWriting,
        )
        const cached = comicTranslationCache.get(cacheKey)
        if (cached) {
          working.pages[pageIndex] = structuredClone(cached)
          continue
        }
        const result = await api.rewriteComicTextPage({
          plan: working,
          pageIndex,
          mode: 'translate',
          instruction: '',
          targetLanguage: target,
          dialogueDensity: state.project.director!.input.dialogueDensity,
          glossary: state.project.translationGlossary,
          ...translationWriting,
        })
        working.pages[pageIndex] = result.page
        comicTranslationCache.set(cacheKey, structuredClone(result.page))
      }
      working.language = target
      const translatedProject = simplifyDirectorText({
        ...state.project,
        title: `${state.project.title} — ${target}`,
        language: target,
        director: {
          ...state.project.director!,
          plan: normalizeComicPlan(working, state.project.director!.input.dialogueDensity),
        },
      })
      state.patchProject(translatedProject)
      temporaryApplied = true
      await wait(100)
      await exportComicPdf((current, total) => setProgress(`PDF ${current}/${total}`))
      notify({
        kind: 'ok',
        text: `PDF exported in ${target}; the editable original was preserved.`,
      })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      if (temporaryApplied) {
        useComicStore.getState().undo()
        if (originalPageId) useComicStore.getState().setCurrentPage(originalPageId)
      }
      setBusy(false)
      setProgress('')
    }
  }

  return (
    <div className="flex items-center gap-1">
      <input
        className={`${input} w-28`}
        list="comic-toolbar-languages"
        value={language}
        onChange={event => setLanguage(event.target.value)}
        placeholder="Language"
        title="Choose or type any export language"
      />
      <datalist id="comic-toolbar-languages">
        {TRANSLATION_LANGUAGES.map(item => <option key={item} value={item} />)}
      </datalist>
      <button
        className={`${button} whitespace-nowrap border-emerald-500/50 text-emerald-400`}
        disabled={busy || !hasDirectorPlan || !language.trim()}
        onClick={exportTranslated}
        title={hasDirectorPlan
          ? 'Translate only the lettering, export a PDF, then restore the editable original'
          : 'Generate the comic with Director before using translated export'}
      >
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
        {progress || `Export in ${language.trim() || 'language'}`}
      </button>
    </div>
  )
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
      insertAssetIntoPage(await generateImageAsset(provider, prompt.trim(), model))
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
  const parentPanel = element?.parentId
    ? page?.elements.find(
      (item): item is ComicPanelElement =>
        item.id === element.parentId && item.type === 'panel',
    )
    : undefined
  const patch = (next: Partial<ComicElement>) => element && update(pageId, element.id, next, true)
  const detachFromPanel = () => {
    if (!page || !element?.parentId) return
    update(pageId, element.id, {
      parentId: null,
      x: element.x + (parentPanel?.x ?? 0),
      y: element.y + (parentPanel?.y ?? 0),
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
              {parentPanel && (
                <div className="space-y-2 rounded-lg border border-accent-blue/30 bg-accent-blue/5 p-2">
                  <p className="text-[9px] leading-relaxed text-text-muted">
                    Drag the image to reframe it. Hold Shift for fine movement or Ctrl-wheel over
                    the selected image to zoom.
                  </p>
                  <Field label={`Crop zoom · ${Math.round(Math.max(
                    element.width / parentPanel.width,
                    element.height / parentPanel.height,
                  ) * 100)}%`}>
                    <input
                      className={input}
                      type="range"
                      min={1}
                      max={3}
                      step={.02}
                      value={Math.max(1, Math.min(3, Math.max(
                        element.width / parentPanel.width,
                        element.height / parentPanel.height,
                      )))}
                      onChange={event => {
                        const scale = Number(event.target.value)
                        const width = parentPanel.width * scale
                        const height = parentPanel.height * scale
                        patch({
                          width,
                          height,
                          x: element.x + (element.width - width) / 2,
                          y: element.y + (element.height - height) / 2,
                        })
                      }}
                    />
                  </Field>
                  <div className="grid grid-cols-2 gap-1">
                    <button
                      className={button}
                      onClick={() => patch({
                        x: (parentPanel.width - element.width) / 2,
                        y: (parentPanel.height - element.height) / 2,
                      })}
                    >
                      Center crop
                    </button>
                    <button
                      className={button}
                      onClick={() => patch({
                        x: 0,
                        y: 0,
                        width: parentPanel.width,
                        height: parentPanel.height,
                        objectFit: 'cover',
                      })}
                    >
                      Reset crop
                    </button>
                  </div>
                </div>
              )}
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
  writingProvider: 'maestro',
  writingModel: 'deepseek-v4-pro',
  writingBaseUrl: 'https://api.deepseek.com',
  provider: 'maestro',
  imageModel: useStore.getState().selectedModelPerMode.image || 'flux2_klein_9b',
  characters: [],
})

function stagedStoryDirectorRequest(): ComicDirectorRequest | null {
  try {
    const staged = JSON.parse(window.localStorage.getItem('maestro-story-comic-draft') || 'null')
    if (!staged || typeof staged !== 'object') return null
    return { ...initialDirector(), ...staged }
  } catch {
    return null
  }
}

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
    project.director?.input
      ?? stagedStoryDirectorRequest()
      ?? { ...initialDirector(), characters: project.characters })
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
  const previousProjectId = useRef(project.id)
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
  const externalWritingLlm = Boolean(request.writingProvider && request.writingProvider !== 'maestro')
  useEffect(() => {
    const changedProject = previousProjectId.current !== project.id
    previousProjectId.current = project.id
    if (changedProject) {
      setPendingPlan(null)
      setRecoveryJobId('')
    }
    const staged = stagedStoryDirectorRequest()
    setRequest(project.director?.input ?? staged ?? { ...initialDirector(), characters: project.characters })
    if (staged) {
      try { window.localStorage.removeItem('maestro-story-comic-draft') } catch { /* no-op */ }
    }
    // A project switch resets the form. Director edits inside the same project
    // are already applied through patch() and must not reset in-progress input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])
  useEffect(() => {
    const receiveStagedStory = () => {
      const staged = stagedStoryDirectorRequest()
      if (!staged) return
      setRequest(staged)
      try { window.localStorage.removeItem('maestro-story-comic-draft') } catch { /* no-op */ }
    }
    window.addEventListener('maestro:comic-staged', receiveStagedStory)
    return () => window.removeEventListener('maestro:comic-staged', receiveStagedStory)
  }, [])
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
    if (!director.scriptApprovedAt && !window.confirm(
      'This script version has not been approved in the Script tab. Generate artwork anyway?',
    )) return false
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
        const characterReference = character?.referenceAssetId
          ? useComicStore.getState().project.assets[character.referenceAssetId]?.source
          : undefined
        const currentDirector = useComicStore.getState().project.director!
        const maestroState = useStore.getState()
        const selectedImageModel = maestroState.models.find(model =>
          model.model_type === currentDirector.imageModel)
        const localSupportsReferences = currentDirector.provider === 'maestro'
          && Boolean(
            selectedImageModel?.supports_ref_images
            || (currentDirector.imageModel === maestroState.params.model_type
              && maestroState.modelOptions?.image_ref_choices),
          )
        const worldReferenceId = currentDirector.input.worldReferenceAssetIds?.[0]
        const reference = characterReference || (localSupportsReferences && worldReferenceId
          ? useComicStore.getState().project.assets[worldReferenceId]?.source
          : undefined)
        const prompt = buildDirectorImagePrompt(
          currentDirector,
          task.plan.imagePrompt,
          state.project.style.promptSuffix,
          task.plan,
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
          asset = await generateImageAsset(
            currentDirector.provider,
            prompt,
            currentDirector.imageModel,
            reference,
            '',
            {
              panelId: task.plan.id,
              existingJobId,
              onJobSubmitted: jobId => rememberPanelJob(task.plan.id, jobId),
              onPollRetry: attempt => report(
                `Connection interrupted while checking panel ${index + 1}; retrying (${attempt}/20)…`,
                { current: index + 1, total: tasks.length },
              ),
              onProviderRetry: attempt => report(
                `MiniMax temporarily failed on panel ${index + 1}; retrying (${attempt}/2)…`,
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

  const transformTextPlan = async (
    mode: 'rewrite' | 'translate',
    languageOverride?: string,
  ): Promise<ComicPlan> => {
    const current = useComicStore.getState().project
    const captured = planWithCanvasText(current)
    if (!captured) throw new Error('This comic does not have an editable Director plan')
    const working = structuredClone(captured)
    const translationLanguage = (languageOverride ?? targetLanguage).trim()
    const operationWriting = writingForOperation(current.director!.input, mode)
    for (let pageIndex = 0; pageIndex < working.pages.length; pageIndex += 1) {
      report(`${mode === 'translate' ? 'Translating' : 'Rewriting'} page ${pageIndex + 1} of ${working.pages.length}…`, {
        current: pageIndex + 1,
        total: working.pages.length,
      })
      const cacheKey = mode === 'translate'
        ? translationCacheKey(
          working.pages[pageIndex],
          translationLanguage,
          current.translationGlossary,
          operationWriting,
        )
        : ''
      const cached = cacheKey ? comicTranslationCache.get(cacheKey) : undefined
      if (cached) {
        working.pages[pageIndex] = structuredClone(cached)
        continue
      }
      const result = await api.rewriteComicTextPage({
        plan: working,
        pageIndex,
        mode,
        instruction: textInstruction,
        targetLanguage: translationLanguage,
        dialogueDensity: current.director!.input.dialogueDensity,
        glossary: current.translationGlossary,
        ...operationWriting,
      })
      working.pages[pageIndex] = result.page
      if (cacheKey) comicTranslationCache.set(cacheKey, structuredClone(result.page))
    }
    if (mode === 'translate') working.language = translationLanguage
    return normalizeComicPlan(working, current.director!.input.dialogueDensity)
  }

  const applyTextOperation = async (
    mode: 'rewrite' | 'translate',
    languageOverride?: string,
  ) => {
    const translationLanguage = (languageOverride ?? targetLanguage).trim()
    if (mode === 'translate' && !translationLanguage) return
    setBusy(mode === 'translate' ? 'translation' : 'text')
    try {
      const state = useComicStore.getState()
      const plan = await transformTextPlan(mode, translationLanguage)
      const translated = mode === 'translate'
      const next = simplifyDirectorText({
        ...state.project,
        language: translated ? translationLanguage : state.project.language,
        director: { ...state.project.director!, plan },
      })
      state.patchProject(next)
      report(`${translated ? `Translation to ${translationLanguage}` : 'Text rewrite'} applied without changing artwork.`, {
        state: 'complete',
      })
      notify({ kind: 'ok', text: translated
        ? `Comic text repaired in ${translationLanguage} and left editable.`
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

  const confirmNewComic = (withImages: boolean) => {
    const estimatedPanels = Math.max(1, request.pageCount * request.panelsPerPage)
    const artworkNotice = withImages
      ? ` After the script is ready, up to ${estimatedPanels} panel images will be generated and may use provider credits.`
      : ''
    return window.confirm(
      `Create a new comic? When planning succeeds, it will replace the comic currently open and any unsaved changes will be lost.${artworkNotice}\n\nThe current comic will remain untouched if planning fails or is cancelled.`,
    )
  }

  const placePlan = async (rawPlan: ComicPlan, withImages: boolean) => {
      const plan = normalizeComicPlan(rawPlan, request.dialogueDensity)
      setPendingPlan(plan)
      report(`Plan received: ${plan.pages.length} pages and ${
        plan.pages.reduce((total, page) => total + page.panels.length, 0)
      } panels.`)
      const currentProject = useComicStore.getState().project
      const freshProject = createComicProject()
      const characterReferenceIds = new Set(
        [...request.characters, ...plan.characters].flatMap(character => [
          character.referenceAssetId,
          ...(character.referenceAssetIds || []),
        ]).filter((assetId): assetId is string => Boolean(assetId)),
      )
      freshProject.assets = Object.fromEntries(
        [...characterReferenceIds]
          .map(assetId => currentProject.assets[assetId])
          .filter((asset): asset is ComicAsset => Boolean(asset))
          .map(asset => [asset.id, asset]),
      )
      freshProject.style = structuredClone(currentProject.style)
      freshProject.pageNumbering = structuredClone(currentProject.pageNumbering)
      freshProject.format = {
        ...freshProject.format,
        preset: request.format,
        ...(request.format !== 'custom' ? COMIC_FORMATS[request.format] : {
          width: currentProject.format.width,
          height: currentProject.format.height,
          dpi: currentProject.format.dpi,
        }),
      }
      const next = projectFromPlan(plan, freshProject)
      next.director = {
        planId: plan.id,
        provider: request.provider,
        imageModel: request.imageModel,
        input: request,
        plan,
        completedPanelIds: [],
        panelJobs: {},
        scriptVersion: 1,
        scriptApprovedAt: withImages ? new Date().toISOString() : undefined,
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
    if (!confirmNewComic(withImages)) return
    rememberPrompt({
      prompt: request.premise,
      mode: 'comic-plan',
      model: request.writingModel || request.writingProvider,
      workspace: useStore.getState().activeWorkspace,
      source: 'generation',
    })
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
    if (!confirmNewComic(createCompleteComic)) return
    setBusy('plan')
    setStartedAt(Date.now())
    try {
      const jobId = recoveryJobId.trim()
      let plan: ComicPlan | null = null
      // An explicitly entered durable job is authoritative. A stale browser
      // result from an older session must never shadow the ID visible here.
      if (jobId) {
        report(`Checking the saved state of ${jobId}…`)
        const job = await api.fetchComicPlanJob(jobId)
        if (job.status === 'completed' && job.result?.plan) {
          report(`Recovered completed plan ${jobId} without calling the LLM again.`)
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
    if (!director.scriptApprovedAt && !window.confirm(
      'This script version has not been approved in the Script tab. Generate this panel anyway?',
    )) return
    setSingleBusy(planned.id)
    try {
      const character = director.plan.characters.find(item => planned.characters.includes(item.id))
      const characterReference = character?.referenceAssetId
        ? state.project.assets[character.referenceAssetId]?.source
        : undefined
      const maestroState = useStore.getState()
      const selectedImageModel = maestroState.models.find(model =>
        model.model_type === director.imageModel)
      const localSupportsReferences = director.provider === 'maestro'
        && Boolean(
          selectedImageModel?.supports_ref_images
          || (director.imageModel === maestroState.params.model_type
            && maestroState.modelOptions?.image_ref_choices),
        )
      const worldReferenceId = director.input.worldReferenceAssetIds?.[0]
      const reference = characterReference || (localSupportsReferences && worldReferenceId
        ? state.project.assets[worldReferenceId]?.source
        : undefined)
      const existingJobId = director.completedPanelIds.includes(planned.id)
        ? undefined
        : director.panelJobs?.[planned.id]
      const asset = await generateImageAsset(
        director.provider,
        buildDirectorImagePrompt(director, planned.imagePrompt, state.project.style.promptSuffix, planned),
        director.imageModel,
        reference,
        '',
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
          {externalWritingLlm
            ? `Comic override · ${request.writingProvider === 'deepseek' ? 'DeepSeek' : request.writingProvider === 'minimax' ? 'MiniMax' : request.writingProvider === 'openai' ? 'OpenAI' : 'Custom compatible'} · ${request.writingModel || 'Choose a model'}`
            : `Maestro default · ${planningLlmProviderLabel[planningLlmProvider] || planningLlmProvider} · ${planningLlmModel}`}
        </div>
        <div className="mt-0.5 text-[9px] text-text-muted">
          {externalWritingLlm
            ? `${request.writingProvider === 'deepseek' ? 'https://api.deepseek.com' : request.writingProvider === 'minimax' ? 'https://api.minimax.io/v1' : request.writingProvider === 'openai' ? 'https://api.openai.com' : request.writingBaseUrl || 'Configure the custom profile'} · internal LLM is left untouched`
            : planningLlmIsActive
              ? 'Active now'
              : llmStatus?.loaded
                ? `Will switch from ${llmStatus.model_id || 'the currently loaded model'} when planning starts`
                : 'Auto-loads when planning starts'}
        </div>
      </div>
      <ComicWritingProviderFields value={request} onChange={patch} disabled={busy !== null} />
      <Field label="Story premise"><textarea className={input} rows={5} value={request.premise} onChange={event => patch('premise', event.target.value)} placeholder="What happens in the comic?" /></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Pages"><input className={input} type="number" min={1} max={100} value={request.pageCount} onChange={event => patch('pageCount', Math.max(1, Number(event.target.value)))} /></Field>
        <Field label="Panels / page"><input className={input} type="number" min={1} max={12} value={request.panelsPerPage} onChange={event => patch('panelsPerPage', Math.max(1, Number(event.target.value)))} /></Field>
        <Field label="Language">
          <EditableLanguageInput className={input} value={request.language} onChange={value => patch('language', value)} />
        </Field>
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
            <button
              className={`${button} w-full border-amber-500/50 text-amber-300`}
              disabled={busy !== null}
              onClick={() => applyTextOperation(
                'translate',
                project.language || project.director?.plan.language || project.director?.input.language,
              )}
            >
              {busy === 'translation' ? <Loader2 size={12} className="animate-spin" /> : <WandSparkles size={12} />}
              Fix mixed-language lines · {project.language || project.director?.plan.language || project.director?.input.language}
            </button>
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
              {TRANSLATION_LANGUAGES.map(language =>
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
          {project.director.plan.storyStructure?.length ? (
            <details className="rounded-lg border border-border bg-bg-tertiary/30 p-2" open>
              <summary className="cursor-pointer text-[10px] font-medium text-text-secondary">
                Dramatic structure · {project.director.plan.storyStructure.length} page beats
              </summary>
              <ol className="mt-2 space-y-2">
                {project.director.plan.storyStructure.map(beat => (
                  <li key={beat.pageNumber} className="text-[9px] leading-relaxed text-text-muted">
                    <strong className="text-text-secondary">
                      {beat.pageNumber}. {beat.stage}
                    </strong>
                    <span className="block">{beat.goal}</span>
                    <span className="block text-amber-300/80">Turn: {beat.turningPoint}</span>
                  </li>
                ))}
              </ol>
            </details>
          ) : null}
          <details className="rounded-lg border border-border bg-bg-tertiary/30 p-2">
            <summary className="cursor-pointer text-[10px] font-medium text-text-secondary">
              {(project.director.plan.styleBible || '').trim()
                ? 'Visual continuity bible created by the LLM'
                : 'No separate visual bible needed'}
            </summary>
            {(project.director.plan.styleBible || '').trim() ? (
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
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewZoom, setPreviewZoom] = useState(1)
  const [notice, setNotice] = useState<Notice>(null)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [comicHistory, setComicHistory] = useState<api.ComicHistoryEntry[]>([])
  const importRef = useRef<HTMLInputElement>(null)
  const previewViewportRef = useRef<HTMLDivElement>(null)
  const maestroOutputs = useStore(state => state.outputs)
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const comicOutputs = maestroOutputs.filter(output => output.type === 'comic')
  const currentPageIndex = Math.max(
    0,
    project.pages.findIndex(page => page.id === currentPageId),
  )
  const goToPage = (index: number) => {
    const page = project.pages[Math.max(0, Math.min(project.pages.length - 1, index))]
    if (page) useComicStore.getState().setCurrentPage(page.id)
  }
  const notify = (value: Notice) => {
    setNotice(value)
    if (value) setTimeout(() => setNotice(null), 5000)
  }
  const notifyWorkflow = (kind: 'ok' | 'error', text: string) => notify({ kind, text })
  const checkpointCurrent = async (
    reason: string,
    snapshot = useComicStore.getState(),
  ) => {
    try {
      return await api.createComicHistory(snapshot.project, reason, snapshot.persistedName)
    } catch (error) {
      console.warn('[Comic history] Could not create checkpoint:', error)
      return null
    }
  }
  const refreshComicHistory = async () => {
    setHistoryLoading(true)
    try {
      setComicHistory(await api.listComicHistory())
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setHistoryLoading(false)
    }
  }
  const openComicHistory = () => {
    setHistoryOpen(true)
    void refreshComicHistory()
  }
  const restoreComicHistory = async (entry: api.ComicHistoryEntry) => {
    if (dirty && !confirm('Restore this checkpoint as a new editable copy? Your current comic will be backed up first.')) return
    setHistoryLoading(true)
    try {
      await checkpointCurrent('Before history restore')
      const restored = await api.loadComicHistory(entry.id)
      const state = useComicStore.getState()
      state.setProject(restored.project, null)
      useComicStore.getState().patchProject({})
      setHistoryOpen(false)
      notify({ kind: 'ok', text: `Restored “${entry.title}” as an unsaved editable copy.` })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setHistoryLoading(false)
    }
  }
  const generateCharacterReference = async (character: ComicCharacter) => {
    const state = useComicStore.getState()
    const director = state.project.director
    const provider = director?.provider || 'maestro'
    const model = director?.imageModel || useStore.getState().selectedModelPerMode.image
    const prompt = [
      'CHARACTER REFERENCE SHEET: one single character, neutral full-body three-quarter pose and a clean head-and-shoulders inset, plain unobtrusive background, no text, no labels, no comic panels.',
      `Identity: ${character.name}.`,
      character.role ? `Story role: ${character.role}.` : '',
      character.description,
      character.visualNotes,
      character.wardrobe,
      character.personality ? `Expression must communicate: ${character.personality}.` : '',
      character.negativePrompt ? `Strictly avoid: ${character.negativePrompt}.` : '',
      state.project.style.promptSuffix,
    ].filter(Boolean).join(' ')
    const primary = character.referenceAssetId
      ? state.project.assets[character.referenceAssetId]?.source
      : undefined
    const asset = await generateImageAsset(provider, prompt, model, primary)
    asset.characterIds = [character.id]
    state.addAsset(asset)
    const latest = useComicStore.getState()
    const characters = latest.project.characters.map(item => item.id === character.id ? {
      ...item,
      referenceAssetId: asset.id,
      referenceAssetIds: Array.from(new Set([...(item.referenceAssetIds || []), asset.id])),
    } : item)
    const currentDirector = latest.project.director
    latest.patchProject({
      characters,
      ...(currentDirector ? { director: {
        ...currentDirector,
        input: { ...currentDirector.input, characters },
        plan: { ...currentDirector.plan, characters },
      } } : {}),
    })
  }
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (previewOpen) return
      const target = event.target as HTMLElement | null
      if (target?.matches('input, textarea, select, [contenteditable="true"]')) return
      const state = useComicStore.getState()
      const page = state.project.pages.find(item => item.id === state.currentPageId)
      const element = page?.elements.find(item => item.id === state.selectedId)
      const modifier = event.ctrlKey || event.metaKey
      if (modifier && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) state.redo()
        else state.undo()
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
  }, [previewOpen])
  useEffect(() => {
    if (!previewOpen) return
    const viewport = previewViewportRef.current
    const page = project.pages.find(item => item.id === currentPageId)
    if (!viewport || !page) return
    const fit = () => {
      const bounds = viewport.getBoundingClientRect()
      const horizontalPadding = 48
      const verticalPadding = 48
      const nextZoom = Math.min(
        2,
        Math.max(.05, (bounds.width - horizontalPadding) / page.width),
        Math.max(.05, (bounds.height - verticalPadding) / page.height),
      )
      setPreviewZoom(nextZoom)
    }
    const frame = window.requestAnimationFrame(fit)
    const observer = new ResizeObserver(fit)
    observer.observe(viewport)
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreviewOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [previewOpen, currentPageId, project.pages])

  useEffect(() => {
    const snapshot = useComicStore.getState()
    const timer = window.setTimeout(() => {
      void checkpointCurrent('Comic opened or created', snapshot)
    }, 2500)
    return () => window.clearTimeout(timer)
    // The project identity is the intended boundary for this checkpoint.
  }, [project.id, activeWorkspace])

  useEffect(() => {
    if (!dirty) return
    const snapshot = useComicStore.getState()
    const timer = window.setTimeout(() => {
      void checkpointCurrent('Automatic editing checkpoint', snapshot)
    }, 12000)
    return () => window.clearTimeout(timer)
    // updatedAt resets the inactivity window without serialising drag frames.
  }, [dirty, project.updatedAt, activeWorkspace])
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

  const save = async (withPreview = true) => {
    setSaving(true)
    try {
      const preview = withPreview ? await captureComicPage(0.35) : undefined
      const result = await api.saveComicProject(useComicStore.getState().project, preview, persistedName)
      useComicStore.getState().setPersistedName(result.name)
      useComicStore.getState().markSaved()
      if (withPreview) {
        await checkpointCurrent('Manual save', useComicStore.getState())
        useStore.getState().loadOutputs()
        notify({ kind: 'ok', text: 'Comic saved in the active Maestro workspace.' })
      }
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    if (!persistedName || !dirty || saving) return
    const timer = window.setTimeout(() => save(false), 5000)
    return () => window.clearTimeout(timer)
    // save intentionally reads the current store snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, persistedName, saving, project.updatedAt])

  const importProject = async (file?: File) => {
    if (!file) return
    if (dirty && !confirm('Import this comic and replace the current unsaved work? A recovery checkpoint will be created first.')) {
      if (importRef.current) importRef.current.value = ''
      return
    }
    try {
      await checkpointCurrent('Before comic import')
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
      await checkpointCurrent('Before opening saved comic')
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

  const newProject = async () => {
    if (dirty && !confirm('Create a new comic and discard unsaved changes?')) return
    await checkpointCurrent('Before creating a new comic')
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
            <button className={button} onClick={() => void newProject()}><Plus size={13} /> New</button>
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
            <button className={button} onClick={openComicHistory} title="Browse recoverable comic versions">
              <HistoryIcon size={13} /> History
            </button>
            <button className={button} onClick={() => importRef.current?.click()}><Upload size={13} /> Import</button>
            <input ref={importRef} type="file" accept=".json,.comic.json" className="hidden" onChange={event => importProject(event.target.files?.[0])} />
            <button className={button} disabled={saving} onClick={() => save(true)}>{saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save</button>
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
              <TranslatedPdfExport notify={notify} />
              <button className={button} onClick={() => setToolbarCollapsed(true)} title="Collapse comic toolbar">
                <ChevronUp size={13} />
              </button>
            </div>
          </>
        )}
      </header>
      {historyOpen && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-4" onMouseDown={() => setHistoryOpen(false)}>
          <div
            className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl"
            onMouseDown={event => event.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold text-text-primary">Comic history</h2>
                <p className="text-[10px] text-text-muted">
                  Durable recovery checkpoints in workspace “{activeWorkspace}”. Restoring creates a new unsaved copy.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button className={button} disabled={historyLoading} onClick={() => void refreshComicHistory()}>
                  {historyLoading ? <Loader2 size={13} className="animate-spin" /> : <HistoryIcon size={13} />} Refresh
                </button>
                <button className={button} onClick={() => setHistoryOpen(false)} aria-label="Close comic history">
                  <X size={13} />
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {historyLoading && comicHistory.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-12 text-xs text-text-muted">
                  <Loader2 size={14} className="animate-spin" /> Loading checkpoints…
                </div>
              ) : comicHistory.length === 0 ? (
                <div className="py-12 text-center text-xs text-text-muted">
                  No comic checkpoints yet. A checkpoint is created after editing pauses and before destructive actions.
                </div>
              ) : (
                <div className="space-y-2">
                  {comicHistory.map(entry => (
                    <div
                      key={entry.id}
                      className={`flex items-center gap-3 rounded-lg border p-3 ${
                        entry.comicId === project.id
                          ? 'border-accent-blue/40 bg-accent-blue/5'
                          : 'border-border bg-bg-tertiary'
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-xs font-medium text-text-primary">{entry.title}</span>
                          {entry.comicId === project.id && (
                            <span className="shrink-0 rounded bg-accent-blue/15 px-1.5 py-0.5 text-[9px] text-accent-blue">Current comic</span>
                          )}
                        </div>
                        <div className="mt-1 truncate text-[10px] text-text-muted">
                          {entry.reason} · {entry.pageCount} pages · {entry.assetCount} assets
                          {entry.persistedName ? ` · ${entry.persistedName}` : ''}
                        </div>
                        <div className="mt-0.5 text-[9px] text-text-muted">
                          {new Date(entry.createdAt).toLocaleString()}
                        </div>
                      </div>
                      <button
                        className={button}
                        disabled={historyLoading}
                        onClick={() => void restoreComicHistory(entry)}
                      >
                        Restore copy
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {notice && (
        <div className={`shrink-0 px-3 py-1.5 text-xs ${notice.kind === 'ok' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/15 text-red-300'}`}>{notice.text}</div>
      )}
      <div className="flex flex-1 min-h-0">
        <PagesRail />
        <section className="flex-1 min-w-0 flex flex-col bg-[#15171b]">
          <div className="shrink-0 border-b border-border p-2 flex items-center justify-center gap-2 text-xs text-text-muted">
            <button
              className={button}
              disabled={currentPageIndex === 0}
              onClick={() => goToPage(currentPageIndex - 1)}
              title="Previous page"
            >
              <ChevronLeft size={12} />
            </button>
            <select
              className={`${input} w-28`}
              value={currentPageId}
              onChange={event => useComicStore.getState().setCurrentPage(event.target.value)}
              aria-label="Current comic page"
            >
              {project.pages.map((page, index) => (
                <option key={page.id} value={page.id}>Page {index + 1} / {project.pages.length}</option>
              ))}
            </select>
            <button
              className={button}
              disabled={currentPageIndex >= project.pages.length - 1}
              onClick={() => goToPage(currentPageIndex + 1)}
              title="Next page"
            >
              <ChevronRight size={12} />
            </button>
            <div className="h-5 border-l border-border mx-1" />
            <button className={button} onClick={() => setZoom(zoom - .1)}>-</button>
            <span className="w-12 text-center">{Math.round(zoom * 100)}%</span>
            <button className={button} onClick={() => setZoom(zoom + .1)}>+</button>
            <button
              className={button}
              onClick={() => {
                useComicStore.getState().setSelected(null)
                setPreviewOpen(true)
              }}
              title="Open a full-screen, read-only page preview"
            >
              <Maximize2 size={12} /> Fit
            </button>
            <span className="ml-2">{project.format.width} × {project.format.height}</span>
          </div>
          <div className="flex-1 min-h-0 overflow-auto">
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
              <span className="[writing-mode:vertical-rl]">Comic tools</span>
            </button>
          ) : (
            <>
              <div className="flex border-b border-border">
                <div className="grid flex-1 grid-cols-3">
                  {([
                    ['assets', 'Assets'],
                    ['inspector', 'Inspector'],
                    ['script', 'Script'],
                    ['characters', 'Characters'],
                    ['quality', 'Quality'],
                    ['video', 'Video'],
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
                {sideTab === 'script' && <ComicScriptPanel notify={notifyWorkflow} />}
                {sideTab === 'characters' && <ComicCharactersPanel generateReference={generateCharacterReference} notify={notifyWorkflow} />}
                {sideTab === 'quality' && <ComicQualityPanel notify={notifyWorkflow} />}
                {sideTab === 'video' && <ComicVideoPanel notify={notifyWorkflow} />}
                {sideTab === 'director' && <ComicDirectorPanel notify={notify} />}
              </div>
            </>
          )}
        </aside>
      </div>
      {previewOpen && (
        <div className="fixed inset-0 z-[2000] flex flex-col bg-[#090a0d]/95 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Read-only comic preview">
          <div className="shrink-0 flex items-center gap-2 border-b border-white/10 bg-black/40 px-3 py-2 text-xs text-white/70">
            <span className="font-medium text-white">Read-only preview</span>
            <span>Page {currentPageIndex + 1} / {project.pages.length}</span>
            <div className="ml-auto flex items-center gap-1.5">
              <button className={button} disabled={currentPageIndex === 0} onClick={() => goToPage(currentPageIndex - 1)}><ChevronLeft size={13} /> Previous</button>
              <button className={button} disabled={currentPageIndex >= project.pages.length - 1} onClick={() => goToPage(currentPageIndex + 1)}>Next <ChevronRight size={13} /></button>
              <button className={button} onClick={() => setPreviewOpen(false)}><X size={13} /> Close</button>
            </div>
          </div>
          <div ref={previewViewportRef} className="flex min-h-0 flex-1 items-center justify-center overflow-hidden p-6">
            <ComicCanvas readOnly zoomOverride={previewZoom} domId="maestro-comic-preview-page" />
          </div>
        </div>
      )}
    </div>
  )
}
