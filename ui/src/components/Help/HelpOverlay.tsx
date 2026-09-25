import { CircleHelp, X } from 'lucide-react'
import { setUiLanguage, useUiTranslation, type UiLanguage } from '../../i18n'
import { ModalShell } from '../common/ModalShell'

const SECTIONS = [
  { id: 'start', image: '/help/direct-image.jpg', imageKey: 'directImage' },
  { id: 'wizard', image: '/help/wizard.jpg', imageKey: 'wizard' },
  { id: 'direct', image: '/help/direct-video.jpg', imageKey: 'directVideo' },
  { id: 'queue', image: '/help/activity.jpg', imageKey: 'activity' },
  { id: 'studios', image: '/help/story-lab.jpg', imageKey: 'storyLab' },
  { id: 'faces', image: '/help/character-creator.jpg', imageKey: 'characterCreator' },
  { id: 'tijeral', image: '/help/story-lab.jpg', imageKey: 'storyLab' },
  { id: 'video3d', image: '/help/video-3d.jpg', imageKey: 'video3d' },
  { id: 'production', image: '/help/director.jpg', imageKey: 'director' },
  { id: 'media', image: '/help/media.jpg', imageKey: 'media' },
  { id: 'settings', image: '/help/settings.jpg', imageKey: 'settings' },
  { id: 'examples' },
] as const

export function HelpOverlay({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, i18n } = useUiTranslation('help')
  const language: UiLanguage = String(i18n.resolvedLanguage || i18n.language).startsWith('es') ? 'es' : 'en'

  if (!open) return null

  return (
    <ModalShell
      open={open}
      title={t('title')}
      onClose={onClose}
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-3 md:p-6"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}
    >
      <div
        className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl"
      >
        <div className="flex items-center gap-3 border-b border-border px-4 py-3">
          <CircleHelp size={16} className="text-accent-blue" />
          <h2 className="flex-1 text-sm font-semibold">{t('title')}</h2>
          <label className="flex items-center gap-1 text-[10px] text-text-muted">
            <span className="sr-only">{t('languageLabel')}</span>
            <select
              value={language}
              aria-label={t('languageLabel')}
              onChange={event => { void setUiLanguage(event.target.value as UiLanguage) }}
              className="cursor-pointer rounded-md bg-bg-primary px-2 py-1 text-[10px] text-text-secondary outline-none"
            >
              <option value="es">ES</option>
              <option value="en">EN</option>
            </select>
          </label>
          <button type="button" onClick={onClose} aria-label={t('close')} className="rounded-lg p-1.5 text-text-secondary hover:bg-bg-hover hover:text-text-primary">
            <X size={16} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <p className="mb-4 text-xs text-text-muted">{t('draft')}</p>
          <nav className="mb-6 flex flex-wrap gap-x-3 gap-y-1 text-xs" aria-label={t('title')}>
            {SECTIONS.map(section => (
              <a key={section.id} href={`#help-${section.id}`} className="text-accent-blue hover:underline">{t(`nav.${section.id}` as const)}</a>
            ))}
          </nav>
          {SECTIONS.map(section => (
            <section key={section.id} id={`help-${section.id}`} className="mb-8 scroll-mt-4">
              <h3 className="mb-2 text-sm font-semibold">{t(`${section.id}.title` as const)}</h3>
              {String(t(`${section.id}.body` as const)).split('\n\n').map((paragraph, index) => (
                <p key={`${section.id}-${index}`} className="mb-2 text-sm text-text-secondary">{paragraph}</p>
              ))}
              {'image' in section && section.image ? (
                <figure className="mt-3">
                  <img src={section.image} alt={t(`images.${section.imageKey}` as const)} className="w-full rounded-lg border border-border" />
                </figure>
              ) : null}
              {section.id === 'examples' ? (
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <figure>
                    <img src="/help/example-image.jpg" alt={t('images.exampleImage')} className="w-full rounded-lg border border-border" />
                  </figure>
                  <figure>
                    <img src="/help/example-video.jpg" alt={t('images.exampleVideo')} className="w-full rounded-lg border border-border" />
                  </figure>
                </div>
              ) : null}
            </section>
          ))}
        </div>
      </div>
    </ModalShell>
  )
}
