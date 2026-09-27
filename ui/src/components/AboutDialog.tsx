import { useState } from 'react'
import { Copy, ExternalLink, GitBranch, Info, X } from 'lucide-react'
import { useUiTranslation } from '../i18n'
import type { AboutInfo } from '../api/about'
import { BUNDLE_COMMIT, buildState, commitUrl, shortCommit } from '../lib/buildIdentity'

function formatWhen(value: string | undefined, locale: string): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale)
}

function CommitRow({ label, commit, detail, repository }: { label: string; commit?: string; detail?: string; repository: string }) {
  const { t } = useUiTranslation('common')
  const [copied, setCopied] = useState(false)
  const url = commitUrl(repository, commit)
  const copy = () => {
    if (!commit) return
    void navigator.clipboard?.writeText(commit)
    setCopied(true)
  }
  return <div className="flex items-start justify-between gap-3 py-1.5">
    <div className="min-w-0">
      <div className="text-[11px] text-text-muted">{label}</div>
      {detail && <div className="text-[10px] text-text-muted">{detail}</div>}
    </div>
    <div className="flex shrink-0 items-center gap-2 font-mono text-[11px]">
      {url ? <a href={url} target="_blank" rel="noreferrer" className="text-accent-blue hover:underline">{shortCommit(commit)}</a>
        : <span className="text-text-secondary">{commit || '—'}</span>}
      {commit && <button type="button" onClick={copy} className="text-text-muted hover:text-text-primary" title={copied ? t('about.copied') : t('about.copy')} aria-label={t('about.copy')}>
        <Copy size={12} />
      </button>}
    </div>
  </div>
}

export function AboutDialog({ about, error, onClose }: { about: AboutInfo | null; error: boolean; onClose: () => void }) {
  const { t, i18n } = useUiTranslation('common')
  const state = buildState(about)
  const repository = about?.repository ?? 'https://github.com/IAnMove/hocuspocus'
  const dirty = about?.backend.dirty ? ` · ${t('about.dirty')}` : ''
  return (
    <div className="fixed inset-0 z-[130] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="about-title"
        className="max-h-[88vh] w-[480px] max-w-[94vw] overflow-y-auto rounded-2xl border border-border bg-bg-secondary shadow-2xl"
        onClick={event => event.stopPropagation()}>
        <div className="flex items-start gap-3 px-6 pb-3 pt-6">
          <img src="/hocuspocus-icon.png" alt="" className="h-11 w-11 shrink-0 object-contain" draggable={false} />
          <div className="flex-1">
            <h2 id="about-title" className="text-base font-semibold text-text-primary">{t('about.title')}</h2>
            <p className="mt-0.5 text-xs text-text-muted">{t('about.subtitle')}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-text-muted hover:text-text-primary" aria-label={t('about.close')}>
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4 px-6 pb-6 text-xs">
          <p className="leading-relaxed text-text-secondary">{t('about.description')}</p>
          <div className="flex flex-wrap gap-2">
            <a href={repository} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-bg-tertiary/50 px-3 py-2 text-text-primary hover:bg-bg-hover">
              <GitBranch size={14} /> {t('about.repository')} <ExternalLink size={11} className="text-text-muted" />
            </a>
            <a href={about?.author.x_url ?? 'https://x.com/theinaog'} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-bg-tertiary/50 px-3 py-2 text-text-primary hover:bg-bg-hover">
              <span className="font-semibold">𝕏</span> @{about?.author.x_handle ?? 'theinaog'} <ExternalLink size={11} className="text-text-muted" />
            </a>
          </div>

          <section className="rounded-xl border border-border bg-bg-tertiary/40 px-3 py-2" aria-label={t('about.deployment')}>
            <div className="flex items-center justify-between pb-1">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">{t('about.deployment')}</h3>
              {about && <span className="text-[11px] text-text-secondary">v{about.version}</span>}
            </div>
            {error && <p className="py-1.5 text-red-300">{t('about.unavailable')}</p>}
            {about && <>
              <CommitRow repository={repository} label={t('about.backend')} commit={about.backend.commit}
                detail={t('about.backendDetail', { branch: about.backend.branch ?? '—', when: formatWhen(about.backend.started_at, i18n.language) }) + dirty} />
              <CommitRow repository={repository} label={t('about.uiBuild')} commit={about.ui.commit}
                detail={t('about.uiBuildDetail', { when: formatWhen(about.ui.built_at, i18n.language) })} />
              <CommitRow repository={repository} label={t('about.thisTab')} commit={BUNDLE_COMMIT || undefined} />
            </>}
            {state !== 'in-sync' && about && <p className={`mt-1 rounded-lg px-2 py-1.5 ${state === 'unknown' ? 'text-text-muted' : 'bg-amber-500/10 text-amber-200'}`}>
              {t(`about.state.${state}`)}
              {state === 'reload' && <button type="button" onClick={() => window.location.reload()} className="ml-2 text-accent-blue hover:underline">{t('about.reload')}</button>}
            </p>}
          </section>

          <section aria-label={t('about.credits')}>
            <h3 className="flex items-center gap-1.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted"><Info size={12} /> {t('about.credits')}</h3>
            <ul className="space-y-0.5 text-[11px] text-text-secondary">
              {(about?.credits ?? []).map(item => <li key={item.name}><span className="text-text-primary">{item.name}</span> · {t(`about.roles.${item.role}`, { defaultValue: item.role })}</li>)}
            </ul>
          </section>
        </div>
      </div>
    </div>
  )
}
