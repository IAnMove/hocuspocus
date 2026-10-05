import { useRef, useState, type KeyboardEvent } from 'react'
import { Search, X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { ModalShell } from '../../components/common/ModalShell'
import { campaignCard } from './campaignTemplates'
import { actionCard } from './actionTemplates'
import { animeCard } from './animeTemplates'
import { SCENE3D_TEMPLATES, type Scene3DTemplate, type Scene3DTemplateId } from './templates'
import { filterScene3DTemplates, settingsIn, type TemplateSetting } from './templateFilters'
import { CORE_TEMPLATES, isCoreTemplate, templateCollections } from './templateCatalog'
import { ExampleDownloads } from './ExampleDownloads'
import { Scene3DTemplateThumb } from './Scene3DTemplateThumb'
import { Scene3DUserTemplates } from './Scene3DUserTemplates'
import { gridFocusTarget, LIBRARY_CATEGORIES, readLibraryView, readRecentShots, rememberRecentShot, saveLibraryView, type LibraryCategory, type LibraryView } from './shotLibraryState'
import type { Scene3DDocument } from './types.ts'
import type { World3DUserTemplate } from './userTemplates.ts'

type Pick = { kind: 'template'; id: Scene3DTemplateId } | { kind: 'user'; pack: World3DUserTemplate }

export type ShotLibraryProps = {
  document: Scene3DDocument
  /** The imported scenario the scene came from, if any, instead of a built-in shot. */
  userTemplateId?: string
  /** Applying is blocked (while exporting); browsing is not. */
  applyDisabled: boolean
  editingLocked: boolean
  keepAssets: boolean
  onKeepAssets: (keep: boolean) => void
  onTemplate: (id: Scene3DTemplateId) => void
  onUserTemplate: (pack: World3DUserTemplate) => void
  onClose: () => void
  /** Workspace used to save and apply library templates. */
  workspace?: string
  /** PNG data URL of the current frame, used as a template preview. */
  preview?: () => string | undefined
}

/** The shot library in its own dialog: pick a shot, look at it, then use it. */
export function Scene3DShotLibraryDialog(props: ShotLibraryProps) {
  const { t } = useUiTranslation('scene3dEditor')
  return <ModalShell open title={t('templates')} onClose={props.onClose}
    className="fixed inset-0 z-[130] flex items-center justify-center bg-black/70 p-2 sm:p-4"
    onMouseDown={event => { if (event.target === event.currentTarget) props.onClose() }}>
    <ShotLibraryBody {...props} />
  </ModalShell>
}

function libraryDownloads(mode: 'templates' | 'examples', picked: Pick | undefined) {
  const required = picked?.kind === 'template' ? templateCollections(picked.id) : []
  if (required.length) return { required }
  return mode === 'examples' ? {} : null
}

function ShotLibraryBody(props: ShotLibraryProps) {
  const { t, i18n } = useUiTranslation('scene3dEditor')
  const locale = i18n.language.startsWith('es') ? 'es' : 'en'
  const [mode, setMode] = useState<'templates' | 'examples'>(() => {
    const category = readLibraryView().category
    return LIBRARY_CATEGORIES.includes(category as typeof LIBRARY_CATEGORIES[number]) &&
      !filterScene3DTemplates({ category: category as typeof LIBRARY_CATEGORIES[number], setting: 'all', query: '', locale: 'en', titleOf: id => id }).some(item => isCoreTemplate(item.id)) ? 'examples' : 'templates'
  })
  const [view, setViewState] = useState<LibraryView>(readLibraryView)
  const [recent, setRecent] = useState(readRecentShots)
  const current: Pick = { kind: 'template', id: props.document.templateId }
  const [picked, setPicked] = useState<Pick | undefined>(props.userTemplateId ? undefined : current)
  const setView = (next: Partial<LibraryView>) => setViewState(before => { const view = { ...before, ...next }; saveLibraryView(view); return view })
  const titleOf = (id: Scene3DTemplateId) => `${t(`template.${id}.title`)} ${t(`template.${id}.description`)}`
  const filter = { query: view.query, locale, titleOf } as const
  const candidates = view.category === 'recent' ? SCENE3D_TEMPLATES : mode === 'templates' ? CORE_TEMPLATES : SCENE3D_TEMPLATES.filter(item => !isCoreTemplate(item.id))
  const allowed = new Set(candidates.map(item => item.id))
  const inCatalog = (items: Scene3DTemplate[]) => items.filter(item => allowed.has(item.id))
  const shown = view.category === 'recent'
    ? recentTemplates(recent, filterScene3DTemplates({ ...filter, category: 'all', setting: 'all' }))
    : view.category === 'mine' ? [] : inCatalog(filterScene3DTemplates({ ...filter, category: view.category, setting: view.setting }))
  const settings = view.category === 'recent' || view.category === 'mine' ? [] : settingsIn(inCatalog(filterScene3DTemplates({ ...filter, category: view.category, setting: 'all' })))
  const downloads = libraryDownloads(mode, picked)
  const use = (choice = picked) => {
    if (!choice || props.applyDisabled) return
    if (choice.kind === 'template') { setRecent(rememberRecentShot(choice.id)); props.onTemplate(choice.id) } else props.onUserTemplate(choice.pack)
    props.onClose()
  }
  return <div className="flex h-full max-h-[56rem] w-full max-w-[96rem] flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl" data-testid="world3d-shot-library">
    <header className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
      <h2 className="mr-auto text-base font-semibold text-text-primary">{t('templates')}
        {view.category !== 'mine' && <span className="ml-2 text-sm font-normal text-text-muted">{t('filterCount', { shown: shown.length, total: candidates.length })}</span>}
      </h2>
      <label className="flex min-h-10 min-w-[14rem] flex-1 items-center gap-2 rounded-lg border border-border bg-bg-primary px-3 text-text-muted sm:max-w-md"><Search size={16} />
        <input type="search" value={view.query} onChange={event => setView({ query: event.target.value })} placeholder={t('search')} aria-label={t('search')}
          className="min-w-0 flex-1 bg-transparent text-sm text-text-primary outline-none" />
      </label>
      <div role="group" aria-label={t('examples.catalog')} className="flex gap-1">
        {(['templates', 'examples'] as const).map(value => <button key={value} type="button" aria-pressed={mode === value}
          className="rounded-lg border border-border px-3 py-2 text-sm" onClick={() => { setMode(value); setView({ category: 'all', setting: 'all', query: '' }); setPicked(undefined) }}>{t(`examples.${value}`)}</button>)}
      </div>
      <button type="button" onClick={props.onClose} aria-label={t('shotLibrary.close')} className="flex min-h-10 min-w-10 items-center justify-center rounded-lg border border-border hover:bg-bg-hover"><X size={18} /></button>
    </header>
    <p className="border-b border-border px-4 py-2 text-xs text-text-muted">{t('shotLibrary.optionalExamples')}</p>
    {downloads && <ExampleDownloads disabled={props.editingLocked} {...downloads} />}
    <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto md:grid-cols-[12rem_minmax(0,1fr)] md:overflow-hidden lg:grid-cols-[12rem_minmax(0,1fr)_20rem]">
      <LibrarySidebar available={LIBRARY_CATEGORIES.filter(category => filterScene3DTemplates({ category, setting: 'all', query: '', locale, titleOf }).some(item => allowed.has(item.id)))} view={view} hasRecent={recent.length > 0} settings={settings} onView={setView} />
      <main className="min-h-0 overflow-y-auto p-3">
        {view.category === 'mine'
          ? <Scene3DUserTemplates document={props.document} workspace={props.workspace} preview={props.preview} disabled={props.editingLocked} selectedId={picked?.kind === 'user' ? picked.pack.id : undefined}
            onApply={pack => setPicked({ kind: 'user', pack })} />
          : <ShotGrid templates={shown} picked={picked?.kind === 'template' ? picked.id : undefined} current={props.userTemplateId ? undefined : props.document.templateId}
            onPick={id => setPicked({ kind: 'template', id })} onUse={id => use({ kind: 'template', id })} />}
      </main>
      <aside className="hidden min-h-0 overflow-y-auto border-l border-border p-3 lg:block">
        <ShotPreview picked={picked} current={props.userTemplateId ? undefined : props.document.templateId} locale={locale} />
      </aside>
    </div>
    <footer className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
      <label className="mr-auto flex min-h-10 items-center gap-2 text-xs text-text-secondary">
        <input type="checkbox" checked={props.keepAssets} onChange={event => props.onKeepAssets(event.target.checked)} />{t('keepAssets')}
      </label>
      <span className="hidden text-xs text-text-muted sm:inline">{t('shotLibrary.hint')}</span>
      <button type="button" onClick={props.onClose} className="min-h-10 rounded-lg border border-border px-4 text-sm hover:bg-bg-hover">{t('shotLibrary.cancel')}</button>
      <button type="button" disabled={!picked || props.applyDisabled} onClick={() => use()} data-testid="world3d-use-shot"
        className="min-h-10 rounded-lg border border-cyan-300 bg-cyan-300/15 px-4 text-sm font-semibold text-cyan-100 hover:bg-cyan-300/25 disabled:opacity-40">{t('shotLibrary.use')}</button>
    </footer>
  </div>
}

function recentTemplates(ids: Scene3DTemplateId[], matching: Scene3DTemplate[]) {
  const byId = new Map(matching.map(item => [item.id, item]))
  return ids.flatMap(id => byId.get(id) ?? [])
}

function LibrarySidebar({ available, view, hasRecent, settings, onView }: {
  available: readonly LibraryCategory[]; view: LibraryView; hasRecent: boolean; settings: TemplateSetting[]; onView: (view: Partial<LibraryView>) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const categories: LibraryCategory[] = [...(hasRecent ? ['recent' as const] : []), 'all', ...available, 'mine']
  const label = (item: LibraryCategory) => item === 'all' ? t('all') : item === 'recent' ? t('shotLibrary.recent') : item === 'mine' ? t('userTemplates.title') : t(`category.${item}`)
  return <nav className="flex flex-col gap-3 border-b border-border p-3 md:min-h-0 md:overflow-y-auto md:border-b-0 md:border-r" aria-label={t('filterCategory')}>
    <div className="flex flex-wrap gap-1 md:flex-col" role="group" aria-label={t('filterCategory')}>
      {categories.map(item => <button key={item} type="button" onClick={() => onView({ category: item, setting: 'all' })} aria-pressed={view.category === item}
        className={`min-h-9 rounded-lg px-3 text-left text-sm ${view.category === item ? 'bg-cyan-300/15 font-medium text-cyan-100' : 'text-text-secondary hover:bg-bg-hover'}`}>{label(item)}</button>)}
    </div>
    {settings.length > 1 && <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('filterSetting')}>
      {(['all', ...settings] as const).map(item => <button key={item} type="button" onClick={() => onView({ setting: item })} aria-pressed={view.setting === item}
        className={`min-h-8 rounded-full border px-2.5 text-[11px] font-medium ${view.setting === item ? 'border-amber-300 bg-amber-300/15 text-amber-100' : 'border-border text-text-muted hover:bg-bg-hover'}`}>
        {item === 'all' ? t('allSettings') : t(`setting.${item}`)}
      </button>)}
    </div>}
  </nav>
}

function ShotGrid({ templates, picked, current, onPick, onUse }: {
  templates: Scene3DTemplate[]; picked?: Scene3DTemplateId; current?: Scene3DTemplateId
  onPick: (id: Scene3DTemplateId) => void; onUse: (id: Scene3DTemplateId) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const grid = useRef<HTMLDivElement>(null)
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    const cards = Array.from(grid.current?.querySelectorAll<HTMLButtonElement>('[data-shot-card]') ?? [])
    const index = cards.indexOf(document.activeElement as HTMLButtonElement)
    if (index < 0) return
    if (event.key === 'Enter') { event.preventDefault(); onUse(templates[index].id); return }
    const columns = getComputedStyle(grid.current!).gridTemplateColumns.split(' ').filter(Boolean).length || 1
    const next = gridFocusTarget(index, event.key, cards.length, columns)
    if (next === undefined) return
    event.preventDefault()
    cards[next].focus()
    onPick(templates[next].id)
  }
  if (!templates.length) return <p role="status" className="p-4 text-sm text-text-secondary">{t('noResults')}</p>
  return <div ref={grid} onKeyDown={keys} className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
    {templates.map(item => <button key={item.id} type="button" data-shot-card onClick={() => onPick(item.id)} onDoubleClick={() => onUse(item.id)} aria-pressed={picked === item.id}
      data-testid={`world3d-template-${item.id}`}
      className={`overflow-hidden rounded-lg border text-left transition-colors focus-visible:outline-2 focus-visible:outline-cyan-200 ${picked === item.id ? 'border-cyan-300 bg-cyan-300/10' : 'border-border bg-bg-primary hover:border-cyan-300/50'}`}>
      <Scene3DTemplateThumb id={item.id} portrait={item.frameFormat === 'portrait'} fill />
      <span className="flex items-start justify-between gap-2 px-3 pt-2 text-sm font-semibold text-text-primary">{t(`template.${item.id}.title`)}
        <span className="whitespace-nowrap text-xs font-normal tabular-nums text-text-muted">{current === item.id ? `${t('shotLibrary.current')} · ` : ''}{item.duration} s</span></span>
      <span className="mt-0.5 line-clamp-2 px-3 pb-2 text-[11px] leading-4 text-text-secondary">{t(`template.${item.id}.description`)}</span>
    </button>)}
  </div>
}

function ShotPreview({ picked, current, locale }: { picked?: Pick; current?: Scene3DTemplateId; locale: 'en' | 'es' }) {
  const { t } = useUiTranslation('scene3dEditor')
  if (!picked) return <p className="text-sm text-text-muted">{t('shotLibrary.pickOne')}</p>
  if (picked.kind === 'user') return <div className="space-y-2" data-testid="world3d-shot-preview">
    <h3 className="text-base font-semibold text-text-primary">{picked.pack.title}</h3>
    <p className="text-sm leading-5 text-text-secondary">{picked.pack.description || t('userTemplates.noDescription')}</p>
  </div>
  const item = SCENE3D_TEMPLATES.find(template => template.id === picked.id)
  const card = campaignCard(picked.id, locale) ?? actionCard(picked.id, locale) ?? animeCard(picked.id, locale)
  return <div className="space-y-3" data-testid="world3d-shot-preview">
    <Scene3DTemplateThumb id={picked.id} portrait={item?.frameFormat === 'portrait'} fill />
    <h3 className="text-base font-semibold text-text-primary">{t(`template.${picked.id}.title`)}</h3>
    <p className="text-xs tabular-nums text-text-muted">{current === picked.id ? `${t('shotLibrary.current')} · ` : ''}{item?.duration} s</p>
    <p className="text-sm leading-5 text-text-secondary">{t(`template.${picked.id}.description`)}</p>
    {card?.requirements.map(req => <p key={req} className="text-xs leading-4 text-text-muted">{req}</p>)}
  </div>
}
