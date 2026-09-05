import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { TFunction } from 'i18next'
import { BadgeInfo, CalendarDays, Check, Clock3, Copy, FileVideo2, Languages, Loader2, MessageSquareText, RefreshCw, SlidersHorizontal, Sparkles, X, Youtube } from 'lucide-react'
import { fetchVideoExtraInfo, generateVideoExtraInfo } from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { formatGenerationBreakdown, formatGenerationDuration } from '../../lib/generationTiming'
import type { VideoClipInfo, VideoExtraInfo, VideoExtraInfoStatus } from '../../types'

const LANGUAGES = [
  ['es', 'Español'],
  ['en', 'English'],
  ['ca', 'Català'],
  ['fr', 'Français'],
  ['de', 'Deutsch'],
  ['it', 'Italiano'],
  ['pt', 'Português'],
  ['ja', '日本語'],
  ['ko', '한국어'],
  ['zh', '简体中文'],
] as const

function initialLanguage() {
  try {
    const saved = localStorage.getItem('maestro-extra-info-language')
    if (saved && LANGUAGES.some(([code]) => code === saved)) return saved
  } catch {
    // Storage can be unavailable in hardened/private browser contexts.
  }
  const browserLanguage = navigator.language?.toLowerCase().split('-')[0]
  return LANGUAGES.some(([code]) => code === browserLanguage) ? browserLanguage : 'es'
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return
    } catch {
      // Fall through to the secure-context compatible legacy path.
    }
  }
  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const { t } = useUiTranslation('extraInfo')
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await copyText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-text-muted hover:bg-bg-hover hover:text-text-primary transition-colors"
      title={t('copy.title', { label })}
    >
      {copied ? <Check size={11} className="text-accent-green" /> : <Copy size={11} />}
      {copied ? t('copy.copied') : t('copy.action')}
    </button>
  )
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`
}

function formatDate(timestamp: number | null) {
  if (timestamp == null || !Number.isFinite(timestamp) || timestamp <= 0) return ''
  return new Date(timestamp * 1000).toLocaleString()
}

function clipInfoAsText(clip: VideoClipInfo, t: TFunction<'extraInfo'>) {
  const breakdown = formatGenerationBreakdown(clip.generation_timings)
  const lines = [
    t('clip.title').toUpperCase(),
    `${t('clip.file')}: ${clip.name}`,
    clip.created_at ? `${t('clip.generated')}: ${formatDate(clip.created_at)}` : '',
    clip.file_size_bytes ? `${t('clip.fileSize')}: ${formatBytes(clip.file_size_bytes)}` : '',
    clip.generation_time_sec != null ? `${t('clip.generationTime')}: ${formatGenerationDuration(clip.generation_time_sec)}` : '',
    breakdown ? `${t('clip.timingBreakdown')}: ${breakdown}` : '',
    clip.model_type ? `${t('clip.model')}: ${clip.model_type}` : '',
    clip.resolution ? `${t('clip.resolution')}: ${clip.resolution}` : '',
    clip.video_length_frames != null ? `${t('clip.frames')}: ${clip.video_length_frames}` : '',
    clip.num_inference_steps != null ? `${t('clip.inferenceSteps')}: ${clip.num_inference_steps}` : '',
    clip.guidance_scale != null ? `${t('clip.guidance')}: ${clip.guidance_scale}` : '',
    clip.seed != null ? `${t('clip.seed')}: ${clip.seed}` : '',
    clip.job_id ? `${t('clip.jobId')}: ${clip.job_id}` : '',
    clip.prompt ? `\n${t('clip.prompt').toUpperCase()}\n${clip.prompt}` : '',
    clip.audio_prompt ? `\n${t('clip.audioPrompt').toUpperCase()}\n${clip.audio_prompt}` : '',
    clip.negative_prompt ? `\n${t('clip.negativePrompt').toUpperCase()}\n${clip.negative_prompt}` : '',
    `\n${t('clip.allSavedMetadata').toUpperCase()}\n${JSON.stringify(clip.saved_metadata, null, 2)}`,
  ]
  return lines.filter(Boolean).join('\n')
}

export function VideoExtraInfoDialog({ name, onClose }: { name: string; onClose: () => void }) {
  const { t: tActivity } = useUiTranslation('activity')
  const { t } = useUiTranslation('extraInfo')
  const { t: tCommon } = useUiTranslation('common')
  const [language, setLanguage] = useState(initialLanguage)
  const [status, setStatus] = useState<VideoExtraInfoStatus | null>(null)
  const [data, setData] = useState<VideoExtraInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !generating) onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [generating, onClose])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    setData(null)
    try {
      localStorage.setItem('maestro-extra-info-language', language)
    } catch {
      // The selection still works for this session.
    }
    fetchVideoExtraInfo(name, language)
      .then(result => {
        if (!active) return
        setStatus(result)
        setData(result.data)
      })
      .catch(reason => {
        if (active) setError(reason instanceof Error ? reason.message : t('errors.loadFailed'))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [language, name, t])

  const generate = async () => {
    if (generating) return
    setGenerating(true)
    setError(null)
    try {
      const result = await generateVideoExtraInfo(name, language, !!data)
      setData(result.data)
      setStatus(previous => previous ? { ...previous, available: true, data: result.data } : previous)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('errors.generateFailed'))
    } finally {
      setGenerating(false)
    }
  }

  const clip = status?.clip || null
  const clipCopy = clip ? clipInfoAsText(clip, t) : ''
  const publishingCopy = data
    ? `${t('publishing.heading').toUpperCase()}\n${data.overview}\n\n${t('publishing.youtube')}\n${data.youtube.title}\n\n${data.youtube.description}\n\n${t('publishing.xCom')}\n${data.x.post}`
    : ''
  const allCopy = [clipCopy, publishingCopy].filter(Boolean).join('\n\n')
  const generationBreakdown = clip ? formatGenerationBreakdown(clip.generation_timings) : ''
  const savedMetadata = clip ? JSON.stringify(clip.saved_metadata, null, 2) : ''

  return createPortal(
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-black/70 p-4"
      onClick={() => { if (!generating) onClose() }}
      role="presentation"
    >
      <div
        className="flex max-h-[92vh] w-[720px] max-w-[96vw] flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl"
        onClick={event => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="video-extra-info-title"
      >
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="mt-0.5 rounded-lg bg-accent-blue/15 p-2 text-accent-blue">
            <BadgeInfo size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="video-extra-info-title" className="text-sm font-semibold text-text-primary">{tActivity('extraInfo')}</h2>
            <p className="mt-1 truncate text-[11px] text-text-muted" title={name}>{name}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={generating}
            className="rounded-lg p-1.5 text-text-muted hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
            title={generating ? t('waitForGeneration') : tCommon('actions.close')}
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex items-center gap-3 border-b border-border px-5 py-3">
          <Languages size={14} className="shrink-0 text-text-muted" />
          <label htmlFor="extra-info-language" className="text-xs text-text-secondary">{t('language')}</label>
          <select
            id="extra-info-language"
            value={language}
            onChange={event => setLanguage(event.target.value)}
            disabled={generating}
            className="rounded-lg border border-border bg-bg-tertiary px-3 py-1.5 text-xs text-text-primary focus:border-accent-blue focus:outline-none disabled:opacity-50"
          >
            {LANGUAGES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
          {status && (
            <span className="ml-auto text-[10px] text-text-muted">
              {t('savedPrompts', { count: status.prompt_count })}
              {status.director_context ? ` · ${t('directorContext')}` : ''}
            </span>
          )}
        </div>

        <div className="min-h-[260px] flex-1 overflow-y-auto px-5 py-4">
          <div className="mb-4 rounded-lg border border-border bg-bg-tertiary/60 px-3 py-2 text-[11px] leading-relaxed text-text-muted">
            {t('intro')}
          </div>

          {clip && (
            <section className="mb-4 space-y-3 rounded-lg border border-accent-blue/25 bg-accent-blue/5 p-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="flex items-center gap-1.5 text-xs font-medium text-text-primary">
                  <FileVideo2 size={14} className="text-accent-blue" /> {t('clip.title')}
                </h3>
                <CopyButton value={clipCopy} label={t('copy.clipInformation')} />
              </div>

              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {clip.created_at != null && (
                  <div className="rounded-md bg-bg-primary/50 p-2">
                    <div className="mb-1 flex items-center gap-1 text-[9px] uppercase tracking-wider text-text-muted"><CalendarDays size={10} /> {t('clip.generated')}</div>
                    <div className="text-[11px] text-text-primary">{formatDate(clip.created_at)}</div>
                  </div>
                )}
                {clip.generation_time_sec != null && (
                  <div className="rounded-md bg-bg-primary/50 p-2">
                    <div className="mb-1 flex items-center gap-1 text-[9px] uppercase tracking-wider text-text-muted"><Clock3 size={10} /> {t('clip.generationTime')}</div>
                    <div className="text-[11px] text-text-primary">{formatGenerationDuration(clip.generation_time_sec)}</div>
                  </div>
                )}
                {clip.file_size_bytes > 0 && (
                  <div className="rounded-md bg-bg-primary/50 p-2">
                    <div className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">{t('clip.fileSize')}</div>
                    <div className="text-[11px] text-text-primary">{formatBytes(clip.file_size_bytes)}</div>
                  </div>
                )}
                {clip.model_type && (
                  <div className="rounded-md bg-bg-primary/50 p-2">
                    <div className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">{t('clip.model')}</div>
                    <div className="break-words text-[11px] text-text-primary">{clip.model_type}</div>
                  </div>
                )}
                {clip.resolution && (
                  <div className="rounded-md bg-bg-primary/50 p-2">
                    <div className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">{t('clip.resolution')}</div>
                    <div className="text-[11px] text-text-primary">{clip.resolution}</div>
                  </div>
                )}
                {clip.video_length_frames != null && (
                  <div className="rounded-md bg-bg-primary/50 p-2">
                    <div className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">{t('clip.frames')}</div>
                    <div className="text-[11px] text-text-primary">{String(clip.video_length_frames)}</div>
                  </div>
                )}
                {clip.num_inference_steps != null && (
                  <div className="rounded-md bg-bg-primary/50 p-2">
                    <div className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">{t('clip.inferenceSteps')}</div>
                    <div className="text-[11px] text-text-primary">{String(clip.num_inference_steps)}</div>
                  </div>
                )}
                {clip.seed != null && (
                  <div className="rounded-md bg-bg-primary/50 p-2">
                    <div className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">{t('clip.seed')}</div>
                    <div className="break-all text-[11px] text-text-primary">{String(clip.seed)}</div>
                  </div>
                )}
                {clip.job_id && (
                  <div className="rounded-md bg-bg-primary/50 p-2">
                    <div className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">{t('clip.jobId')}</div>
                    <div className="break-all text-[11px] text-text-primary">{clip.job_id}</div>
                  </div>
                )}
              </div>

              {generationBreakdown && (
                <div className="rounded-md bg-bg-primary/50 px-2.5 py-2 text-[10px] text-text-muted">
                  <span className="font-medium text-text-secondary">{t('clip.timingBreakdown')}:</span> {generationBreakdown}
                </div>
              )}

              <div className="rounded-md bg-bg-primary/50 p-2.5">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-text-muted">{t('clip.generationPrompt')}</span>
                  {clip.prompt && <CopyButton value={clip.prompt} label={t('copy.generationPrompt')} />}
                </div>
                <p className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-text-secondary">
                  {clip.prompt || t('clip.noPrompt')}
                </p>
              </div>

              {clip.audio_prompt && (
                <div className="rounded-md bg-bg-primary/50 p-2.5">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-[10px] uppercase tracking-wider text-text-muted">{t('clip.audioPrompt')}</span>
                    <CopyButton value={clip.audio_prompt} label={t('copy.audioPrompt')} />
                  </div>
                  <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-text-secondary">{clip.audio_prompt}</p>
                </div>
              )}

              {clip.negative_prompt && (
                <div className="rounded-md bg-bg-primary/50 p-2.5">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-[10px] uppercase tracking-wider text-text-muted">{t('clip.negativePrompt')}</span>
                    <CopyButton value={clip.negative_prompt} label={t('copy.negativePrompt')} />
                  </div>
                  <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-text-secondary">{clip.negative_prompt}</p>
                </div>
              )}

              <details className="rounded-md bg-bg-primary/50 p-2.5">
                <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-muted hover:text-text-secondary">
                  <SlidersHorizontal size={11} /> {t('clip.allSavedSettings')}
                </summary>
                <div className="mt-2 flex justify-end"><CopyButton value={savedMetadata} label={t('copy.allSavedSettings')} /></div>
                <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-black/20 p-2 text-[10px] leading-relaxed text-text-muted">{savedMetadata}</pre>
              </details>
            </section>
          )}

          {(loading || generating) && !data && (
            <div className="flex min-h-[190px] flex-col items-center justify-center gap-3 text-text-muted">
              <Loader2 size={22} className="animate-spin text-accent-blue" />
              <span className="text-xs">{generating ? t('status.writing') : t('status.checking')}</span>
            </div>
          )}

          {error && (
            <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</div>
          )}

          {!loading && !data && !generating && (
            <div className="flex min-h-[180px] flex-col items-center justify-center gap-3 text-center">
              <Sparkles size={24} className="text-accent-blue" />
              <div>
                <p className="text-sm text-text-primary">{t('empty.title')}</p>
                <p className="mt-1 text-[11px] text-text-muted">{t('empty.hint')}</p>
              </div>
              <button
                type="button"
                onClick={generate}
                className="mt-1 inline-flex items-center gap-1.5 rounded-lg bg-accent-blue px-4 py-2 text-xs text-white hover:bg-accent-blue-hover"
              >
                <Sparkles size={13} /> {t('empty.generate')}
              </button>
            </div>
          )}

          {data && (
            <div className={`space-y-4 ${generating ? 'opacity-60' : ''}`}>
              <section className="rounded-lg border border-border bg-bg-tertiary/40 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="flex items-center gap-1.5 text-xs font-medium text-text-primary"><BadgeInfo size={13} /> {t('publishing.overview')}</h3>
                  <CopyButton value={data.overview} label={t('copy.overview')} />
                </div>
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{data.overview}</p>
              </section>

              <section className="rounded-lg border border-border bg-bg-tertiary/40 p-3">
                <div className="mb-2 flex items-center gap-1.5">
                  <Youtube size={14} className="text-red-400" />
                  <h3 className="text-xs font-medium text-text-primary">{t('publishing.youtube')}</h3>
                </div>
                <div className="mb-3 rounded-md bg-bg-primary/50 p-2.5">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[10px] uppercase tracking-wider text-text-muted">{t('publishing.optimizedTitle', { length: data.youtube.title.length })}</span>
                    <CopyButton value={data.youtube.title} label={t('copy.youtubeTitle')} />
                  </div>
                  <p className="text-sm font-medium text-text-primary">{data.youtube.title}</p>
                </div>
                <div className="rounded-md bg-bg-primary/50 p-2.5">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[10px] uppercase tracking-wider text-text-muted">{t('publishing.optimizedDescription')}</span>
                    <CopyButton value={data.youtube.description} label={t('copy.youtubeDescription')} />
                  </div>
                  <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{data.youtube.description}</p>
                </div>
              </section>

              <section className="rounded-lg border border-border bg-bg-tertiary/40 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="flex items-center gap-1.5 text-xs font-medium text-text-primary"><MessageSquareText size={13} /> {t('publishing.xPost', { length: data.x.post.length })}</h3>
                  <CopyButton value={data.x.post} label={t('copy.xPost')} />
                </div>
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{data.x.post}</p>
              </section>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          {allCopy && <CopyButton value={allCopy} label={t('copy.allExtraInfo')} />}
          <button
            type="button"
            onClick={onClose}
            disabled={generating}
            className="rounded-lg border border-border px-3 py-2 text-xs text-text-secondary hover:border-border-light hover:text-text-primary disabled:opacity-40"
          >
            {tCommon('actions.close')}
          </button>
          {data && (
            <button
              type="button"
              onClick={generate}
              disabled={generating}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-blue px-3 py-2 text-xs text-white hover:bg-accent-blue-hover disabled:opacity-50"
            >
              {generating ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              {generating ? t('actions.generating') : t('actions.regenerate')}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
