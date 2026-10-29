import type { ParseKeys } from 'i18next'
import type { RigAnimation } from '../../api/model3d'
import { useUiTranslation } from '../../i18n'
import { proceduralClipCopy } from '../../lib/catalogLabels'

/** Keys built from clip ids the catalogs define; ``defaultValue`` covers anything new. */
const key = (value: string) => value as ParseKeys<'scene3d'>

/** Clip label and description in the interface language, falling back to the backend's English.
 *  Humanoid clips use the scene3d catalog. Procedural clips use studio keys by id. */
export function useClipText() {
  const { t } = useUiTranslation('scene3d')
  const { t: tStudio } = useUiTranslation('studio')
  return (animation: RigAnimation, engineId: string) => engineId === 'humanoid'
    ? {
        label: t(key(`rig.humanoidClip.${animation.id}`), { defaultValue: animation.label }),
        description: t(key(`rig.humanoidClipHelp.${animation.id}`), { defaultValue: animation.description }),
      }
    : proceduralClipCopy(tStudio, animation)
}
