import { useState } from 'react'
import { BASE } from '../../api/http'
import { useUiTranslation } from '../../i18n'
import { controlReason } from '../../i18n/controlLabel'
import { comicMontageBody, type ComicMontageMode } from '../scene3d/comicTransition'
import { applyComicMontageTransition } from './comicMontageRun'
import { loadMontageIntoEditor } from './montageLoader'

type LoadedMontage = Awaited<ReturnType<typeof loadMontageIntoEditor>>

async function postComicTransition(body: ReturnType<typeof comicMontageBody>): Promise<{ montage?: { file?: string } }> {
  const response = await fetch(`${BASE}/api/v1/world3d/templates/commands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const payload = await response.json().catch(() => ({})) as { detail?: { message?: string } | string; result?: { montage?: { file?: string } } }
  if (!response.ok) {
    const detail = payload.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || 'Comic transition failed')
  }
  return payload.result ?? {}
}

/** The Video Editor door of `scene3d.comic.transition`. `between` is the clip index. */
export function ComicTransitionButton({
  workspace,
  file,
  between,
  onOpened,
  onError,
  prepare,
  run = postComicTransition,
  load = loadMontageIntoEditor,
}: {
  workspace: string
  file: string | null
  between: number
  onOpened: (loaded: LoadedMontage) => void
  onError: (message: string) => void
  prepare?: () => Promise<string>
  run?: typeof postComicTransition
  load?: typeof loadMontageIntoEditor
}) {
  const { t } = useUiTranslation('videoEditor')
  const [mode, setMode] = useState<ComicMontageMode>('insert')
  const [busy, setBusy] = useState(false)
  const go = () => {
    if (!file) return
    setBusy(true)
    applyComicMontageTransition({
      workspace, file, between, mode, intentId: `comic-ui-${Date.now()}`, prepare, run, load,
    })
      .then(onOpened)
      .catch(reason => onError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setBusy(false))
  }
  const unavailable = !file || busy
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <select
        aria-label={t('inspector.comicTransition')}
        value={mode}
        disabled={busy}
        title={controlReason(busy, 'disabled.actionInProgress')}
        onChange={event => setMode(event.target.value as ComicMontageMode)}
        className="rounded border border-border bg-bg-tertiary px-2 py-1 text-xs"
      >
        <option value="insert">{t('inspector.comicInsert')}</option>
        <option value="replace">{t('inspector.comicReplace')}</option>
      </select>
      <button
        type="button"
        onClick={go}
        disabled={unavailable}
        title={controlReason(unavailable, 'disabled.actionInProgress')}
        className="rounded border border-border px-2 py-1 text-xs hover:bg-bg-hover disabled:opacity-40"
      >
        {busy ? t('inspector.comicWorking') : t('inspector.comicTransition')}
      </button>
      {!file && <span className="text-[10px] text-text-muted">{t('inspector.comicNeedsSave')}</span>}
    </div>
  )
}
