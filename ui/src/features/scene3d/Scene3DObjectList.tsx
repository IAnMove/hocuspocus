import { useUiTranslation } from '../../i18n'
import type { Scene3DSlot } from './types'

export function Scene3DObjectList({ slots, selectedId, onSelect }: { slots: readonly Scene3DSlot[]; selectedId?: string; onSelect: (id: string) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  const { t: sceneT } = useUiTranslation('scene3d')
  return <section className="space-y-2 rounded-xl border border-border bg-bg-secondary p-3" aria-label={t('objects.title')}>
    <h3 className="text-sm font-semibold">{t('objects.title')} ({slots.length})</h3>
    <p className="text-sm text-text-muted">{t('objects.hint')}</p>
    <ul className="max-h-64 space-y-1 overflow-y-auto" data-testid="scene3d-object-list">
      {slots.map(slot => <li key={slot.id}>
        <button type="button" onClick={() => onSelect(slot.id)} aria-pressed={selectedId === slot.id} data-slot-id={slot.id}
          className={`flex min-h-11 w-full flex-col rounded-lg border px-3 py-2 text-left text-sm ${selectedId === slot.id ? 'border-cyan-300 bg-cyan-300/15 text-cyan-50' : 'border-border text-text-primary'}`}>
          <span className="break-all font-medium">{slot.character?.name || slot.id}</span>
          <span className="text-xs text-text-muted">{sceneT(`stage.slot.${slot.slot}`)} · {t(`objects.${slot.media}`)}</span>
        </button>
      </li>)}
    </ul>
  </section>
}
