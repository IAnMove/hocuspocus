import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { exportGame } from '../../api/gameAssets'
import { fileUrl } from './reviewModel'
import { useGameAssetsStore } from './store'
import { buttonClass, panelClass } from './styles'
import type { ExportResult } from './types'

export function GameExportPanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const workspace = useGameAssetsStore(state => state.workspace)
  const openGame = useGameAssetsStore(state => state.openGame)
  const [pack, setPack] = useState<ExportResult | null>(null)
  const [size, setSize] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!game) return null
  const approved = game.assets.filter(asset => asset.status === 'approved')
  const missing = game.assets.filter(asset => asset.status !== 'approved')

  const run = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await exportGame(workspace, game.id)
      setPack(result)
      setSize(await fileSize(result.url || fileUrl(result.file, workspace)))
      await openGame(game.id)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not export')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className={panelClass}>
        <p className="text-sm">{t('exportApproved')} {approved.length}</p>
        {approved.map(asset => <p key={asset.id} className="text-sm">{asset.kind} {asset.id}</p>)}
        <p className="mt-2 text-sm">{t('exportMissing')} {missing.length}</p>
        {missing.map(asset => <p key={asset.id} className="text-sm">{asset.kind} {asset.id} {asset.status}</p>)}
      </div>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => { void run() }}>{t('exportPack')}</button>
      {error && <p className="text-sm text-red-500">{error}</p>}
      {pack && (
        <p className="text-sm">
          <a href={pack.url || fileUrl(pack.file, workspace)}>{pack.file}</a>
          {size !== null && ` · ${size} B`}
        </p>
      )}
      <div className={panelClass}>
        <p className="text-sm">{t('exportHistory')}</p>
        {game.exports.map(item => <p key={item.id} className="text-sm">{item.file} · r{item.revision}</p>)}
        {!game.exports.length && <p className="text-sm text-muted-foreground">{t('exportEmpty')}</p>}
      </div>
    </div>
  )
}

async function fileSize(url: string): Promise<number | null> {
  try {
    const response = await fetch(url, { method: 'HEAD' })
    const length = Number(response.headers.get('content-length') || '')
    return Number.isFinite(length) && length > 0 ? length : null
  } catch {
    return null
  }
}
