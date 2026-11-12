import i18n from '../../i18n'

/** Card title and description in the active UI language. A missing key keeps the catalog string. */
const copy = (key: string, fallback: string) => String(i18n.t(key, fallback, { ns: 'scene3d' }))

export function templateDisplay(template: { id: string; title: string; description: string }) {
  return {
    title: copy(`templateCards.${template.id}.title`, template.title),
    description: copy(`templateCards.${template.id}.description`, template.description),
  }
}
