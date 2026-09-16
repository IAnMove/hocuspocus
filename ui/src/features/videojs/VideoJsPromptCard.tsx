import { useState } from 'react'
import { Loader2, Sparkles, WandSparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { VIDEOJS_FORMATS, videoJsFormatOf, type VideoJsFormat } from './document.ts'
import type { VideoJsDocument } from './types.ts'

const PRESETS = ['presentation', 'product', 'data', 'showcase3d'] as const

interface PromptCardProps {
  document: VideoJsDocument
  locked: boolean
  busy: boolean
  error: string | null
  onCreate: (request: string) => void
  onAdjustVideo: (instruction: string) => void
  onFormat: (patch: Partial<Pick<VideoJsDocument, 'width' | 'height' | 'fps'>>) => void
}

const field = 'min-h-9 rounded-lg border border-border bg-bg-primary px-2 text-sm text-text-primary disabled:opacity-50'

export function VideoJsPromptCard({ document, locked, busy, error, onCreate, onAdjustVideo, onFormat }: PromptCardProps) {
  const { t } = useUiTranslation('videojs')
  const [request, setRequest] = useState('')
  const [instruction, setInstruction] = useState('')
  const disabled = locked || busy
  const adjust = () => {
    if (!instruction.trim()) return
    onAdjustVideo(instruction.trim())
    setInstruction('')
  }
  return (
    <aside className="flex flex-col gap-4 rounded-xl border border-border bg-bg-secondary p-3" aria-label={t('prompt.region')}>
      <div className="flex flex-col gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary"><WandSparkles size={16} />{t('prompt.createTitle')}</h2>
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map(preset => (
            <button key={preset} type="button" disabled={disabled} onClick={() => setRequest(t(`presets.${preset}.request`))}
              className="rounded-full border border-border px-2.5 py-1 text-xs text-text-secondary hover:bg-bg-hover hover:text-text-primary disabled:opacity-40">
              {t(`presets.${preset}.label`)}
            </button>
          ))}
        </div>
        <textarea value={request} onChange={event => setRequest(event.target.value)} disabled={disabled} rows={6} maxLength={20_000}
          placeholder={t('prompt.createPlaceholder')} aria-label={t('prompt.createLabel')}
          className="w-full resize-y rounded-lg border border-border bg-bg-primary p-2 text-sm text-text-primary disabled:opacity-50" />
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 text-xs text-text-muted">{t('prompt.format')}
            <select className={field} value={videoJsFormatOf(document)} disabled={disabled}
              onChange={event => onFormat(VIDEOJS_FORMATS[event.target.value as VideoJsFormat])}>
              {(Object.keys(VIDEOJS_FORMATS) as VideoJsFormat[]).map(format => <option key={format} value={format}>{t(`formats.${format}`)}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-text-muted">{t('prompt.fps')}
            <select className={field} value={document.fps} disabled={disabled} onChange={event => onFormat({ fps: Number(event.target.value) === 60 ? 60 : 30 })}>
              <option value={30}>30</option><option value={60}>60</option>
            </select>
          </label>
        </div>
        <button type="button" disabled={disabled || !request.trim()} onClick={() => onCreate(request.trim())}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-accent-blue px-3 text-sm font-semibold text-white disabled:opacity-40">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}{t('prompt.create')}
        </button>
        <p className="text-xs text-text-muted">{t('prompt.createHelp')}</p>
      </div>
      <div className="flex flex-col gap-2 border-t border-border pt-3">
        <h2 className="text-sm font-semibold text-text-primary">{t('prompt.adjustTitle')}</h2>
        <textarea value={instruction} onChange={event => setInstruction(event.target.value)} disabled={disabled || !document.scenes.length} rows={3}
          placeholder={t('prompt.adjustPlaceholder')} aria-label={t('prompt.adjustLabel')}
          className="w-full resize-y rounded-lg border border-border bg-bg-primary p-2 text-sm text-text-primary disabled:opacity-50" />
        <button type="button" disabled={disabled || !instruction.trim()} onClick={adjust}
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-accent-blue/60 px-3 text-xs font-semibold text-text-primary hover:bg-accent-blue/10 disabled:opacity-40">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}{t('prompt.adjust')}
        </button>
      </div>
      {busy && <p role="status" className="text-xs text-text-secondary">{t('prompt.working')}</p>}
      {error && <p role="alert" className="rounded-lg border border-red-500/40 bg-red-950/40 p-2 text-xs text-red-100">{error}</p>}
    </aside>
  )
}
