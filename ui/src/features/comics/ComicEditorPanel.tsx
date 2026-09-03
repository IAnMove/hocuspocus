import { useEffect, useMemo, useRef, useState } from 'react'
import type { ParseKeys } from 'i18next'
import {
  BookOpen, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Copy, Download, Eye, EyeOff, FileJson,
  History as HistoryIcon, ImagePlus, Loader2, Lock, PanelTop, Plus, Redo2, Save, Sparkles, Trash2,
  Maximize2, Type, Undo2, Unlock, Upload, WandSparkles, X,
} from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { getModelMode, useStore } from '../../stores/useStore'
import * as api from '../../api/client'
import { EditableLanguageInput } from '../../components/common/EditableLanguageInput'
import { generateImageAsset } from '../../lib/imageGeneration'
import { writingBaseUrlFromProfile, writingProviderFromText } from '../../lib/productionProfile'
import {
  buildDirectorImagePrompt,
  generateDirectorArtwork,
  miniMaxAspectRatio,
  panelIdentityReference,
} from './generateArtwork'
import { rememberPrompt } from '../../lib/promptHistory'
import { ComicCanvas } from './ComicCanvas'
import {
  ComicCharactersPanel, ComicQualityPanel, ComicScriptPanel, ComicVideoPanel,
  ComicVideoPreflightPanel, ComicWritingProviderFields,
} from './ComicWorkflowPanels'
import {
  comicId, COMIC_FORMATS, createComicProject, normalizeComicProject, panelsForCount,
  mergeComicVideoOverrideFields, normalizeComicPlan, planWithCanvasText, projectFromPlan,
  repairComicText, simplifyDirectorText, varyDirectorLayouts, withComicContentLanguage,
} from './model'
import { COMIC_EFFECTS, COMIC_LAYOUTS, createEffect } from './presets'
import { useComicStore } from './store'
import { COMIC_HANDOFF_STORAGE_KEY, resolveComicSource } from './provenance'
import { captureComicPage, exportComicCbz, exportComicJson, exportComicPagePng, exportComicPdf } from './export'
import type {
  ComicAsset, ComicCharacter, ComicDirectorRequest, ComicElement, ComicImageElement,
  ComicPanelElement, ComicPlan, ComicPlanPanel, ComicProject, ComicTextElement,
  ComicPlanPage, ComicVideoOverrideField,
} from './types'

