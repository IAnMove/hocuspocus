import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, ClipboardCopy, Loader2, ShieldAlert } from 'lucide-react'
import { fetchOutputMetadata, fetchOutputs } from '../../api/client'
import type { ApiOutput } from '../../api/client'
import { useStore } from '../../stores/useStore'
import { formatFailedPromptDump, promptFromMetadata, type AuditFailedClip } from './auditClipboard'

const FLAGS_KEY = 'maestro-auditdev-flags-v1'

type FlagMap = Record<string, boolean>

function loadFlags(): FlagMap {
  try {
    const raw = localStorage.getItem(FLAGS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as FlagMap
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function saveFlags(flags: FlagMap) {
  localStorage.setItem(FLAGS_KEY, JSON.stringify(flags))
}

export function AuditDevPanel() {
  const workspace = useStore(s => s.activeWorkspace)
  const [outputs, setOutputs] = useState<ApiOutput[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [flags, setFlags] = useState<FlagMap>(() => loadFlags())
  const [prompts, setPrompts] = useState<Record<string, string>>({})
  const [jobIds, setJobIds] = useState<Record<string, string>>({})
  const [onlyMarked, setOnlyMarked] = useState(false)
  const [copied, setCopied] = useState(false)
  const [loadingMeta, setLoadingMeta] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchOutputs(0, 0, { workspace, mediaType: 'video' })
      .then(result => {
        if (cancelled) return
        setOutputs(result.outputs)
        setError('')
      })
      .catch(err => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [workspace])

  const visible = useMemo(
    () => (onlyMarked ? outputs.filter(item => flags[item.name]) : outputs),
    [outputs, flags, onlyMarked],
  )
  const markedCount = useMemo(
    () => outputs.reduce((count, item) => count + (flags[item.name] ? 1 : 0), 0),
    [outputs, flags],
  )

  const toggle = (name: string) => {
    setFlags(current => {
      const next = { ...current, [name]: !current[name] }
      if (!next[name]) delete next[name]
      saveFlags(next)
      return next
    })
  }

  const ensurePrompt = useCallback(async (name: string) => {
    if (prompts[name] !== undefined) return
    setLoadingMeta(name)
    try {
      const meta = await fetchOutputMetadata(name, workspace)
      const prompt = promptFromMetadata(meta)
      const jobId = typeof meta.job_id === 'string' ? meta.job_id : ''
      setPrompts(current => ({ ...current, [name]: prompt }))
      setJobIds(current => ({ ...current, [name]: jobId }))
    } catch {
      setPrompts(current => ({ ...current, [name]: '(failed to load metadata)' }))
    } finally {
      setLoadingMeta(current => (current === name ? null : current))
    }
  }, [prompts, workspace])

  const copyFailed = async () => {
    const marked = outputs.filter(item => flags[item.name])
    for (const item of marked) {
      if (prompts[item.name] === undefined) await ensurePrompt(item.name)
    }
    const payload: AuditFailedClip[] = marked.map(item => ({
      name: item.name,
      jobId: jobIds[item.name],
      prompt: prompts[item.name] || '',
    }))
    const text = formatFailedPromptDump(payload)
    await navigator.clipboard.writeText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2">
        <ShieldAlert size={16} className="shrink-0 text-amber-300" />
        <div className="min-w-0 flex-1 text-xs text-amber-100">
          Auditoría interna: marca los clips con alucinación de audio. Copia los prompts
          fallidos y pégalos en el chat para iterar el generador.
        </div>
        <label className="flex items-center gap-1 text-[11px] text-amber-100">
          <input
            type="checkbox"
            checked={onlyMarked}
            onChange={event => setOnlyMarked(event.target.checked)}
          />
          Solo marcados
        </label>
        <button
          type="button"
          onClick={() => void copyFailed()}
          disabled={markedCount === 0}
          className="inline-flex items-center gap-1 rounded-md border border-amber-400/40 bg-amber-500/20 px-2.5 py-1 text-[11px] font-medium text-amber-100 hover:bg-amber-500/30 disabled:opacity-40"
        >
          {copied ? <Check size={12} /> : <ClipboardCopy size={12} />}
          {copied ? 'Copiado' : `Copiar prompts erróneos (${markedCount})`}
        </button>
      </div>

      {loading ? (
        <div className="flex flex-1 items-center justify-center text-text-muted">
          <Loader2 size={18} className="animate-spin" />
          <span className="ml-2 text-xs">Cargando vídeos…</span>
        </div>
      ) : error ? (
        <p className="text-xs text-red-400">{error}</p>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto space-y-3 pr-1">
          {visible.map(item => (
            <article
              key={item.name}
              className={`rounded-lg border bg-bg-secondary p-2 ${
                flags[item.name] ? 'border-red-400/60' : 'border-border'
              }`}
            >
              <div className="grid gap-2 md:grid-cols-[220px_1fr]">
                <video
                  src={item.url}
                  controls
                  preload="metadata"
                  className="h-40 w-full rounded bg-black object-contain"
                  onPlay={() => void ensurePrompt(item.name)}
                />
                <div className="flex min-w-0 flex-col gap-2">
                  <div className="flex items-start justify-between gap-2">
                    <p className="truncate text-[11px] text-text-secondary" title={item.name}>
                      {item.name}
                    </p>
                    <label className="flex shrink-0 items-center gap-1 text-[11px] text-red-200">
                      <input
                        type="checkbox"
                        checked={Boolean(flags[item.name])}
                        onChange={() => {
                          toggle(item.name)
                          void ensurePrompt(item.name)
                        }}
                      />
                      Audio mal
                    </label>
                  </div>
                  <button
                    type="button"
                    className="self-start text-[10px] text-accent-blue hover:underline"
                    onClick={() => void ensurePrompt(item.name)}
                  >
                    {prompts[item.name] !== undefined ? 'Prompt cargado' : 'Cargar prompt'}
                  </button>
                  <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-bg-tertiary p-2 text-[10px] text-text-muted">
                    {loadingMeta === item.name
                      ? 'Cargando…'
                      : prompts[item.name] !== undefined
                        ? prompts[item.name] || '(sin prompt en metadata)'
                        : 'Pulsa para cargar el prompt.'}
                  </pre>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
