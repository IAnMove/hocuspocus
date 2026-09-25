import { useState } from 'react'
import { Sparkles, Download, Cpu, GitPullRequest, X } from 'lucide-react'
import { useUiTranslation } from '../i18n'
import { safeStorageGet, safeStorageSet } from '../lib/safeStorage'
import { latestWhatsNewPr, WELCOME_SEEN_KEY, WHATS_NEW } from '../whatsNew'

/**
 * WelcomeModal — first-run keys plus a scrollable one-liner per recent PR.
 * Re-shown when the newest listed PR changes.
 */
export function WelcomeModal() {
  const { t, i18n } = useUiTranslation('common')
  const [open, setOpen] = useState(() => safeStorageGet('local', WELCOME_SEEN_KEY) !== String(latestWhatsNewPr()))
  const locale = i18n.language.startsWith('es') ? 'es' : 'en'

  if (!open) return null

  const dismiss = () => {
    safeStorageSet('local', WELCOME_SEEN_KEY, String(latestWhatsNewPr()))
    setOpen(false)
  }

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/60 p-4" onClick={dismiss}>
      <div
        className="bg-bg-secondary border border-border rounded-2xl shadow-2xl w-[520px] max-w-[94vw] max-h-[88vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 pt-6 pb-4 flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl bg-accent-blue/15 flex items-center justify-center shrink-0">
            <Sparkles size={22} className="text-accent-blue" />
          </div>
          <div className="flex-1">
            <h2 className="text-base font-semibold text-text-primary">{t('welcome.title')}</h2>
            <p className="text-xs text-text-muted mt-0.5">
              {t('welcome.subtitle')}
            </p>
          </div>
          <button onClick={dismiss} className="p-1 rounded text-text-muted hover:text-text-primary" aria-label={t('welcome.closeAria')}>
            <X size={16} />
          </button>
        </div>

        {/* Points */}
        <div className="px-6 pb-2 space-y-3.5">
          <Row icon={<Download size={16} className="text-accent-blue" />} title={t('welcome.modelsTitle')}>
            {t('welcome.modelsBody')}
          </Row>
          <Row icon={<Cpu size={16} className="text-accent-blue" />} title={t('welcome.directorTitle')}>
            {t('welcome.directorBody')}
          </Row>
          <Row icon={<GitPullRequest size={16} className="text-accent-blue" />} title={t('welcome.recentTitle')}>
            {t('welcome.recentHint')}
          </Row>
          <ul
            className="max-h-44 overflow-y-auto rounded-xl border border-border bg-bg-tertiary/40 px-3 py-2 space-y-1.5"
            aria-label={t('welcome.recentTitle')}
          >
            {WHATS_NEW.map(item => (
              <li key={item.pr} className="text-[11px] leading-snug text-text-secondary">
                <a
                  href={`https://github.com/IAnMove/hocuspocus/pull/${item.pr}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent-blue hover:underline"
                >
                  #{item.pr}
                </a>
                <span className="text-text-muted"> · </span>
                <span>{item[locale]}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 flex items-center justify-end gap-3">
          <button
            onClick={dismiss}
            className="px-5 py-2 text-xs bg-accent-blue text-white rounded-lg hover:bg-accent-blue-hover transition-colors font-medium"
          >
            {t('welcome.enter')}
          </button>
        </div>
      </div>
    </div>
  )
}

function Row({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-8 h-8 rounded-lg bg-bg-tertiary/60 flex items-center justify-center shrink-0 mt-0.5">
        {icon}
      </div>
      <div className="flex-1">
        <div className="text-xs font-medium text-text-primary">{title}</div>
        <div className="text-[11px] text-text-muted mt-0.5 leading-relaxed">{children}</div>
      </div>
    </div>
  )
}