type SideTab = 'assets' | 'inspector' | 'script' | 'characters' | 'quality' | 'video' | 'pre' | 'director'
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
const comicsKey = (key: string) => key as ParseKeys<'comics'>
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
  const { t } = useUiTranslation('comics')
  const canonical = panelScript(panel)
  const [draft, setDraft] = useState({ canonical, value: canonical })
  const value = draft.canonical === canonical ? draft.value : canonical
  return (
    <textarea
      className={input}
      rows={3}
      value={value}
      placeholder={t('lettering.placeholder')}
      onChange={event => setDraft({ canonical, value: event.target.value })}
      onBlur={() => value !== canonical && onCommit(value)}
    />
  )
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
  const { t } = useUiTranslation('comics')
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
      notify({ kind: 'error', text: t('generate.noPlan') })
      return
    }
    const originalPageId = state.currentPageId
    const translationWriting = writingForOperation(state.project.director!.input, 'translate')
    let temporaryApplied = false
    setBusy(true)
    try {
      const working = structuredClone(sourcePlan)
      for (let pageIndex = 0; pageIndex < working.pages.length; pageIndex += 1) {
        setProgress(t('export.translating', { current: pageIndex + 1, total: working.pages.length }))
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
      await exportComicPdf((current, total) => setProgress(t('export.pdfProgress', { current, total })))
      notify({
        kind: 'ok',
        text: t('export.pdfKept', { language: target }),
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
        placeholder={t('export.language')}
        title={t('export.languageTitle')}
      />
      <datalist id="comic-toolbar-languages">
        {TRANSLATION_LANGUAGES.map(item => <option key={item} value={item} />)}
      </datalist>
      <button
        className={`${button} whitespace-nowrap border-emerald-500/50 text-emerald-400`}
        disabled={busy || !hasDirectorPlan || !language.trim()}
        onClick={exportTranslated}
        title={hasDirectorPlan
          ? t('export.translateTitle')
          : t('export.needDirector')}
      >
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
        {progress || t('export.inLanguage', { language: language.trim() || t('export.languageFallback') })}
      </button>
    </div>
  )
}

function PagesRail() {
  const { t } = useUiTranslation('comics')
  const { t: tCommon } = useUiTranslation('common')
  const project = useComicStore(state => state.project)
  const current = useComicStore(state => state.currentPageId)
  const setCurrent = useComicStore(state => state.setCurrentPage)
  const addPage = useComicStore(state => state.addPage)
  const duplicate = useComicStore(state => state.duplicatePage)
  const movePage = useComicStore(state => state.movePage)
  const remove = useComicStore(state => state.deletePage)
  return (
    <aside className="w-36 shrink-0 border-r border-border bg-bg-secondary p-2 overflow-y-auto">
      <button className={`${button} w-full mb-2`} onClick={addPage}><Plus size={13} /> {t('pages.add')}</button>
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
              <span className="block text-[10px] text-text-muted mt-1">{t('pages.page', { n: index + 1 })}</span>
            </button>
            <div className="flex justify-center gap-1 mt-1">
              <button title={t('pages.moveUp')} disabled={index === 0} onClick={() => movePage(page.id, -1)} className="p-1 text-text-muted hover:text-text-primary disabled:opacity-30">↑</button>
              <button title={t('pages.moveDown')} disabled={index === project.pages.length - 1} onClick={() => movePage(page.id, 1)} className="p-1 text-text-muted hover:text-text-primary disabled:opacity-30">↓</button>
              <button title={tCommon('actions.duplicate')} onClick={() => duplicate(page.id)} className="p-1 text-text-muted hover:text-text-primary"><Copy size={11} /></button>
              <button title={tCommon('actions.delete')} disabled={project.pages.length === 1} onClick={() => remove(page.id)} className="p-1 text-text-muted hover:text-red-400 disabled:opacity-30"><Trash2 size={11} /></button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}

function AssetsPanel() {
  const { t } = useUiTranslation('comics')
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
        <button className={`${button} ${source === 'maestro' ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setSource('maestro')}>{t('assets.hocuspocus')}</button>
        <button className={`${button} ${source === 'project' ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setSource('project')}>{t('assets.project')}</button>
      </div>
      <button className={`${button} w-full`} onClick={() => fileRef.current?.click()} disabled={busy}>
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} {t('assets.upload')}
      </button>
      <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={event => uploadFiles(event.target.files)} />
      <div className="rounded-lg border border-border bg-bg-tertiary/40 p-2 space-y-2">
        <div className="grid grid-cols-2 gap-1">
          <button className={`${button} ${provider === 'maestro' ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setProvider('maestro')}>{t('assets.local')}</button>
          <button className={`${button} ${provider === 'minimax' ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setProvider('minimax')}>{t('assets.minimax')}</button>
        </div>
        <textarea className={input} rows={3} value={prompt} onChange={event => setPrompt(event.target.value)} placeholder={t('assets.promptPlaceholder')} />
        <button className={`${button} w-full`} disabled={busy || !prompt.trim()} onClick={generateOne}>
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {t('assets.generateInto')}
        </button>
        {generationError && <p className="text-[10px] text-red-400">{generationError}</p>}
      </div>
      <p className="text-[10px] text-text-muted">{t('assets.hint')}</p>
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
  const { t } = useUiTranslation('comics')
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
    content = t('inspector.defaultText'),
  ) => {
    if (!page) return
    const selectedPanel = element?.type === 'panel' ? element : undefined
    const text: ComicTextElement = {
      id: comicId('text'), type: 'text', parentId: selectedPanel?.id ?? null,
      x: selectedPanel ? selectedPanel.width * .15 : page.width * .25,
      y: selectedPanel ? selectedPanel.height * .7 : page.height * .4,
      width: selectedPanel ? selectedPanel.width * .7 : page.width * .5,
      height: 100, rotation: 0, zIndex: 30, visible: true,
      letteringType: bubble === 'caption' ? 'caption' : bubble === 'none' ? 'sound-effect' : 'dialogue',
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
        <button className={button} onClick={() => addPanels(4)}><PanelTop size={13} /> {t('inspector.fourPanels')}</button>
        <button className={button} onClick={() => addText()}><Type size={13} /> {t('inspector.addText')}</button>
      </div>
      <div className="grid grid-cols-4 gap-1">
        {[1, 3, 6, 9].map(count => <button key={count} className={button} onClick={() => addPanels(count)}>{count}</button>)}
      </div>
      <div className="grid grid-cols-2 gap-1">
        <button className={button} onClick={() => addText('thought', t('inspector.defaultThought'))}>{t('inspector.thought')}</button>
        <button className={button} onClick={() => addText('caption', t('inspector.defaultCaption'))}>{t('inspector.caption')}</button>
        <button className={button} onClick={() => addText('whisper', t('inspector.defaultWhisper'))}>{t('inspector.whisper')}</button>
        <button className={button} onClick={() => addText('electric', t('inspector.defaultShout'))}>{t('inspector.shout')}</button>
      </div>
      {!element ? (
        <div className="space-y-3">
          <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-text-muted">
            {t('inspector.empty')}
          </div>
          <Field label={t('inspector.pagePreset')}>
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
              <option value="">{t('inspector.choose')}</option>
              <option value="a4">{t('inspector.a4')}</option>
              <option value="a4-landscape">{t('inspector.a4Landscape')}</option>
              <option value="square">{t('inspector.square')}</option>
              <option value="webtoon">{t('inspector.webtoon')}</option>
            </select>
          </Field>
          {page && (
            <div className="grid grid-cols-2 gap-2">
              <Field label={t('inspector.width')}><input className={input} type="number" value={page.width} onChange={event => updatePage(page.id, { width: Math.max(200, Number(event.target.value)) })} /></Field>
              <Field label={t('inspector.height')}><input className={input} type="number" value={page.height} onChange={event => updatePage(page.id, { height: Math.max(200, Number(event.target.value)) })} /></Field>
              <Field label={t('inspector.background')}><input className="h-8 w-full" type="color" value={page.background} onChange={event => updatePage(page.id, { background: event.target.value })} /></Field>
            </div>
          )}
          <Field label={t('inspector.pageNumbers')}>
            <select className={input} value={project.pageNumbering.style} onChange={event => patchProject({ pageNumbering: { style: event.target.value as 'none' | 'plain' | 'circle' } })}>
              <option value="none">{t('inspector.none')}</option>
              <option value="plain">{t('inspector.plain')}</option>
              <option value="circle">{t('inspector.circle')}</option>
            </select>
          </Field>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <strong className="text-xs capitalize text-text-primary">{t(comicsKey(`inspector.type${element.type.charAt(0).toUpperCase()}${element.type.slice(1)}`))}</strong>
            <div className="flex gap-1">
              <button className={button} title={t('inspector.duplicateTitle')} onClick={() => useComicStore.getState().duplicateElement(pageId, element.id)}><Copy size={12} /></button>
              <button className={button} onClick={() => patch({ locked: !element.locked })}>{element.locked ? <Unlock size={12} /> : <Lock size={12} />}</button>
              <button className={`${button} hover:text-red-400`} onClick={() => remove(pageId, element.id)}><Trash2 size={12} /></button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {(['x', 'y', 'width', 'height', 'rotation', 'zIndex'] as const).map(key => (
              <Field key={key} label={t(comicsKey(`inspector.field${key.charAt(0).toUpperCase()}${key.slice(1)}`))}>
                <input className={input} type="number" value={Math.round(Number(element[key]))}
                  onChange={event => patch({ [key]: Number(event.target.value) } as Partial<ComicElement>)} />
              </Field>
            ))}
          </div>
          <label className="flex items-center justify-between text-xs text-text-secondary">
            {t('inspector.visible')}
            <button onClick={() => patch({ visible: element.visible === false })}>{element.visible === false ? <EyeOff size={15} /> : <Eye size={15} />}</button>
          </label>
          <div className="grid grid-cols-2 gap-1">
            <button className={button} onClick={() => patch({ zIndex: Math.max(...(page?.elements.map(item => item.zIndex) ?? [0])) + 1 })}>{t('inspector.bringFront')}</button>
            <button className={button} onClick={() => patch({ zIndex: Math.min(...(page?.elements.map(item => item.zIndex) ?? [0])) - 1 })}>{t('inspector.sendBack')}</button>
          </div>
          {element.type === 'panel' && (
            <div className="space-y-2">
              <Field label={t('inspector.borderWidth')}><input className={input} type="number" min={0} max={30} value={element.borderWidth} onChange={event => patch({ borderWidth: Number(event.target.value) })} /></Field>
              <Field label={t('inspector.borderColor')}><input className="w-full h-8" type="color" value={element.borderColor} onChange={event => patch({ borderColor: event.target.value })} /></Field>
              <Field label={t('inspector.cornerRadius')}><input className={input} type="number" value={element.borderRadius} onChange={event => patch({ borderRadius: Number(event.target.value) })} /></Field>
              <Field label={t('inspector.background')}><input className="w-full h-8" type="color" value={element.background === 'transparent' ? '#ffffff' : element.background} onChange={event => patch({ background: event.target.value })} /></Field>
              <div className="grid grid-cols-2 gap-1">
                <button className={button} onClick={() => patch({ background: 'transparent' })}>{t('inspector.transparent')}</button>
                <button
                  className={`${button} ${element.points ? 'border-accent-blue text-accent-blue' : ''}`}
                  onClick={() => patch({ points: element.points ? undefined : [[0, 0], [1, 0], [1, 1], [0, 1]] })}
                >
                  {element.points ? t('inspector.rectangle') : t('inspector.polygon')}
                </button>
              </div>
            </div>
          )}
          {element.type === 'image' && (
            <div className="space-y-2">
              {parentPanel && (
                <div className="space-y-2 rounded-lg border border-accent-blue/30 bg-accent-blue/5 p-2">
                  <p className="text-[9px] leading-relaxed text-text-muted">
                    {t('inspector.cropHint')}
                  </p>
                  <Field label={t('inspector.cropZoom', { percent: Math.round(Math.max(
                    element.width / parentPanel.width,
                    element.height / parentPanel.height,
                  ) * 100) })}>
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
                      {t('inspector.centerCrop')}
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
                      {t('inspector.resetCrop')}
                    </button>
                  </div>
                </div>
              )}
              <Field label={t('inspector.fit')}><select className={input} value={element.objectFit} onChange={event => patch({ objectFit: event.target.value as ComicImageElement['objectFit'] })}><option value="cover">{t('inspector.fillPanel')}</option><option value="contain">{t('inspector.showEntire')}</option></select></Field>
              <Field label={t('inspector.filter')}><select className={input} value={element.filter} onChange={event => patch({ filter: event.target.value as ComicImageElement['filter'] })}><option value="none">{t('inspector.filterNone')}</option><option value="bw">{t('inspector.bw')}</option><option value="sepia">{t('inspector.sepia')}</option><option value="contrast">{t('inspector.contrast')}</option><option value="posterize">{t('inspector.posterize')}</option><option value="halftone">{t('inspector.halftone')}</option></select></Field>
              <Field label={t('inspector.opacity')}><input className={input} type="range" min={0} max={1} step={.05} value={element.opacity ?? 1} onChange={event => patch({ opacity: Number(event.target.value) })} /></Field>
              <div className="grid grid-cols-2 gap-1">
                <button className={`${button} ${element.flipH ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => patch({ flipH: !element.flipH })}>{t('inspector.flipH')}</button>
                <button className={`${button} ${element.flipV ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => patch({ flipV: !element.flipV })}>{t('inspector.flipV')}</button>
              </div>
              {element.parentId && (
                <button className={`${button} w-full`} onClick={detachFromPanel}>{t('inspector.removeFromPanel')}</button>
              )}
            </div>
          )}
          {element.type === 'text' && (
            <div className="space-y-2">
              <Field label={t('inspector.text')}><textarea className={input} rows={4} value={element.content} onChange={event => patch({ content: event.target.value })} /></Field>
              <Field label={t('inspector.bubble')}><select className={input} value={element.bubble} onChange={event => {
                const bubble = event.target.value as ComicTextElement['bubble']
                patch({
                  bubble,
                  letteringType: bubble === 'caption'
                    ? 'caption'
                    : bubble === 'none'
                      ? 'sound-effect'
                      : element.letteringType === 'sound-effect'
                        ? 'sound-effect'
                        : 'dialogue',
                })
              }}><option value="none">{t('inspector.bubbleNone')}</option><option value="speech">{t('inspector.speech')}</option><option value="ellipse">{t('inspector.ellipse')}</option><option value="rect">{t('inspector.rect')}</option><option value="thought">{t('inspector.thought')}</option><option value="whisper">{t('inspector.whisper')}</option><option value="caption">{t('inspector.caption')}</option><option value="scream">{t('inspector.scream')}</option><option value="electric">{t('inspector.electric')}</option><option value="burst">{t('inspector.burst')}</option><option value="cloud">{t('inspector.cloud')}</option></select></Field>
              <Field label={t('inspector.fontSize')}><input className={input} type="number" value={element.fontSize} onChange={event => patch({ fontSize: Number(event.target.value) })} /></Field>
              <Field label={t('inspector.font')}><select className={input} value={element.fontFamily} onChange={event => patch({ fontFamily: event.target.value })}><option value='"Comic Sans MS", "Trebuchet MS", sans-serif'>{t('inspector.fontComic')}</option><option value='"Arial Black", Impact, sans-serif'>{t('inspector.fontImpact')}</option><option value='Georgia, serif'>{t('inspector.fontSerif')}</option><option value='"Courier New", monospace'>{t('inspector.fontTypewriter')}</option><option value='Arial, sans-serif'>{t('inspector.fontSans')}</option></select></Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label={t('inspector.lineHeight')}><input className={input} type="number" min={0.7} max={2} step={.05} value={element.lineHeight ?? 1.08} onChange={event => patch({ lineHeight: Number(event.target.value) })} /></Field>
                <Field label={t('inspector.spacing')}><input className={input} type="number" min={-8} max={30} value={element.letterSpacing ?? 0} onChange={event => patch({ letterSpacing: Number(event.target.value) })} /></Field>
                <Field label={t('inspector.textColor')}><input className="w-full h-8" type="color" value={element.color} onChange={event => patch({ color: event.target.value })} /></Field>
                <Field label={t('inspector.outline')}><input className={input} type="number" min={0} max={8} value={element.textStrokeWidth ?? 0} onChange={event => patch({ textStrokeWidth: Number(event.target.value) })} /></Field>
              </div>
              <Field label={t('inspector.textEffect')}><select className={input} value={element.textEffect ?? 'none'} onChange={event => patch({ textEffect: event.target.value as ComicTextElement['textEffect'] })}><option value="none">{t('inspector.effectNone')}</option><option value="shadow">{t('inspector.shadow')}</option><option value="extrude">{t('inspector.extrude')}</option><option value="glow">{t('inspector.glow')}</option></select></Field>
              <Field label={t('inspector.fill')}><select className={input} value={element.textFill ?? 'solid'} onChange={event => patch({ textFill: event.target.value as ComicTextElement['textFill'] })}><option value="solid">{t('inspector.solid')}</option><option value="gradient">{t('inspector.gradient')}</option></select></Field>
              <div className="grid grid-cols-2 gap-1">
                <button className={`${button} ${element.bold ? 'border-accent-blue' : ''}`} onClick={() => patch({ bold: !element.bold })}>{t('inspector.bold')}</button>
                <button className={`${button} ${element.italic ? 'border-accent-blue' : ''}`} onClick={() => patch({ italic: !element.italic })}>{t('inspector.italic')}</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

const initialDirector = (): ComicDirectorRequest => ({
  useGlobalProfile: true,
  premise: '',
  productionMode: 'comic',
  storyboardAspect: 'landscape',
  storyboardQuality: 'draft',
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
  writingProvider: writingProviderFromText(useStore.getState().productionProfile.text.provider),
  writingModel: useStore.getState().productionProfile.text.model,
  writingBaseUrl: writingBaseUrlFromProfile(useStore.getState().productionProfile),
  provider: useStore.getState().productionProfile.image.provider === 'minimax' ? 'minimax' : 'maestro',
  imageModel: useStore.getState().productionProfile.image.model || useStore.getState().selectedModelPerMode.image || 'flux2_klein_9b',
  characters: [],
})

function stagedStoryDirectorRequest(projectId?: string): ComicDirectorRequest | null {
  try {
    const handoff = JSON.parse(window.localStorage.getItem(COMIC_HANDOFF_STORAGE_KEY) || 'null')
    if (
      handoff && typeof handoff === 'object'
      && (!projectId || handoff.projectId === projectId)
      && handoff.request && typeof handoff.request === 'object'
    ) return { ...initialDirector(), ...handoff.request }
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
  optionKey,
}: {
  value: string
  options: string[]
  onChange: (value: string) => void
  customPlaceholder: string
  optionKey: 'genre' | 'tone'
}) {
  const { t } = useUiTranslation('comics')
  const custom = !options.includes(value)
  return (
    <div className="space-y-1.5">
      <select
        className={input}
        value={custom ? '__other__' : value}
        onChange={event => onChange(event.target.value === '__other__' ? '' : event.target.value)}
      >
        {options.map(option => <option key={option} value={option}>{t(comicsKey(`${optionKey}.${option}`))}</option>)}
        <option value="__other__">{t('planning.other')}</option>
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
  const { t } = useUiTranslation('comics')
  const project = useComicStore(state => state.project)
  const [request, setRequest] = useState<ComicDirectorRequest>(() =>
    project.director?.input
      ?? stagedStoryDirectorRequest(project.id)
      ?? { ...initialDirector(), characters: project.characters })
  const [busy, setBusy] = useState<'plan' | 'images' | 'text' | 'translation' | null>(null)
  const [progress, setProgress] = useState('')
  const [textInstruction, setTextInstruction] = useState('')
  const [targetLanguage, setTargetLanguage] = useState('')
  const [activity, setActivity] = useState<DirectorActivity>({
    state: 'idle',
    message: t('planning.ready'),
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
  const productionProfile = useStore(state => state.productionProfile)
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
    local: t('planning.providerLocal'),
    remote: t('planning.providerRemote'),
    openai: t('planning.providerOpenai'),
    anthropic: t('planning.providerAnthropic'),
  }
  const planningLlmModel = servicesConfig?.llm_model_id || llmStatus?.model_id || t('planning.loadingConfig')
  const planningLlmIsActive = Boolean(
    llmStatus?.loaded
    && llmStatus.model_id === planningLlmModel
    && (!llmStatus.provider || llmStatus.provider === planningLlmProvider),
  )
  const externalWritingLlm = Boolean(request.writingProvider && request.writingProvider !== 'maestro')
  useEffect(() => {
    if (!request.useGlobalProfile) return
    const next: ComicDirectorRequest = {
      ...request,
      writingProvider: writingProviderFromText(productionProfile.text.provider),
      writingModel: productionProfile.text.model,
      writingBaseUrl: writingBaseUrlFromProfile(productionProfile),
      provider: productionProfile.image.provider === 'minimax' ? 'minimax' : 'maestro',
      imageModel: productionProfile.image.model,
    }
    if (
      next.writingProvider === request.writingProvider
      && next.writingModel === request.writingModel
      && next.writingBaseUrl === request.writingBaseUrl
      && next.provider === request.provider
      && next.imageModel === request.imageModel
    ) return
    setRequest(next)
    const state = useComicStore.getState()
    if (state.project.director) {
      state.patchProject({
        director: {
          ...state.project.director,
          provider: next.provider,
          imageModel: next.imageModel,
          input: next,
          panelJobs: {},
        },
      })
    }
  }, [productionProfile, request])
  useEffect(() => {
    const changedProject = previousProjectId.current !== project.id
    previousProjectId.current = project.id
    if (changedProject) {
      setPendingPlan(null)
      setRecoveryJobId('')
    }
    const staged = stagedStoryDirectorRequest(project.id)
    if (project.director?.input) {
      setRequest(project.director.input)
    } else if (staged) {
      setRequest(staged)
    } else if (changedProject) {
      setRequest({ ...initialDirector(), characters: project.characters })
    }
    // A project switch resets the form. Director edits inside the same project
    // are already applied through patch() and must not reset in-progress input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])
  useEffect(() => {
    const receiveStagedStory = (event: Event) => {
      const detail = (event as CustomEvent<ComicDirectorRequest>).detail
      const staged = detail && typeof detail === 'object'
        ? { ...initialDirector(), ...detail }
        : stagedStoryDirectorRequest()
      if (!staged) return
      setRequest(staged)
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
    report(t('planning.encodingRepaired'), { state: 'complete' })
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
    const director = useComicStore.getState().project.director
    if (!director) return false
    if (!director.scriptApprovedAt && !window.confirm(
      t('generate.unapproved'),
    )) return false
    setBusy('images')
    try {
      const result = await generateDirectorArtwork({
        force,
        onProgress: (message, current, total) => {
          report(message, { current, total })
          setProgress(t('generate.progress', { current, total }))
        },
      })
      if (!result.total) {
        report(t('generate.allHaveArt'), { state: 'complete' })
        return true
      }
      report(t('generate.complete', { count: result.generated }), {
        state: 'complete',
        current: result.generated,
        total: result.total,
      })
      notify({ kind: 'ok', text: t('generate.allPlaced') })
      useStore.getState().loadOutputs()
      return true
    } catch (error) {
      const message = t('generate.resumeError', { message: (error as Error).message })
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
    notify({ kind: 'ok', text: t('lettering.simplified') })
    report(t('lettering.repaired'), {
      state: 'complete',
    })
  }

  const transformTextPlan = async (
    mode: 'rewrite' | 'translate',
    languageOverride?: string,
  ): Promise<ComicPlan> => {
    const current = useComicStore.getState().project
    const captured = planWithCanvasText(current)
    if (!captured) throw new Error(t('generate.noPlan'))
    const working = structuredClone(captured)
    const translationLanguage = (languageOverride ?? targetLanguage).trim()
    const operationWriting = writingForOperation(current.director!.input, mode)
    for (let pageIndex = 0; pageIndex < working.pages.length; pageIndex += 1) {
      report(t(mode === 'translate' ? 'lettering.translatingPage' : 'lettering.rewritingPage', { current: pageIndex + 1, total: working.pages.length }), {
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
      const languageProject = translated
        ? withComicContentLanguage(state.project, translationLanguage)
        : state.project
      const next = simplifyDirectorText({
        ...languageProject,
        director: { ...state.project.director!, plan },
      })
      state.patchProject(next)
      report(translated ? t('lettering.appliedTranslation', { language: translationLanguage }) : t('lettering.appliedRewrite'), {
        state: 'complete',
      })
      notify({ kind: 'ok', text: translated
        ? t('lettering.translated', { language: translationLanguage })
        : t('lettering.rewritten') })
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
        ...withComicContentLanguage(state.project, targetLanguage.trim()),
        title: `${state.project.title} — ${targetLanguage.trim()}`,
        director: { ...state.project.director!, plan },
      })
      state.patchProject(translatedProject)
      temporaryApplied = true
      await wait(100)
      await exportComicPdf((current, total) =>
        report(t('export.exportingPage', { current, total }), { current, total }))
      report(t('export.pdfRestored', { language: targetLanguage.trim() }), {
        state: 'complete',
      })
      notify({ kind: 'ok', text: t('export.translatedPdf', { language: targetLanguage.trim() }) })
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
    notify({ kind: 'ok', text: t('generate.layoutsVaried') })
  }

  const regenerateAllArtwork = async () => {
    if (!window.confirm(
      t('generate.regenerateConfirm', { count: totalPlannedPanels }),
    )) return
    await generateAll(true)
  }

  const confirmNewComic = (withImages: boolean) => {
    const storyboard = request.productionMode === 'storyboard'
    const estimatedPanels = Math.max(
      1,
      request.pageCount * (storyboard ? 1 : request.panelsPerPage),
    )
    const artworkNotice = withImages
      ? t('dialogs.artworkAfter', {
        count: estimatedPanels,
        kind: storyboard ? t('dialogs.shotImages') : t('dialogs.panelImages'),
      })
      : ''
    return window.confirm(
      t(storyboard ? 'dialogs.newStoryboard' : 'dialogs.newComic', { artwork: artworkNotice }),
    )
  }

  const placePlan = async (
    rawPlan: ComicPlan,
    withImages: boolean,
    placementRequest: ComicDirectorRequest = request,
  ) => {
      const plan = normalizeComicPlan(rawPlan, placementRequest.dialogueDensity)
      // A freshly generated storyboard may contain duration, camera and motion
      // hints, but none of them are manual locks until the user edits a source
      // beat. Unknown fields invented by an LLM must not defeat film adaptation.
      plan.pages.forEach(page => page.panels.forEach(panel => {
        panel.videoOverrideFields = []
      }))
      setPendingPlan(plan)
      const plannedImageCount = plan.pages.reduce(
        (total, page) => total + page.panels.length,
        0,
      )
      report(placementRequest.productionMode === 'storyboard'
        ? t('planning.planShots', { count: plannedImageCount })
        : t('planning.planPages', { pages: plan.pages.length, panels: plannedImageCount }))
      const currentProject = useComicStore.getState().project
      const freshProject = createComicProject()
      if (currentProject.provenance) {
        // A re-plan is still the same cross-domain destination. Reuse its
        // immutable Comic ID instead of creating a second destination whose
        // lineage would need title-based reconciliation.
        freshProject.id = currentProject.id
        freshProject.createdAt = currentProject.createdAt
      }
      const preservedReferenceIds = new Set(
        [...placementRequest.characters, ...plan.characters].flatMap(character => [
          character.referenceAssetId,
          ...(character.referenceAssetIds || []),
        ]).concat(placementRequest.worldReferenceAssetIds || [])
          .filter((assetId): assetId is string => Boolean(assetId)),
      )
      freshProject.assets = Object.fromEntries(
        [...preservedReferenceIds]
          .map(assetId => currentProject.assets[assetId])
          .filter((asset): asset is ComicAsset => Boolean(asset))
          .map(asset => [asset.id, asset]),
      )
      // Planning replaces the editable pages, not the source identity. Keep
      // the exact Series → Comics lineage attached to the new plan so a
      // generated/reloaded project cannot silently become standalone.
      if (currentProject.provenance) {
        freshProject.provenance = structuredClone(currentProject.provenance)
      }
      freshProject.style = structuredClone(currentProject.style)
      const storyboard = placementRequest.productionMode === 'storyboard'
      freshProject.pageNumbering = storyboard
        ? { style: 'none' }
        : structuredClone(currentProject.pageNumbering)
      if (storyboard) {
        const finalQuality = placementRequest.storyboardQuality === 'final'
        const portrait = placementRequest.storyboardAspect === 'portrait'
        freshProject.format = {
          preset: 'custom',
          width: portrait ? (finalQuality ? 704 : 448) : (finalQuality ? 1280 : 832),
          height: portrait ? (finalQuality ? 1280 : 832) : (finalQuality ? 704 : 448),
          dpi: 96,
        }
      } else {
        freshProject.format = {
          ...freshProject.format,
          preset: placementRequest.format,
          ...(placementRequest.format !== 'custom' ? COMIC_FORMATS[placementRequest.format] : {
            width: currentProject.format.width,
            height: currentProject.format.height,
            dpi: currentProject.format.dpi,
          }),
        }
      }
      const next = projectFromPlan(
        plan,
        freshProject,
        placementRequest.productionMode || 'comic',
      )
      next.director = {
        planId: plan.id,
        provider: placementRequest.provider,
        imageModel: placementRequest.imageModel,
        input: placementRequest,
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
        window.localStorage.removeItem('maestro-story-comic-draft')
        window.localStorage.removeItem('maestro-story-comic-auto-start')
      } catch {
        // Private browsing may block storage; the in-memory state is enough.
      }
      report(storyboard
        ? t('planning.placedStoryboard')
        : t('planning.placedComic'))
      notify({ kind: 'ok', text: storyboard
        ? t('planning.createdShots', { count: plan.pages.length })
        : t('planning.createdPages', { count: plan.pages.length }) })
      if (withImages) {
        report(t('planning.openingCanvas'))
        await new Promise(resolve => window.setTimeout(resolve, 0))
        await generateAll()
      } else {
        report(t('planning.planReady'), { state: 'complete' })
      }
  }

  const makePlan = async (withImages = false, skipConfirmation = false) => {
    if (!request.premise.trim()) return
    if (!skipConfirmation && !confirmNewComic(withImages)) return
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
      message: t('planning.submitting'),
      steps: [t('planning.submitting')],
    })
    try {
      const { plan } = await api.planComic({
        ...request,
        workspace: useStore.getState().activeWorkspace,
      }, status => {
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

  useEffect(() => {
    if (busy !== null || !request.sourceStory?.id) return
    let staged: { id?: string; revision?: number } | null = null
    try {
      staged = JSON.parse(
        window.localStorage.getItem('maestro-story-comic-auto-start') || 'null',
      )
    } catch {
      window.localStorage.removeItem('maestro-story-comic-auto-start')
      return
    }
    if (
      staged?.id !== request.sourceStory.id
      || staged.revision !== request.sourceStory.revision
    ) return

    // Remove the hand-off before starting so React StrictMode, a remount or a
    // failed request cannot submit the same paid generation twice.
    window.localStorage.removeItem('maestro-story-comic-auto-start')
    window.setTimeout(() => {
      void makePlan(true, true)
    }, 0)
    // makePlan intentionally reads the current staged request. Re-running this
    // effect for every activity/render update could submit duplicate jobs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request.sourceStory?.id, request.sourceStory?.revision])

  const recoverPlan = async () => {
    if (!confirmNewComic(createCompleteComic)) return
    setBusy('plan')
    setStartedAt(Date.now())
    try {
      const jobId = recoveryJobId.trim()
      let plan: ComicPlan | null = null
      let placementRequest: ComicDirectorRequest | undefined
      // An explicitly entered durable job is authoritative. A stale browser
      // result from an older session must never shadow the ID visible here.
      if (jobId) {
        report(t('planning.checkingJob', { jobId }))
        const job = await api.fetchComicPlanJob(jobId)
        placementRequest = job.request
        if (job.status === 'completed' && job.result?.plan) {
          report(t('planning.recoveredJob', { jobId }))
          plan = job.result.plan
        } else {
          report(t('planning.resumingJob', { jobId }))
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
      if (!plan) throw new Error(t('planning.needJob'))
      await placePlan(plan, createCompleteComic, placementRequest)
    } catch (error) {
      const message = (error as Error).message
      report(message, { state: 'error' })
      notify({ kind: 'error', text: message })
    } finally {
      setBusy(null)
    }
  }

  const updatePlanPanel = (
    pageIndex: number,
    panelIndex: number,
    patchValue: Partial<ComicPlanPanel>,
    overrideFields: readonly ComicVideoOverrideField[] = [],
  ) => {
    const state = useComicStore.getState()
    const director = state.project.director
    if (!director) return
    const pages = director.plan.pages.map((page, pi) => pi !== pageIndex ? page : {
      ...page,
      panels: page.panels.map((panel, pj) => {
        if (pj !== panelIndex) return panel
        const updated = { ...panel, ...patchValue }
        if (overrideFields.length) {
          updated.videoOverrideFields = mergeComicVideoOverrideFields(
            panel.videoOverrideFields,
            overrideFields,
          )
        }
        return updated
      }),
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
      t('generate.unapprovedPanel'),
    )) return
    setSingleBusy(planned.id)
    try {
      const identityReference = panelIdentityReference(director, planned, state.project.assets)
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
      const reference = identityReference.source || (localSupportsReferences && worldReferenceId
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
          aspectRatio: miniMaxAspectRatio(panel.width, panel.height),
        },
      )
      if (identityReference.characterId) {
        asset.characterIds = [identityReference.characterId]
      }
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
      notify({ kind: 'ok', text: t('generate.panelDone', { page: pageIndex + 1, panel: panelIndex + 1 }) })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setSingleBusy(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-accent-blue/30 bg-accent-blue/5 p-3">
        <div className="flex items-center gap-2 text-xs font-medium text-text-primary"><WandSparkles size={14} /> {request.productionMode === 'storyboard' ? t('planning.storyboardTitle') : t('planning.title')}</div>
        <p className="text-[10px] text-text-muted mt-1">
          {request.productionMode === 'storyboard'
            ? t('planning.storyboardHint')
            : t('planning.comicHint')}
        </p>
      </div>
      <div className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-bg-tertiary/30 p-1">
        <button
          className={`${button} ${request.productionMode !== 'storyboard' ? 'border-accent-blue text-accent-blue' : ''}`}
          disabled={busy !== null}
          onClick={() => patch('productionMode', 'comic')}
        >
          {t('planning.comic')}
        </button>
        <button
          className={`${button} ${request.productionMode === 'storyboard' ? 'border-purple-400 text-purple-300' : ''}`}
          disabled={busy !== null}
          onClick={() => {
            patch('productionMode', 'storyboard')
            patch('panelsPerPage', 1)
          }}
        >
          {t('planning.storyboard')}
        </button>
      </div>
      {request.productionMode === 'storyboard' && (
        <div className="rounded-lg border border-purple-400/30 bg-purple-400/5 p-2.5 text-[10px] text-text-muted">
          {t('planning.storyboardNote')}
        </div>
      )}
      <div className="rounded-lg border border-border bg-bg-tertiary/30 p-2.5">
        <div className="text-[9px] uppercase tracking-wide text-text-muted">{t('planning.llm')}</div>
        <div className="mt-1 text-[11px] text-text-primary">
          {externalWritingLlm
            ? t('planning.overrideProvider', {
              provider: request.writingProvider === 'deepseek' ? t('planning.providerDeepseek') : request.writingProvider === 'minimax' ? t('planning.providerMinimax') : request.writingProvider === 'openai' ? t('planning.providerOpenaiHosted') : t('planning.providerCompatible'),
              model: request.writingModel || t('planning.chooseModel'),
            })
            : t('planning.defaultProvider', { provider: planningLlmProviderLabel[planningLlmProvider] || planningLlmProvider, model: planningLlmModel })}
        </div>
        <div className="mt-0.5 text-[9px] text-text-muted">
          {externalWritingLlm
            ? t('planning.externalHint', {
              endpoint: request.writingProvider === 'deepseek' ? 'https://api.deepseek.com' : request.writingProvider === 'minimax' ? 'https://api.minimax.io/v1' : request.writingProvider === 'openai' ? 'https://api.openai.com' : request.writingBaseUrl || t('planning.configureCustom'),
            })
            : planningLlmIsActive
              ? t('planning.activeNow')
              : llmStatus?.loaded
                ? t('planning.willSwitch', { model: llmStatus.model_id || t('planning.currentModel') })
                : t('planning.autoLoads')}
        </div>
      </div>
      <ComicWritingProviderFields value={request} onChange={patch} disabled={busy !== null} />
      <Field label={t('planning.premise')}><textarea className={input} rows={5} value={request.premise} onChange={event => patch('premise', event.target.value)} placeholder={t('planning.premisePlaceholder')} /></Field>
      {request.sourceStory && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-2.5 text-[10px] text-emerald-200">
          {t('planning.fromStory', { title: request.sourceStory.title, revision: request.sourceStory.revision })}
        </div>
      )}
      {request.sourceSeries && request.sourceEpisode && (
        <div className="rounded-lg border border-violet-500/30 bg-violet-500/5 p-2.5 text-[10px] text-violet-200">
          {t('planning.fromSeries', {
            series: request.sourceSeries.title,
            episode: request.sourceEpisode.title,
            seriesId: request.sourceSeries.id,
            episodeId: request.sourceEpisode.id,
          })}
        </div>
      )}
      <Field label={t('planning.brief')}>
        <textarea
          className={input}
          rows={8}
          value={request.storyContext || ''}
          onChange={event => patch('storyContext', event.target.value)}
          placeholder={t('planning.briefPlaceholder')}
        />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label={request.productionMode === 'storyboard' ? t('planning.shots') : t('planning.pages')}><input className={input} type="number" min={1} max={100} value={request.pageCount} onChange={event => patch('pageCount', Math.max(1, Number(event.target.value)))} /></Field>
        {request.productionMode === 'storyboard' ? (
          <Field label={t('planning.screen')}>
            <select
              className={input}
              value={request.storyboardAspect || 'landscape'}
              onChange={event => patch('storyboardAspect', event.target.value as ComicDirectorRequest['storyboardAspect'])}
            >
              <option value="landscape">{t('planning.landscape')}</option>
              <option value="portrait">{t('planning.portrait')}</option>
            </select>
          </Field>
        ) : (
          <Field label={t('planning.panelsPerPage')}><input className={input} type="number" min={1} max={12} value={request.panelsPerPage} onChange={event => patch('panelsPerPage', Math.max(1, Number(event.target.value)))} /></Field>
        )}
        <Field label={t('planning.language')}>
          <EditableLanguageInput className={input} value={request.language} onChange={value => patch('language', value)} />
        </Field>
        {request.productionMode === 'storyboard' ? (
          <Field label={t('planning.frameQuality')}>
            <select
              className={input}
              value={request.storyboardQuality || 'draft'}
              onChange={event => patch('storyboardQuality', event.target.value as ComicDirectorRequest['storyboardQuality'])}
            >
              <option value="draft">{t('planning.draftQuality')}</option>
              <option value="final">{t('planning.finalQuality')}</option>
            </select>
          </Field>
        ) : (
          <Field label={t('planning.format')}><select className={input} value={request.format} onChange={event => patch('format', event.target.value as ComicDirectorRequest['format'])}>{Object.entries(COMIC_FORMATS).map(([id]) => <option key={id} value={id}>{t(comicsKey(`format.${id}`))}</option>)}</select></Field>
        )}
        <Field label={t('planning.genre')}>
          <SuggestedChoice
            value={request.genre}
            options={COMIC_GENRES}
            onChange={value => patch('genre', value)}
            customPlaceholder={t('planning.customGenre')}
            optionKey="genre"
          />
        </Field>
        <Field label={t('planning.tone')}>
          <SuggestedChoice
            value={request.tone}
            options={COMIC_TONES}
            onChange={value => patch('tone', value)}
            customPlaceholder={t('planning.customTone')}
            optionKey="tone"
          />
        </Field>
        {request.productionMode !== 'storyboard' && <Field label={t('planning.density')}>
          <select
            className={input}
            value={request.dialogueDensity}
            onChange={event => patch('dialogueDensity', event.target.value as ComicDirectorRequest['dialogueDensity'])}
          >
            <option value="low">{t('planning.densityLow')}</option>
            <option value="medium">{t('planning.densityMedium')}</option>
            <option value="high">{t('planning.densityHigh')}</option>
          </select>
        </Field>}
      </div>
      <Field label={t('planning.artStyle')}><input
        className={input}
        value={request.artStyle}
        onChange={event => patch('artStyle', event.target.value)}
        placeholder={t('planning.artStylePlaceholder')}
      /></Field>
      <Field label={t('planning.world')}>
        <textarea
          className={input}
          rows={3}
          value={request.worldContext || ''}
          onChange={event => patch('worldContext', event.target.value)}
          placeholder={t('planning.worldPlaceholder')}
        />
      </Field>
      <Field label={t('planning.forbidden')}>
        <textarea
          className={input}
          rows={2}
          value={request.forbiddenElements || ''}
          onChange={event => patch('forbiddenElements', event.target.value)}
          placeholder={t('planning.forbiddenPlaceholder')}
        />
      </Field>
      <p className="text-[9px] text-text-muted">
        {t('planning.blankHint')}
      </p>
      <Field label={t('planning.imageGenerator')}><select
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
        <optgroup label={t('planning.externalGroup')}>
          <option value="minimax:image-01">{t('planning.minimaxImage')}</option>
        </optgroup>
        <optgroup label={t('planning.installedGroup')}>
          {request.provider === 'maestro' && request.imageModel
            && !installedMaestroImageModels.some(model => model.model_type === request.imageModel) && (
            <option value={`maestro:${request.imageModel}`}>
              {t('planning.incompatible', { model: request.imageModel })}
            </option>
          )}
          {installedMaestroImageModels.map(model => (
            <option key={model.model_type} value={`maestro:${model.model_type}`}>
              {t('planning.localModel', { name: model.name })}
            </option>
          ))}
        </optgroup>
        {maestroImageModels.some(model => model.is_downloaded === false) && (
          <optgroup label={t('planning.notDownloaded')}>
            {maestroImageModels.filter(model => model.is_downloaded === false).map(model => (
              <option disabled key={model.model_type} value={`maestro:${model.model_type}`}>
                {model.name}
              </option>
            ))}
          </optgroup>
        )}
      </select>
      <p className="mt-1 text-[9px] text-text-muted">
        {t('planning.queueHint')}
      </p>
      </Field>
      {request.provider === 'minimax' && (
        <p className="text-[9px] text-text-muted">
          {t('planning.minimaxRefHint')}
        </p>
      )}
      {project.director && (
        <p className="rounded border border-border bg-bg-tertiary/40 px-2 py-1.5 text-[9px] text-text-muted">
          {t('planning.currentPlan', {
            engine: project.director.provider === 'minimax'
              ? t('planning.minimaxEngine')
              : t('planning.hocusEngine', { model: project.director.imageModel || t('planning.noImageModel') }),
          })}
        </p>
      )}
      <div className="border-t border-border pt-3 space-y-2">
        <strong className="text-[10px] uppercase tracking-wide text-text-muted">{t('characters.heading')}</strong>
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
              <option value="">{t('characters.noIdentity')}</option>
              {Object.values(project.assets).map(asset => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
            </select>
            <p className="mt-1 text-[9px] text-text-muted">
              {t('characters.minimaxHint')}
            </p>
          </div>
        ))}
        <input className={input} value={newCharacter.name} onChange={event => setNewCharacter(value => ({ ...value, name: event.target.value }))} placeholder={t('characters.name')} />
        <textarea className={input} value={newCharacter.description} onChange={event => setNewCharacter(value => ({ ...value, description: event.target.value }))} placeholder={t('characters.visual')} />
        <button className={`${button} w-full`} onClick={addCharacter}><Plus size={12} /> {t('characters.add')}</button>
      </div>
      <button
        className={`${button} w-full border-accent-blue text-accent-blue`}
        disabled={busy !== null || !request.premise.trim()}
        onClick={() => makePlan(createCompleteComic)}
      >
        {busy !== null ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
        {createCompleteComic ? t('planning.createComplete') : t('planning.createPlan')}
      </button>
      {createCompleteComic && (
        <button className={`${button} w-full`} disabled={busy !== null || !request.premise.trim()} onClick={() => makePlan(false)}>
          {t('planning.createPlanOnly')}
        </button>
      )}
      <details open={activity.state === 'error'} className="rounded-lg border border-border bg-bg-tertiary/30 p-2">
        <summary className="cursor-pointer text-[10px] font-medium text-text-secondary">
          {t('planning.resumeTitle')}
        </summary>
        <p className="mt-2 text-[9px] text-text-muted">
          {t('planning.resumeHint')}
        </p>
        <input
          className={`${input} mt-2`}
          value={recoveryJobId}
          onChange={event => setRecoveryJobId(event.target.value)}
          placeholder={t('planning.jobPlaceholder')}
        />
        <button
          className={`${button} mt-2 w-full border-amber-500/50 text-amber-300`}
          disabled={busy !== null || (!pendingPlan && !recoveryJobId.trim())}
          onClick={recoverPlan}
        >
          {busy === 'plan' ? <Loader2 size={12} className="animate-spin" /> : <Redo2 size={12} />}
          {t('planning.resumeAction')}
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
            ? t('generate.allQueued', { count: remainingPanels })
            : t('generate.allDone', { count: totalPlannedPanels }))}
        </button>
      )}
      {project.director && (
        <div className="border-t border-border pt-3 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <button className={`${button} border-amber-500/50 text-amber-300`} disabled={busy !== null} onClick={cleanUpCurrentComicText}>
              <Type size={12} /> {t('lettering.repair')}
            </button>
            <button className={`${button} border-accent-blue/50 text-accent-blue`} disabled={busy !== null} onClick={regenerateAllArtwork}>
              <ImagePlus size={12} /> {t('generate.regenerateAll')}
            </button>
            <button className={`${button} col-span-2`} disabled={busy !== null} onClick={varyCurrentLayouts}>
              <PanelTop size={12} /> {t('generate.varyLayouts')}
            </button>
          </div>
          <p className="text-[9px] text-text-muted">
            {t('lettering.keepImages')}
          </p>
          <div className="rounded-lg border border-border bg-bg-tertiary/30 p-2.5 space-y-2">
            <strong className="text-[10px] uppercase tracking-wide text-text-muted">{t('lettering.title')}</strong>
            <p className="text-[9px] text-text-muted">
              {t('lettering.hint')}
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
              {t('lettering.fixMixed', { language: project.language || project.director?.plan.language || project.director?.input.language })}
            </button>
            <textarea
              className={input}
              rows={2}
              value={textInstruction}
              onChange={event => setTextInstruction(event.target.value)}
              placeholder={t('lettering.rewritePlaceholder')}
            />
            <button
              className={`${button} w-full`}
              disabled={busy !== null}
              onClick={() => applyTextOperation('rewrite')}
            >
              {busy === 'text' ? <Loader2 size={12} className="animate-spin" /> : <Type size={12} />}
              {t('lettering.rewrite')}
            </button>
            <input
              className={input}
              list="comic-export-languages"
              value={targetLanguage}
              onChange={event => setTargetLanguage(event.target.value)}
              placeholder={t('lettering.targetLanguage')}
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
                {t('lettering.translateEditor')}
              </button>
              <button
                className={`${button} border-emerald-500/50 text-emerald-400`}
                disabled={busy !== null || !targetLanguage.trim()}
                onClick={exportTranslatedPdf}
              >
                {busy === 'translation' ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                {t('lettering.exportPdf')}
              </button>
            </div>
          </div>
          <div>
            <strong className="text-[10px] uppercase tracking-wide text-text-muted">{t('planning.reviewPlan')}</strong>
            <p className="text-[9px] text-text-muted mt-1">{t('planning.reviewHint')}</p>
          </div>
          {project.director.plan.storyStructure?.length ? (
            <details className="rounded-lg border border-border bg-bg-tertiary/30 p-2" open>
              <summary className="cursor-pointer text-[10px] font-medium text-text-secondary">
                {t('planning.structure', { count: project.director.plan.storyStructure.length })}
              </summary>
              <ol className="mt-2 space-y-2">
                {project.director.plan.storyStructure.map(beat => (
                  <li key={beat.pageNumber} className="text-[9px] leading-relaxed text-text-muted">
                    <strong className="text-text-secondary">
                      {beat.pageNumber}. {beat.stage}
                    </strong>
                    <span className="block">{beat.goal}</span>
                    <span className="block text-amber-300/80">{t('planning.turn', { text: beat.turningPoint })}</span>
                  </li>
                ))}
              </ol>
            </details>
          ) : null}
          <details className="rounded-lg border border-border bg-bg-tertiary/30 p-2">
            <summary className="cursor-pointer text-[10px] font-medium text-text-secondary">
              {(project.director.plan.styleBible || '').trim()
                ? t('planning.bibleCreated')
                : t('planning.bibleEmpty')}
            </summary>
            {(project.director.plan.styleBible || '').trim() ? (
              <p className="mt-2 whitespace-pre-wrap text-[9px] leading-relaxed text-text-muted">
                {project.director.plan.styleBible}
              </p>
            ) : (
              <p className="mt-2 text-[9px] text-text-muted">
                {t('planning.bibleUnused')}
              </p>
            )}
          </details>
          {hasBrokenEncoding && (
            <button className={`${button} w-full border-amber-500/50 text-amber-300`} onClick={repairCurrentPlanEncoding}>
              {t('planning.repairEncoding')}
            </button>
          )}
          {project.director.plan.pages.map((page, pageIndex) => (
            <details key={page.pageNumber} open={pageIndex === 0} className="rounded-lg border border-border bg-bg-tertiary/30">
              <summary className="cursor-pointer px-2 py-2 text-xs font-medium text-text-primary">{t('script.pagePanels', { n: page.pageNumber, count: page.panels.length })}</summary>
              <div className="p-2 pt-0 space-y-2">
                {page.panels.map((panel, panelIndex) => (
                  <div key={panel.id} className="rounded border border-border bg-bg-secondary p-2 space-y-2">
                    <div className="flex justify-between text-[10px]">
                      <b className="text-text-primary">{t('planning.panel', { n: panelIndex + 1 })}</b>
                      <span className="text-text-muted">{panel.framing}</span>
                    </div>
                    <Field label={t('planning.imagePrompt')}>
                      <textarea className={input} rows={5} value={panel.imagePrompt}
                        onChange={event => updatePlanPanel(pageIndex, panelIndex, { imagePrompt: event.target.value })} />
                    </Field>
                    {project.director?.input.productionMode === 'storyboard' ? (
                      <>
                        <Field label={t('planning.videoPrompt')}>
                          <textarea
                            className={input}
                            rows={7}
                            value={panel.videoPrompt || ''}
                            onChange={event => updatePlanPanel(pageIndex, panelIndex, {
                              videoPrompt: event.target.value,
                            }, ['video_prompt'])}
                          />
                        </Field>
                        <div className="grid grid-cols-[1fr_90px] gap-2">
                          <Field label={t('planning.camera')}>
                            <select
                              className={input}
                              value={panel.cameraMove || 'none'}
                              onChange={event => updatePlanPanel(pageIndex, panelIndex, {
                                cameraMove: event.target.value as ComicPlanPanel['cameraMove'],
                              }, ['camera'])}
                            >
                              <option value="none">{t('planning.noCamera')}</option>
                              <option value="push-in">{t('planning.pushIn')}</option>
                              <option value="pull-out">{t('planning.pullOut')}</option>
                              <option value="pan-left">{t('planning.panLeft')}</option>
                              <option value="pan-right">{t('planning.panRight')}</option>
                            </select>
                          </Field>
                          <Field label={t('planning.seconds')}>
                            <input
                              className={input}
                              type="number"
                              min={.8}
                              max={20}
                              step={.1}
                              value={panel.durationSeconds || 3}
                              onChange={event => updatePlanPanel(pageIndex, panelIndex, {
                                durationSeconds: Number(event.target.value),
                              }, ['duration'])}
                            />
                          </Field>
                        </div>
                      </>
                    ) : (
                      <Field label={t('lettering.dialogue')}>
                        <PanelScriptEditor
                          panel={panel}
                          onCommit={value => commitPanelText(pageIndex, panelIndex, value)}
                        />
                      </Field>
                    )}
                    <button className={`${button} w-full`} disabled={singleBusy !== null || busy !== null} onClick={() => generateSingle(pageIndex, panelIndex)}>
                      {singleBusy === panel.id ? <Loader2 size={12} className="animate-spin" /> : <ImagePlus size={12} />}
                      {project.director!.completedPanelIds.includes(panel.id) ? t('generate.regeneratePanel') : t('generate.panel')}
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

const HISTORY_REASON_KEYS: Record<string, ParseKeys<'comics'>> = {
  'Before history restore': 'history.reason.beforeRestore',
  'Comic opened or created': 'history.reason.opened',
  'Automatic editing checkpoint': 'history.reason.auto',
  'Manual save': 'history.reason.save',
  'Before comic import': 'history.reason.beforeImport',
  'Before opening saved comic': 'history.reason.beforeOpen',
  'Before creating a new comic': 'history.reason.beforeNew',
}

export function ComicEditorPanel() {
  const { t } = useUiTranslation('comics')
  const { t: tCommon } = useUiTranslation('common')
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
  const [preDirty, setPreDirty] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewZoom, setPreviewZoom] = useState(1)
  const [notice, setNotice] = useState<Notice>(null)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [comicHistory, setComicHistory] = useState<api.ComicHistoryEntry[]>([])
  const [generatingArtwork, setGeneratingArtwork] = useState(false)
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
  const validateLineage = async (candidate: ComicProject): Promise<void> => {
    if (!candidate.provenance) return
    const sourceWorkspace = candidate.provenance.workspaceId
    const library = await api.fetchSeriesLibrary(sourceWorkspace)
    resolveComicSource(candidate, library, sourceWorkspace)
  }
  useEffect(() => {
    if (!project.provenance) return
    let cancelled = false
    void validateLineage(project).catch(error => {
      if (!cancelled) notify({ kind: 'error', text: (error as Error).message })
    })
    return () => { cancelled = true }
    // Source IDs are the only dependencies that can change the resolution.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    project.id,
    project.provenance?.workspaceId,
    project.provenance?.source.seriesId,
    project.provenance?.source.episodeId,
  ])
  const selectSideTab = (nextTab: SideTab) => {
    if (sideTab === 'pre' && nextTab !== 'pre' && preDirty
      && !window.confirm(
        t('dialogs.leavePre'),
      )) return
    setSideTab(nextTab)
    if (nextTab === 'pre') setSidePanelCollapsed(true)
    else if (sideTab === 'pre') setSidePanelCollapsed(false)
  }
  const totalArtworkPanels = project.director?.plan.pages.reduce(
    (total, page) => total + page.panels.length,
    0,
  ) || 0
  const remainingArtworkPanels = project.director?.plan.pages.reduce(
    (total, page) => total + page.panels.filter(
      panel => !project.director?.completedPanelIds.includes(panel.id),
    ).length,
    0,
  ) || 0
  const generateComicArtwork = async () => {
    const director = useComicStore.getState().project.director
    setSideTab('director')
    setSidePanelCollapsed(false)
    if (!director) {
      notify({ kind: 'error', text: t('generate.needPlan') })
      return
    }
    if (!director.scriptApprovedAt && !window.confirm(
      t('generate.unapproved'),
    )) return
    setGeneratingArtwork(true)
    try {
      const result = await generateDirectorArtwork({
        onProgress: (message, current, total) => notify({
          kind: 'ok',
          text: t('generate.progressWrap', { message, current, total }),
        }),
      })
      notify({
        kind: 'ok',
        text: result.total
          ? t('generate.artworkComplete', { count: result.generated })
          : t('generate.alreadyHave'),
      })
      void useStore.getState().loadOutputs()
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setGeneratingArtwork(false)
    }
  }

  useEffect(() => {
    const openPre = () => {
      setSideTab('pre')
      setSidePanelCollapsed(true)
    }
    window.addEventListener('maestro:comic-pre-open', openPre)
    return () => window.removeEventListener('maestro:comic-pre-open', openPre)
  }, [])
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
    if (dirty && !confirm(t('dialogs.restoreHistory'))) return
    setHistoryLoading(true)
    try {
      await checkpointCurrent('Before history restore')
      const restored = await api.loadComicHistory(entry.id)
      const restoredProject = normalizeComicProject(restored.project)
      await validateLineage(restoredProject)
      const state = useComicStore.getState()
      state.setProject(restoredProject, null)
      useComicStore.getState().patchProject({})
      setHistoryOpen(false)
      notify({ kind: 'ok', text: t('notices.restored', { title: entry.title }) })
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
    if (nested && !confirm(t('dialogs.replaceLayout'))) return
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
        notify({ kind: 'ok', text: t('notices.saved') })
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
    if (dirty && !confirm(t('dialogs.importReplace'))) {
      if (importRef.current) importRef.current.value = ''
      return
    }
    try {
      await checkpointCurrent('Before comic import')
      const parsed = normalizeComicProject(JSON.parse(await file.text()))
      await validateLineage(parsed)
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
      notify({ kind: 'ok', text: t('notices.imported') })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      if (importRef.current) importRef.current.value = ''
    }
  }

  const openSaved = async (name: string) => {
    if (!name) return
    if (dirty && !confirm(t('dialogs.openDiscard'))) return
    try {
      await checkpointCurrent('Before opening saved comic')
      const loaded = normalizeComicProject(await api.loadComicProject(name))
      await validateLineage(loaded)
      useComicStore.getState().setProject(loaded, name)
      notify({ kind: 'ok', text: t('notices.opened') })
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    }
  }

  const runExport = async (kind: 'pdf' | 'cbz' | 'png') => {
    setExporting(kind)
    try {
      if (kind === 'pdf') await exportComicPdf((current, total) => setExporting(t('export.pdfProgress', { current, total })))
      if (kind === 'cbz') await exportComicCbz((current, total) => setExporting(t('export.cbzProgress', { current, total })))
      if (kind === 'png') await exportComicPagePng()
    } catch (error) {
      notify({ kind: 'error', text: (error as Error).message })
    } finally {
      setExporting('')
    }
  }

  const newProject = async () => {
    if (dirty && !confirm(t('dialogs.newDiscard'))) return
    await checkpointCurrent('Before creating a new comic')
    window.localStorage.removeItem('maestro-story-comic-draft')
    window.localStorage.removeItem('maestro-story-comic-auto-start')
    window.localStorage.removeItem(COMIC_HANDOFF_STORAGE_KEY)
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
            {dirty && <span className="text-[10px] text-yellow-400">{t('toolbar.unsaved')}</span>}
            <button
              className={`${button} ml-auto border-emerald-500/50 text-emerald-300`}
              disabled={generatingArtwork}
              onClick={() => void generateComicArtwork()}
              title={project.director ? t('toolbar.generateTitle') : t('toolbar.generateNeedPlan')}
            >
              {generatingArtwork ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
              {remainingArtworkPanels > 0 ? t('generate.remaining', { count: remainingArtworkPanels }) : totalArtworkPanels ? t('generate.done') : t('generate.action')}
            </button>
            <button
              className={button}
              onClick={() => setToolbarCollapsed(false)}
              title={t('toolbar.expand')}
            >
              <ChevronDown size={13} /> {t('toolbar.tools')}
            </button>
          </>
        ) : (
          <>
            <input
              value={project.title}
              onChange={event => patchProject({ title: event.target.value })}
              className="w-48 bg-transparent text-sm font-semibold text-text-primary focus:outline-none border-b border-transparent focus:border-accent-blue"
            />
            {dirty && <span className="text-[10px] text-yellow-400">{t('toolbar.unsaved')}</span>}
            <div className="h-5 border-l border-border mx-1" />
            <button className={button} onClick={() => void newProject()}><Plus size={13} /> {t('toolbar.new')}</button>
            <select className={`${input} w-36`} value="" onChange={event => applyLayout(event.target.value)} title={t('toolbar.layoutTitle')}>
              <option value="">{t('toolbar.layouts')}</option>
              {COMIC_LAYOUTS.map(layout => <option key={layout.name} value={layout.name}>{t(`layout.${layout.name}`)}</option>)}
            </select>
            <select className={`${input} w-32`} value="" onChange={event => addEffect(event.target.value)} title={t('toolbar.effectTitle')}>
              <option value="">{t('toolbar.effects')}</option>
              {COMIC_EFFECTS.map(effect => <option key={effect.name} value={effect.name}>{effect.name}</option>)}
            </select>
            <select className={`${input} w-40`} value="" onChange={event => openSaved(event.target.value)} title={t('toolbar.openTitle')}>
              <option value="">{t('toolbar.openSaved')}</option>
              {comicOutputs.map(output => <option key={output.name} value={output.name}>{output.name}</option>)}
            </select>
            <button className={button} onClick={openComicHistory} title={t('toolbar.historyTitle')}>
              <HistoryIcon size={13} /> {t('toolbar.history')}
            </button>
            <button className={button} onClick={() => importRef.current?.click()}><Upload size={13} /> {tCommon('actions.import')}</button>
            <input ref={importRef} type="file" accept=".json,.comic.json" className="hidden" onChange={event => importProject(event.target.files?.[0])} />
            <button className={button} disabled={saving} onClick={() => save(true)}>{saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} {tCommon('actions.save')}</button>
            <button
              className={`${button} border-emerald-500/50 text-emerald-300`}
              disabled={generatingArtwork}
              onClick={() => void generateComicArtwork()}
              title={project.director ? t('toolbar.generateTitle') : t('toolbar.generateNeedPlan')}
            >
              {generatingArtwork ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
              {remainingArtworkPanels > 0 ? t('generate.remaining', { count: remainingArtworkPanels }) : totalArtworkPanels ? t('generate.done') : t('generate.action')}
            </button>
            <button className={button} disabled={!history.past.length} onClick={undo}><Undo2 size={13} /></button>
            <button className={button} disabled={!history.future.length} onClick={redo}><Redo2 size={13} /></button>
            <button className={`${button} ${snapEnabled ? 'border-accent-blue text-accent-blue' : ''}`} onClick={() => setSnapEnabled(!snapEnabled)}>{t('toolbar.grid')}</button>
            <div className="ml-auto flex items-center gap-1">
              <button className={button} onClick={exportComicJson}><FileJson size={13} /> {t('toolbar.json')}</button>
              <button className={button} disabled={!!exporting} onClick={() => runExport('png')}>{t('toolbar.png')}</button>
              <button className={button} disabled={!!exporting} onClick={() => runExport('cbz')}>{t('toolbar.cbz')}</button>
              <button className={`${button} border-accent-blue/50`} disabled={!!exporting} onClick={() => runExport('pdf')}>
                {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />} {exporting || t('toolbar.pdf')}
              </button>
              <TranslatedPdfExport notify={notify} />
              <button className={button} onClick={() => setToolbarCollapsed(true)} title={t('toolbar.collapse')}>
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
                <h2 className="text-sm font-semibold text-text-primary">{t('history.title')}</h2>
                <p className="text-[10px] text-text-muted">
                  {t('history.hint', { workspace: activeWorkspace })}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button className={button} disabled={historyLoading} onClick={() => void refreshComicHistory()}>
                  {historyLoading ? <Loader2 size={13} className="animate-spin" /> : <HistoryIcon size={13} />} {tCommon('actions.refresh')}
                </button>
                <button className={button} onClick={() => setHistoryOpen(false)} aria-label={t('history.closeAria')}>
                  <X size={13} />
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {historyLoading && comicHistory.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-12 text-xs text-text-muted">
                  <Loader2 size={14} className="animate-spin" /> {t('history.loading')}
                </div>
              ) : comicHistory.length === 0 ? (
                <div className="py-12 text-center text-xs text-text-muted">
                  {t('history.empty')}
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
                            <span className="shrink-0 rounded bg-accent-blue/15 px-1.5 py-0.5 text-[9px] text-accent-blue">{t('history.current')}</span>
                          )}
                        </div>
                        <div className="mt-1 truncate text-[10px] text-text-muted">
                          {t('history.meta', {
                            reason: HISTORY_REASON_KEYS[entry.reason] ? t(HISTORY_REASON_KEYS[entry.reason]) : entry.reason,
                            pages: entry.pageCount,
                            assets: entry.assetCount,
                            saved: entry.persistedName ? ` · ${entry.persistedName}` : '',
                          })}
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
                        {t('history.restore')}
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
        {sideTab !== 'pre' && <PagesRail />}
        <section className="flex-1 min-w-0 flex flex-col bg-[#15171b]">
          {sideTab === 'pre' ? (
            <>
              <div className="shrink-0 border-b border-border p-2 flex items-center gap-2 text-xs text-text-muted">
                <button className={button} onClick={() => selectSideTab('video')}>
                  <ChevronLeft size={12} /> {t('side.back')}
                </button>
                <span className="font-semibold text-text-primary">{t('side.preTitle')}</span>
                <span className="hidden sm:inline">{t('side.preNote')}</span>
              </div>
              <div className="flex-1 min-h-0 overflow-auto">
                <ComicVideoPreflightPanel notify={notifyWorkflow} onDirtyChange={setPreDirty} />
              </div>
            </>
          ) : (
            <>
              <div className="shrink-0 border-b border-border p-2 flex items-center justify-center gap-2 text-xs text-text-muted">
                <button
                  className={button}
                  disabled={currentPageIndex === 0}
                  onClick={() => goToPage(currentPageIndex - 1)}
                  title={t('pages.previous')}
                >
                  <ChevronLeft size={12} />
                </button>
                <select
                  className={`${input} w-28`}
                  value={currentPageId}
                  onChange={event => useComicStore.getState().setCurrentPage(event.target.value)}
                  aria-label={t('pages.currentAria')}
                >
                  {project.pages.map((page, index) => (
                    <option key={page.id} value={page.id}>{t('pages.pageOf', { current: index + 1, total: project.pages.length })}</option>
                  ))}
                </select>
                <button
                  className={button}
                  disabled={currentPageIndex >= project.pages.length - 1}
                  onClick={() => goToPage(currentPageIndex + 1)}
                  title={t('pages.next')}
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
                  title={t('preview.fitTitle')}
                >
                  <Maximize2 size={12} /> {t('preview.fit')}
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
            </>
          )}
        </section>
        <aside className={`shrink-0 border-l border-border bg-bg-secondary flex flex-col min-h-0 transition-[width] ${
          sidePanelCollapsed ? 'w-10' : 'w-72 xl:w-80'
        }`}>
          {sidePanelCollapsed ? (
            <button
              className="h-full flex flex-col items-center gap-2 py-3 text-[10px] text-text-muted hover:text-accent-blue"
              onClick={() => setSidePanelCollapsed(false)}
              title={t('side.expand')}
            >
              <ChevronLeft size={15} />
              <span className="[writing-mode:vertical-rl]">{t('side.tools')}</span>
            </button>
          ) : (
            <>
              <div className="flex border-b border-border">
                <div className="grid flex-1 grid-cols-3">
                  {([
                    ['assets', 'tabs.assets'],
                    ['inspector', 'tabs.inspector'],
                    ['script', 'tabs.script'],
                    ['characters', 'tabs.characters'],
                    ['quality', 'tabs.quality'],
                    ['video', 'tabs.video'],
                    ['pre', 'tabs.pre'],
                    ['director', 'tabs.director'],
                  ] as const).map(([id, label]) => (
                    <button key={id} className={`py-2 text-[11px] ${sideTab === id ? 'text-accent-blue border-b-2 border-accent-blue' : 'text-text-muted'}`} onClick={() => selectSideTab(id)}>{t(label)}</button>
                  ))}
                </div>
                <button
                  className="w-9 border-l border-border text-text-muted hover:text-accent-blue"
                  onClick={() => setSidePanelCollapsed(true)}
                  title={t('side.collapse')}
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
                {sideTab === 'pre' && <p className="text-xs text-text-muted">{t('side.preHint')}</p>}
                {sideTab === 'director' && <ComicDirectorPanel notify={notify} />}
              </div>
            </>
          )}
        </aside>
      </div>
      {previewOpen && (
        <div className="fixed inset-0 z-[2000] flex flex-col bg-[#090a0d]/95 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={t('preview.aria')}>
          <div className="shrink-0 flex items-center gap-2 border-b border-white/10 bg-black/40 px-3 py-2 text-xs text-white/70">
            <span className="font-medium text-white">{t('preview.title')}</span>
            <span>{t('pages.pageOf', { current: currentPageIndex + 1, total: project.pages.length })}</span>
            <div className="ml-auto flex items-center gap-1.5">
              <button className={button} disabled={currentPageIndex === 0} onClick={() => goToPage(currentPageIndex - 1)}><ChevronLeft size={13} /> {t('preview.previous')}</button>
              <button className={button} disabled={currentPageIndex >= project.pages.length - 1} onClick={() => goToPage(currentPageIndex + 1)}>{t('preview.next')} <ChevronRight size={13} /></button>
              <button className={button} onClick={() => setPreviewOpen(false)}><X size={13} /> {tCommon('actions.close')}</button>
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
