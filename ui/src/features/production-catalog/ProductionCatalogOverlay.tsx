import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useStore } from '../../stores/useStore'
import { listWorks, resolveWork } from './api'
import { ProductionCatalogPanel } from './ProductionCatalogPanel'
import type { CatalogPage, LightFormat } from './types'

export function ProductionCatalogOverlay({ open, onClose }: { open: boolean, onClose: () => void }) {
  const workspace = useStore(state => state.activeWorkspace) || 'default'
  if (!open) return null
  return <CatalogLoader key={workspace} workspace={workspace} onClose={onClose} />
}

function CatalogLoader({ workspace, onClose }: { workspace: string, onClose: () => void }) {
  const { t } = useTranslation('productionCatalog')
  const [format, setFormat] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState<CatalogPage | null>(null)
  const [failed, setFailed] = useState(false)
  const [nonce, setNonce] = useState(0)
  useEffect(() => {
    let live = true
    listWorks(workspace, format, status).then(
      result => { if (live) { setPage(result); setFailed(false) } },
      () => { if (live) setFailed(true) },
    )
    return () => { live = false }
  }, [workspace, format, status, nonce])
  const create = (body: { intent_id: string, format: LightFormat, title: string }) => {
    resolveWork(workspace, body).then(
      () => setNonce(current => current + 1),
      () => setFailed(true),
    )
  }
  if (failed) return <p className="p-4 text-xs">{t('loadFailed')}</p>
  if (!page) return <p className="p-4 text-xs">{t('loading')}</p>
  return <ProductionCatalogPanel workspace={workspace} page={page} format={format} status={status} onFormat={setFormat} onStatus={setStatus} onCreate={create} onLinked={() => setNonce(current => current + 1)} onClose={onClose} />
}
