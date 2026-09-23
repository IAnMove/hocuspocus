import { useUiTranslation } from '../../i18n'
import { ModalShell } from './ModalShell'

/** Asks before an action that cannot be undone. The cancel button is the
 *  first control, so Enter or an accidental tap never confirms by default. */
export function ConfirmDialog({ title, message, confirmLabel, destructive = true, onConfirm, onCancel }: {
  title: string
  message: string
  confirmLabel: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useUiTranslation('common')
  return <ModalShell open title={title} onClose={onCancel}
    className="fixed inset-0 z-[160] flex items-center justify-center bg-black/70 p-4"
    onMouseDown={event => { event.stopPropagation(); if (event.target === event.currentTarget) onCancel() }}>
    <section onClick={event => event.stopPropagation()} className="w-full max-w-sm rounded-xl border border-border bg-bg-secondary p-4 text-text-primary">
      <h2 className="text-sm font-medium">{title}</h2>
      <p className="mt-2 text-sm text-text-secondary [overflow-wrap:anywhere]">{message}</p>
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="min-h-11 rounded-lg border border-border px-4 text-sm hover:bg-bg-hover">{t('actions.cancel')}</button>
        <button type="button" onClick={onConfirm}
          className={`min-h-11 rounded-lg px-4 text-sm font-medium text-white ${destructive ? 'bg-red-600 hover:bg-red-500' : 'bg-accent-blue hover:bg-accent-blue-hover'}`}>
          {confirmLabel}
        </button>
      </div>
    </section>
  </ModalShell>
}
