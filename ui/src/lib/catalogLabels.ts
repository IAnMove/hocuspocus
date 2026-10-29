import type { ParseKeys, TFunction } from 'i18next'

/** Catalog ids become studio keys. ``defaultValue`` is the English the server or the prompt data already carries. */
const key = (value: string) => value as ParseKeys<'studio'>

type Named = { id: string; title: string; description: string }
type Labeled = { id: string; label: string; description: string }
type EngineRow = { id: string; label: string; description: string; install_hint?: string | null }

/** Display name of a 2.5D narrative template. The stored scene name and the model prompt stay English. */
export function narrativeCopy(t: TFunction<'studio'>, item: Named) {
  return {
    title: t(key(`narrativeTemplates.${item.id}.title`), { defaultValue: item.title }),
    description: t(key(`narrativeTemplates.${item.id}.description`), { defaultValue: item.description }),
  }
}

/** Procedural (non-humanoid) clip label. Humanoid clips stay on the scene3d catalog. */
export function proceduralClipCopy(t: TFunction<'studio'>, item: Labeled) {
  return {
    label: t(key(`rigCatalog.clips.${item.id}.label`), { defaultValue: item.label }),
    description: t(key(`rigCatalog.clips.${item.id}.description`), { defaultValue: item.description }),
  }
}

export function rigProfileCopy(t: TFunction<'studio'>, item: Labeled) {
  return {
    label: t(key(`rigCatalog.profiles.${item.id}.label`), { defaultValue: item.label }),
    description: t(key(`rigCatalog.profiles.${item.id}.description`), { defaultValue: item.description }),
  }
}

export function proceduralCategory(t: TFunction<'studio'>, category: string) {
  return t(key(`rigCatalog.categories.${category}`), { defaultValue: category })
}

/** Engine row from rig capabilities. An unknown id keeps the server's English. */
export function rigEngineCopy(t: TFunction<'studio'>, item: EngineRow) {
  return {
    label: t(key(`rigCatalog.engines.${item.id}.label`), { defaultValue: item.label }),
    description: t(key(`rigCatalog.engines.${item.id}.description`), { defaultValue: item.description }),
    installHint: item.install_hint
      ? t(key(`rigCatalog.engines.${item.id}.installHint`), { defaultValue: item.install_hint })
      : '',
  }
}
