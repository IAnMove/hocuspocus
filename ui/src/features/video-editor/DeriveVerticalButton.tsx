import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { deriveMontage } from '../../api/montages'
import { loadMontageIntoEditor } from './montageLoader'

type LoadedMontage = Awaited<ReturnType<typeof loadMontageIntoEditor>>

export function DeriveVerticalButton({
  workspace,
  file,
  disabled = false,
  onOpened,
  onError,
  derive = deriveMontage,
  load = loadMontageIntoEditor,
}: {
  workspace: string
  file: string | null
  disabled?: boolean
  onOpened: (loaded: LoadedMontage) => void
  onError: (message: string) => void
  derive?: typeof deriveMontage
  load?: typeof loadMontageIntoEditor
}) {
  const { t } = useUiTranslation('videoEditor')
  const [busy, setBusy] = useState(false)
  if (!file) return null
  const openVertical = () => {
    setBusy(true)
    derive(workspace, file, { format: '9:16', fit: 'blur' })
      .then(saved => load(workspace, saved.file))
      .then(onOpened)
      .catch(reason => onError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setBusy(false))
  }
  return (
    <button
      type="button"
      onClick={openVertical}
      disabled={disabled || busy}
      title={t('toolbar.verticalTitle')}
      className="flex items-center gap-1.5 rounded-lg border border-border bg-bg-secondary px-2.5 py-1.5 text-xs hover:bg-bg-hover disabled:opacity-40"
    >
      {busy ? t('toolbar.verticalWorking') : t('toolbar.vertical')}
    </button>
  )
}
