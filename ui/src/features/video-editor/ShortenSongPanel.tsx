import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { shortenSong, type SongShortenResult } from '../../api/audio'
import type { EditorClip } from './editorClipNormalization'
import type { EditorSoundtrack, ResolutionOption } from './editorDraft'
import { montageFromEditor, type MontageLayers } from './montage'

type Range = [number, number]

function asRanges(value: SongShortenResult['keep']): Range[] {
  return (value || []).map(item => [Number(item[0]), Number(item[1])])
}

function applyClipTrims(current: EditorClip[], remapped: NonNullable<SongShortenResult['montage']>['clips']): EditorClip[] {
  const byId = new Map(current.map(clip => [clip.id, clip]))
  return remapped.flatMap(clip => {
    const base = byId.get(clip.id) || byId.get(clip.id.replace(/-keep-\d+$/, ''))
    if (!base) return []
    return [{ ...base, id: clip.id, trimStart: clip.trimStart, trimEnd: clip.trimEnd }]
  })
}

export function ShortenSongPanel({
  workspace,
  soundtrack,
  clips,
  layers,
  projectName,
  resolution,
  fps,
  onApply,
  onError,
  request = shortenSong,
}: {
  workspace: string
  soundtrack: EditorSoundtrack | null
  clips: EditorClip[]
  layers: MontageLayers
  projectName: string
  resolution: ResolutionOption
  fps: number
  onApply: (next: { soundtrack: EditorSoundtrack; clips: EditorClip[]; layers: MontageLayers; report: string }) => void
  onError: (message: string) => void
  request?: typeof shortenSong
}) {
  const { t } = useUiTranslation('videoEditor')
  const [seconds, setSeconds] = useState(180)
  const [ranges, setRanges] = useState<Range[]>([])
  const [preview, setPreview] = useState<SongShortenResult['time_map']>([])
  const [busy, setBusy] = useState(false)
  if (!soundtrack) return null
  const duration = Math.max(soundtrack.duration, 0.1)
  const document = () => montageFromEditor({ projectName, resolution, fps, clips, soundtrack, layers })
  const run = (previewOnly: boolean, keep?: Range[]) => {
    setBusy(true)
    request({
      workspace,
      source: soundtrack.source,
      durationMax: seconds,
      preview: previewOnly,
      ...(keep ? { keep } : {}),
      ...(!previewOnly && keep ? { montage: document() } : {}),
    }).then(result => {
      if (result.keep) setRanges(asRanges(result.keep))
      setPreview(result.time_map || [])
      if (!previewOnly && result.file && result.url && result.montage) {
        const dropped = result.report?.dropped?.length || 0
        const trimmed = result.report?.trimmed?.length || 0
        onApply({
          soundtrack: {
            ...soundtrack,
            source: `${result.url}?workspace=${encodeURIComponent(workspace)}`,
            duration: result.duration || soundtrack.duration,
            trimStart: 0,
            trimEnd: result.duration || soundtrack.duration,
          },
          clips: applyClipTrims(clips, result.montage.clips),
          layers: { overlays: result.montage.overlays as MontageLayers['overlays'], audioCues: result.montage.audioCues as MontageLayers['audioCues'], duck: layers.duck },
          report: dropped || trimmed ? t('toolbar.shortenReport', { dropped, trimmed }) : '',
        })
      }
    }).catch(reason => onError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setBusy(false))
  }
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <button
        type="button"
        disabled={busy}
        title={t('toolbar.shortenTitle')}
        onClick={() => run(true)}
        className="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary hover:bg-bg-hover disabled:opacity-40"
      >
        {busy ? t('toolbar.shortenWorking') : t('toolbar.shorten', { seconds })}
      </button>
      {ranges.length > 0 && (
        <div className="w-56 rounded border border-border bg-bg-secondary p-1">
          <div className="relative mb-1 h-6 overflow-hidden rounded bg-black/50" aria-label={t('toolbar.shortenTitle')}>
            {ranges.map(range => (
              <span
                key={`${range[0]}-${range[1]}`}
                className="absolute inset-y-1 rounded-sm bg-accent-blue/80"
                style={{ left: `${(range[0] / duration) * 100}%`, width: `${Math.max((range[1] - range[0]) / duration * 100, 1)}%` }}
              />
            ))}
          </div>
          {ranges.map((range, index) => (
            <label key={index} className="mb-1 flex items-center gap-1 text-[10px] text-text-muted">
              <input type="number" step={0.1} value={range[0]} aria-label={`${index} start`}
                onChange={event => setRanges(current => current.map((item, itemIndex) => itemIndex === index ? [Number(event.target.value), item[1]] : item))}
                className="w-14 rounded border border-border bg-bg-tertiary px-1" />
              <input type="number" step={0.1} value={range[1]} aria-label={`${index} end`}
                onChange={event => setRanges(current => current.map((item, itemIndex) => itemIndex === index ? [item[0], Number(event.target.value)] : item))}
                className="w-14 rounded border border-border bg-bg-tertiary px-1" />
            </label>
          ))}
          <div className="flex gap-1">
            <button type="button" className="text-[10px] text-text-secondary" onClick={() => run(true, ranges)}>{t('toolbar.shortenPreview')}</button>
            <button type="button" className="text-[10px] text-accent-blue" onClick={() => run(false, ranges)}>{t('toolbar.shortenApply')}</button>
          </div>
          {preview?.map((cut, index) => (
            <p key={index} className="text-[9px] text-text-muted">{t('toolbar.shortenCut', { index: index + 1, at: Number(cut[1]).toFixed(2), seconds: Number(cut[2]).toFixed(2) })}</p>
          ))}
        </div>
      )}
      <label className="sr-only">
        {t('toolbar.shorten', { seconds })}
        <input type="number" min={1} max={3600} value={seconds} onChange={event => setSeconds(Number(event.target.value) || 180)} />
      </label>
    </div>
  )
}
