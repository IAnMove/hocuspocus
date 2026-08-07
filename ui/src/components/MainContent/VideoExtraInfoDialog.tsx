import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { BadgeInfo, Check, Copy, Languages, Loader2, MessageSquareText, RefreshCw, Sparkles, X, Youtube } from 'lucide-react'
import { fetchVideoExtraInfo, generateVideoExtraInfo } from '../../api/client'
import type { VideoExtraInfo, VideoExtraInfoStatus } from '../../types'

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
      title={`Copy ${label}`}
    >
      {copied ? <Check size={11} className="text-accent-green" /> : <Copy size={11} />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

export function VideoExtraInfoDialog({ name, onClose }: { name: string; onClose: () => void }) {
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
        if (active) setError(reason instanceof Error ? reason.message : 'Failed to load extra info')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [language, name])

  const generate = async () => {
    if (generating) return
    setGenerating(true)
    setError(null)
    try {
      const result = await generateVideoExtraInfo(name, language, !!data)
      setData(result.data)
      setStatus(previous => previous ? { ...previous, available: true, data: result.data } : previous)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Failed to generate extra info')
    } finally {
      setGenerating(false)
    }
  }

  const allCopy = data
    ? `${data.overview}\n\nYouTube\n${data.youtube.title}\n\n${data.youtube.description}\n\nX.com\n${data.x.post}`
    : ''

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
            <h2 id="video-extra-info-title" className="text-sm font-semibold text-text-primary">Extra info</h2>
            <p className="mt-1 truncate text-[11px] text-text-muted" title={name}>{name}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={generating}
            className="rounded-lg p-1.5 text-text-muted hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
            title={generating ? 'Wait for generation to finish' : 'Close'}
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex items-center gap-3 border-b border-border px-5 py-3">
          <Languages size={14} className="shrink-0 text-text-muted" />
          <label htmlFor="extra-info-language" className="text-xs text-text-secondary">Language</label>
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
              {status.prompt_count} saved prompt{status.prompt_count === 1 ? '' : 's'}
              {status.director_context ? ' · Director production context' : ''}
            </span>
          )}
        </div>

        <div className="min-h-[260px] flex-1 overflow-y-auto px-5 py-4">
          <div className="mb-4 rounded-lg border border-border bg-bg-tertiary/60 px-3 py-2 text-[11px] leading-relaxed text-text-muted">
            This is written from the prompts and production properties already saved with the video. The media is not re-analysed.
          </div>

          {(loading || generating) && !data && (
            <div className="flex min-h-[190px] flex-col items-center justify-center gap-3 text-text-muted">
              <Loader2 size={22} className="animate-spin text-accent-blue" />
              <span className="text-xs">{generating ? 'Writing platform copy…' : 'Checking saved extra info…'}</span>
            </div>
          )}

          {error && (
            <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</div>
          )}

          {!loading && !data && !generating && (
            <div className="flex min-h-[180px] flex-col items-center justify-center gap-3 text-center">
              <Sparkles size={24} className="text-accent-blue" />
              <div>
                <p className="text-sm text-text-primary">No copy saved in this language yet</p>
                <p className="mt-1 text-[11px] text-text-muted">Generate a summary, YouTube metadata, and an x.com post.</p>
              </div>
              <button
                type="button"
                onClick={generate}
                className="mt-1 inline-flex items-center gap-1.5 rounded-lg bg-accent-blue px-4 py-2 text-xs text-white hover:bg-accent-blue-hover"
              >
                <Sparkles size={13} /> Generate
              </button>
            </div>
          )}

          {data && (
            <div className={`space-y-4 ${generating ? 'opacity-60' : ''}`}>
              <section className="rounded-lg border border-border bg-bg-tertiary/40 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="flex items-center gap-1.5 text-xs font-medium text-text-primary"><BadgeInfo size={13} /> What the video is</h3>
                  <CopyButton value={data.overview} label="overview" />
                </div>
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{data.overview}</p>
              </section>

              <section className="rounded-lg border border-border bg-bg-tertiary/40 p-3">
                <div className="mb-2 flex items-center gap-1.5">
                  <Youtube size={14} className="text-red-400" />
                  <h3 className="text-xs font-medium text-text-primary">YouTube</h3>
                </div>
                <div className="mb-3 rounded-md bg-bg-primary/50 p-2.5">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[10px] uppercase tracking-wider text-text-muted">Optimized title · {data.youtube.title.length}/100</span>
                    <CopyButton value={data.youtube.title} label="YouTube title" />
                  </div>
                  <p className="text-sm font-medium text-text-primary">{data.youtube.title}</p>
                </div>
                <div className="rounded-md bg-bg-primary/50 p-2.5">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[10px] uppercase tracking-wider text-text-muted">Optimized description</span>
                    <CopyButton value={data.youtube.description} label="YouTube description" />
                  </div>
                  <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{data.youtube.description}</p>
                </div>
              </section>

              <section className="rounded-lg border border-border bg-bg-tertiary/40 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="flex items-center gap-1.5 text-xs font-medium text-text-primary"><MessageSquareText size={13} /> X.com · {data.x.post.length}/280</h3>
                  <CopyButton value={data.x.post} label="x.com post" />
                </div>
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{data.x.post}</p>
              </section>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          {data && <CopyButton value={allCopy} label="all extra info" />}
          <button
            type="button"
            onClick={onClose}
            disabled={generating}
            className="rounded-lg border border-border px-3 py-2 text-xs text-text-secondary hover:border-border-light hover:text-text-primary disabled:opacity-40"
          >
            Close
          </button>
          {data && (
            <button
              type="button"
              onClick={generate}
              disabled={generating}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-blue px-3 py-2 text-xs text-white hover:bg-accent-blue-hover disabled:opacity-50"
            >
              {generating ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              {generating ? 'Generating…' : 'Regenerate'}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
