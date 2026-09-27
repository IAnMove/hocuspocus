import { ModalShell } from '../common/ModalShell'
import { useUiTranslation } from '../../i18n'

export function MediaMoveDialog({ workspaces, onClose, onMove }: {
  workspaces: string[]
  onClose: () => void
  onMove: (workspace: string) => void
}) {
  const { t } = useUiTranslation('activity')
  const { t: common } = useUiTranslation('common')
  return <ModalShell open title={t('moveOutput.title')} onClose={onClose}
    className="fixed inset-0 z-[150] flex items-center justify-center bg-black/70 p-4"
    onMouseDown={event => { event.stopPropagation(); if (event.target === event.currentTarget) onClose() }}>
    <section onClick={event => event.stopPropagation()} className="flex max-h-[80dvh] w-full max-w-sm flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary p-4 text-text-primary">
      <h2 className="mb-3 text-sm font-medium">{t('moveOutput.title')}</h2>
      <div className="min-h-0 overflow-y-auto overscroll-contain">
        {workspaces.map(name => <button key={name} type="button" onClick={() => onMove(name)}
          className="block min-h-11 w-full rounded px-3 py-2 text-left text-sm [overflow-wrap:anywhere] hover:bg-bg-hover">{name}</button>)}
        {workspaces.length === 0 && <p className="py-3 text-sm text-text-muted">{t('moveOutput.empty')}</p>}
      </div>
      <button type="button" onClick={onClose} className="mt-3 min-h-11 shrink-0 rounded border border-border px-3 text-sm">{common('actions.cancel')}</button>
    </section>
  </ModalShell>
}
