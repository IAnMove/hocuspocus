import type { ParseKeys, TFunction } from 'i18next'

const presetKey = (value: string) => value as ParseKeys<'scene3d'>

/** Preset copy is keyed by id. An id the catalog does not know yet keeps the server text. */
export function hunyuanPresetCopy(t: TFunction<'scene3d'>, item: { id: string; label: string; description: string }) {
  return {
    label: t(presetKey(`hunyuan.presets.${item.id}.label`), { defaultValue: item.label }),
    description: t(presetKey(`hunyuan.presets.${item.id}.description`), { defaultValue: item.description }),
  }
}
