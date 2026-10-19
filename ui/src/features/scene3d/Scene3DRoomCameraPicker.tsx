import { useUiTranslation } from '../../i18n'
import { activeRoomCamera } from './roomCamera'
import type { Scene3DDocument } from './types.ts'

/** The room's named cameras beside the camera family: pick the angle a staged room was built with. */
export function Scene3DRoomCameraPicker({ document, disabled, onChange }: { document: Scene3DDocument; disabled: boolean; onChange: (id: string) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  const cameras = document.room?.mold.cameras ?? []
  if (!cameras.length) return null
  const active = activeRoomCamera(document)
  return <label className="flex items-center gap-2 text-sm text-text-primary">{t('roomCamera.label')}
    <select disabled={disabled} value={active} data-testid="world3d-room-camera" onChange={event => { if (event.target.value) onChange(event.target.value) }}
      className="min-h-11 rounded-lg border border-border bg-bg-primary px-3 text-xs disabled:opacity-40">
      {!active && <option value="">{t('roomCamera.custom')}</option>}
      {cameras.map(camera => <option key={camera.id} value={camera.id}>{t(`roomCamera.names.${camera.id}`, { defaultValue: camera.id })}</option>)}
    </select>
  </label>
}
