import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, Music2, Trash2, X } from 'lucide-react'
import {
  attachAlternativeSong,
  fetchAlternativeSongs,
  fetchOutputs,
  fetchVideoEditorExport,
  mountAlternativeSong,
  deleteAlternativeSong,
  type AlternativeSong,
  type AlternativeSongList,
  type ApiOutput,
} from '../../api/client'
import { useStore } from '../../stores/useStore'

export function canRemountVideoclip(file: { type: string }): boolean {
  return file.type === 'video'
}

function formatSeconds(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '—'
  const total = Math.round(value)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

export function AlternativeSongsDialog({ name, onClose }: { name: string; onClose: () => void }) {
  const workspace = useStore(s => s.activeWorkspace) || 'default'
  const loadOutputs = useStore(s => s.loadOutputs)
  const setMediaFilter = useStore(s => s.setMediaFilter)
  const [list, setList] = useState<AlternativeSongList | null>(null)
  const [audio, setAudio] = useState<ApiOutput[]>([])
  const [selectedAudio, setSelectedAudio] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const reload = async () => {
    const [songs, outputs] = await Promise.all([
      fetchAlternativeSongs(name, workspace),
      fetchOutputs(80, 0, { workspace, mediaType: 'audio' }),
    ])
    setList(songs)
    setAudio(outputs.outputs)
    if (!selectedAudio && outputs.outputs[0]) setSelectedAudio(outputs.outputs[0].name)
  }

  useEffect(() => {
    let cancelled = false
    reload().catch(reason => {
      if (!cancelled) setError((reason as Error).message)
    })
    return () => { cancelled = true }
  }, [name, workspace])

  useEffect(() => {
    const mounting = list?.songs.find(song => song.status === 'mounting' && song.job_id)
    if (!mounting?.job_id) return
    let cancelled = false
    const timer = window.setInterval(async () => {
      try {
        const job = await fetchVideoEditorExport(mounting.job_id as string)
        if (cancelled) return
        if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
          await reload()
          if (job.status === 'completed') await loadOutputs()
        }
      } catch {
        /* keep polling; the parent sidecar is the source of truth */
      }
    }, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [list, name, workspace])

  const run = async (label: string, work: () => Promise<void>) => {
    setBusy(label)
    setError(null)
    try {
      await work()
      await reload()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const attach = () => run('attach', async () => {
    if (!selectedAudio) throw new Error('Elige una canción de la galería de audio.')
    await attachAlternativeSong(name, selectedAudio, workspace)
  })

  const mount = (song: AlternativeSong) => run(`mount-${song.id}`, async () => {
    await mountAlternativeSong(name, song.id, { workspace })
  })

  const remove = (song: AlternativeSong) => run(`delete-${song.id}`, async () => {
    await deleteAlternativeSong(name, song.id, workspace)
  })

  const dialog = (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="alternative-songs-title"
        className="flex max-h-[82vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-border bg-bg-secondary shadow-2xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h2 id="alternative-songs-title" className="flex items-center gap-2 text-base font-semibold text-text-primary">
              <Music2 size={18} /> Canciones alternativas
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-text-muted">
              Reutiliza los planos de este videoclip. Si la canción es más corta se recorta el montaje;
              si es más larga se añaden planos aleatorios del mismo pool. No se regenera H3.
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-text-muted hover:bg-bg-hover" aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {list && (
            <p className="text-[11px] text-text-muted">
              {list.source_clip_count} {list.source_clip_count === 1 ? 'plano' : 'planos'} · videoclip {formatSeconds(list.duration_seconds)} · {
                list.adaptation === 'random_extras'
                  ? 'extras aleatorios si hace falta'
                  : 'si falta duración se repetirá el videoclip'
              }
            </p>
          )}

          <div className="flex gap-2">
            <select
              value={selectedAudio}
              onChange={event => setSelectedAudio(event.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-border bg-bg-tertiary px-2 py-2 text-xs text-text-primary"
            >
              <option value="">Elegir canción existente…</option>
              {audio.map(item => (
                <option key={item.name} value={item.name}>{item.name}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void attach()}
              disabled={!selectedAudio || busy !== null}
              className="shrink-0 rounded-lg bg-accent-blue px-3 py-2 text-xs font-medium text-white disabled:opacity-50"
            >
              {busy === 'attach' ? <Loader2 size={14} className="animate-spin" /> : 'Añadir'}
            </button>
          </div>

          {(list?.songs || []).length === 0 && (
            <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-[11px] text-text-muted">
              Aún no hay canciones alternativas. Añade un MP3/WAV de la galería Audio y luego pulsa Montar.
            </p>
          )}

          <div className="space-y-2">
            {(list?.songs || []).map(song => (
              <div key={song.id} className="rounded-xl border border-border bg-bg-tertiary px-3 py-2.5">
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="min-w-0 truncate font-medium text-text-secondary">{song.audio_name}</span>
                  <span className="ml-auto shrink-0 text-[10px] text-text-muted">{formatSeconds(song.duration_seconds)}</span>
                </div>
                <p className="mt-1 text-[10px] text-text-muted">
                  {song.status === 'mounted' && song.mounted_output
                    ? `Montado · ${song.mounted_output}${song.extra_clip_count ? ` · +${song.extra_clip_count} extras` : ''}`
                    : song.status === 'mounting'
                      ? 'Montando con FFmpeg…'
                      : song.status === 'failed'
                        ? 'Falló el montaje'
                        : 'Lista para montar'}
                </p>
                <div className="mt-2 flex gap-2">
                  {song.mounted_output ? (
                    <button
                      type="button"
                      className="rounded-md border border-border px-2 py-1 text-[10px] text-text-secondary hover:bg-bg-hover"
                      onClick={() => { setMediaFilter('videoclips'); onClose() }}
                    >
                      Ver resultado
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy !== null || song.status === 'mounting'}
                      onClick={() => void mount(song)}
                      className="rounded-md bg-accent-blue px-2 py-1 text-[10px] font-medium text-white disabled:opacity-50"
                    >
                      {busy === `mount-${song.id}` || song.status === 'mounting'
                        ? <Loader2 size={12} className="animate-spin" />
                        : 'Montar'}
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy !== null || song.status === 'mounting'}
                    onClick={() => void remove(song)}
                    className="ml-auto rounded-md p-1 text-text-muted hover:bg-red-500/10 hover:text-red-400 disabled:opacity-40"
                    title="Quitar de la lista (no borra el archivo de audio)"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {error && <p className="rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</p>}
        </div>
      </div>
    </div>
  )

  return createPortal(dialog, document.body)
}
