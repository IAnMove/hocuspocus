import { useCallback, useEffect, useState } from 'react'
import { Download, Loader2, RefreshCw } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { installCommunityTemplate, listCommunityTemplates, type CommunityTemplate, type TemplateEditor } from '../../api/templates'
import { authorLabel } from './templateForm'

const button = 'inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-xs hover:bg-bg-hover disabled:opacity-40'

function CommunityCard({ item, busy, onInstall }: { item: CommunityTemplate; busy: boolean; onInstall: (replace: boolean) => void }) {
  const { t } = useUiTranslation('common')
  const action = item.state === 'available' ? 'install' : item.state === 'update' ? 'update' : item.state === 'conflict' ? 'replace' : null
  return <article className="overflow-hidden rounded-lg border border-border bg-bg-primary">
    {item.preview ? <img src={item.preview} alt="" className="aspect-video w-full object-cover" loading="lazy" referrerPolicy="no-referrer" /> : <div className="aspect-video w-full bg-bg-tertiary" />}
    <div className="p-3 text-xs">
      <p className="text-sm font-semibold text-text-primary">{item.title}</p>
      <p className="mt-1 leading-5 text-text-secondary">{item.description || t('templateLibrary.noDescription')}</p>
      <p className="mt-1 text-[11px] text-text-muted">
        {[authorLabel(item.author), item.license, t('templateLibrary.slotCount', { count: item.slots }), `${Math.max(1, Math.round(item.bytes / 1024))} KB`].filter(Boolean).join(' · ')}
      </p>
      {item.tags.length > 0 && <p className="mt-1 text-[11px] text-cyan-200">{item.tags.map(tag => `#${tag}`).join(' ')}</p>}
      <div className="mt-2 flex items-center gap-2">
        {action ? <button type="button" className={button} disabled={busy} onClick={() => onInstall(item.state === 'conflict')}>
          <Download size={12} /> {t(`templateLibrary.community.${action}`)}</button>
          : <span className="text-[11px] text-emerald-300">{t('templateLibrary.community.installed')}</span>}
        {item.state === 'conflict' && <span className="text-[11px] text-amber-200">{t('templateLibrary.community.conflictHint')}</span>}
      </div>
    </div>
  </article>
}

/** Community tab: browse the shared index and install templates into the local library. */
export function CommunityTemplates({ editor, onInstalled }: { editor: TemplateEditor; onInstalled: () => void }) {
  const { t } = useUiTranslation('common')
  const [items, setItems] = useState<CommunityTemplate[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')

  const load = useCallback(async (refresh = false) => {
    setError('')
    try { setItems((await listCommunityTemplates(editor, refresh)).templates) } catch (failure) { setItems([]); setError((failure as Error).message) }
  }, [editor])
  useEffect(() => { void load() }, [load])

  const install = async (item: CommunityTemplate, replace: boolean) => {
    setBusy(true); setError(''); setNote('')
    try {
      await installCommunityTemplate(item.id, replace)
      setNote(t('templateLibrary.community.done', { title: item.title })); onInstalled(); await load()
    } catch (failure) { setError((failure as Error).message) } finally { setBusy(false) }
  }

  return <section aria-label={t('templateLibrary.community.title')} className="mt-3">
    <div className="flex flex-wrap items-center gap-2">
      <p className="mr-auto text-xs text-text-secondary">{t('templateLibrary.community.help')}</p>
      <button type="button" className={button} disabled={busy} onClick={() => void load(true)}><RefreshCw size={12} /> {t('templateLibrary.community.refresh')}</button>
    </div>
    {items === null && <p className="mt-3 flex items-center gap-2 text-xs text-text-muted"><Loader2 size={13} className="animate-spin" /> {t('templateLibrary.community.loading')}</p>}
    {note && <p role="status" className="mt-2 text-xs text-text-secondary">{note}</p>}
    {error && <p role="alert" className="mt-2 text-xs text-red-300">{error}</p>}
    <div className="mt-3 grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-2">
      {(items ?? []).map(item => <CommunityCard key={item.id} item={item} busy={busy} onInstall={replace => void install(item, replace)} />)}
    </div>
    {items?.length === 0 && !error && <p role="status" className="p-3 text-xs text-text-secondary">{t('templateLibrary.community.empty')}</p>}
  </section>
}
