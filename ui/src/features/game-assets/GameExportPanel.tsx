import { useUiTranslation } from '../../i18n'
import { codeLabel, gameText } from './gameErrors'
import { fileUrl } from './reviewModel'
import { useGameAssetsStore } from './store'
import { buttonClass, panelClass } from './styles'
import type { ExportMissing, ExportResult, GameAsset, GameExportRecord } from './types'

/** ``kind: n`` for each packed kind, then the total. */
function countsText(counts: Record<string, number>): string {
  const kinds = Object.entries(counts).filter(([kind]) => kind !== 'total').map(([kind, count]) => `${codeLabel('kinds', kind)}: ${count}`)
  return [...kinds, gameText('exportTotal', { count: counts.total ?? 0 })].join(' · ')
}

function missingText(row: ExportMissing): string {
  const id = row.assetId || row.id || ''
  const kind = row.kind ? codeLabel('kinds', row.kind) : ''
  const reason = row.problem ? codeLabel('exportProblems', row.problem) : codeLabel('statuses', row.status || '')
  const files = row.files?.length ? ` (${row.files.join(', ')})` : ''
  return `${kind} ${id}: ${reason}${files}`.trim()
}

function formatDate(value: string, language: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(language)
}

function AssetRows({ assets }: { assets: GameAsset[] }) {
  return (
    <ul className="space-y-0.5">
      {assets.map(asset => (
        <li key={asset.id} className="text-sm">{codeLabel('kinds', asset.kind)} <span className="font-mono">{asset.id}</span> · {codeLabel('statuses', asset.status)}</li>
      ))}
    </ul>
  )
}

function PackLink({ file, workspace }: { file: string; workspace: string }) {
  const name = file.split('/').pop() || file
  return <a className="underline" href={fileUrl(file, workspace)} download={name}>{name}</a>
}

function ExportSummary({ result, workspace }: { result: ExportResult; workspace: string }) {
  const { t } = useUiTranslation('gameAssets')
  const lost = result.missing.filter(row => row.problem)
  return (
    <div className={panelClass} role="status">
      <p className="text-sm">{t('exportDone')} <PackLink file={result.file} workspace={workspace} /></p>
      <p className="text-sm">{countsText(result.counts)}</p>
      {lost.length > 0 && (
        <>
          <p className="mt-2 text-sm">{t('exportLost')}</p>
          <ul className="space-y-0.5">{lost.map((row, index) => <li key={`${row.assetId || row.id || ''}-${index}`} className="text-sm text-amber-500">{missingText(row)}</li>)}</ul>
        </>
      )}
    </div>
  )
}

function ExportHistory({ exports, workspace }: { exports: GameExportRecord[]; workspace: string }) {
  const { t, i18n } = useUiTranslation('gameAssets')
  const newest = [...exports].reverse()
  return (
    <div className={panelClass}>
      <p className="text-sm">{t('exportHistory')}</p>
      {!newest.length && <p className="text-sm text-muted-foreground">{t('exportEmpty')}</p>}
      <ul className="space-y-1">
        {newest.map(item => (
          <li key={item.id} className="text-sm">
            <PackLink file={item.file} workspace={workspace} /> · {t('exportRevision', { revision: item.revision })} · {formatDate(item.createdAt, i18n.language)} · {countsText(item.counts || {})}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function GameExportPanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const workspace = useGameAssetsStore(state => state.workspace)
  const exporting = useGameAssetsStore(state => state.exporting)
  const last = useGameAssetsStore(state => state.exportResult)
  const exportPack = useGameAssetsStore(state => state.exportPack)
  if (!game) return null
  const approved = game.assets.filter(asset => asset.status === 'approved')
  const waiting = game.assets.filter(asset => asset.status !== 'approved')
  const result = last?.gameId === game.id ? last.result : null

  return (
    <div className="space-y-3">
      <div className={panelClass}>
        <p className="text-sm">{t('exportApproved', { count: approved.length })}</p>
        <AssetRows assets={approved} />
        <p className="mt-2 text-sm">{t('exportMissing', { count: waiting.length })}</p>
        <AssetRows assets={waiting} />
      </div>
      <button type="button" className={buttonClass} disabled={exporting} aria-busy={exporting}
        onClick={() => { void exportPack() }}>{exporting ? t('exporting') : t('exportPack')}</button>
      {!approved.length && <p className="text-sm text-muted-foreground">{t('exportNeedsApproval')}</p>}
      {result && <ExportSummary result={result} workspace={workspace} />}
      <ExportHistory exports={game.exports || []} workspace={workspace} />
    </div>
  )
}
