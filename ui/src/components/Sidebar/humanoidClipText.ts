import type { ParseKeys } from 'i18next'
import type { RigAnimation } from '../../api/model3d'
import { useUiTranslation } from '../../i18n'

/** Keys built from clip ids the catalogs define; ``defaultValue`` covers anything new. */
const key = (value: string) => value as ParseKeys<'scene3d'>

/** Clip label and description in the interface language, falling back to the backend's English. */
export function useClipText() {
  const { t } = useUiTranslation('scene3d')
  return (animation: RigAnimation, engineId: string) => engineId === 'humanoid'
    ? {
        label: t(key(`rig.humanoidClip.${animation.id}`), { defaultValue: animation.label }),
        description: t(key(`rig.humanoidClipHelp.${animation.id}`), { defaultValue: animation.description }),
      }
    : { label: animation.label, description: animation.description }
}
