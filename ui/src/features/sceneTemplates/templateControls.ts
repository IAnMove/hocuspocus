// The i18next instance src/i18n initializes at app start. E2E specs load this module in Node,
// where src/i18n's locale JSON cannot load, so it is not imported here.
import i18n from 'i18next'
import type { ControlSpec, ControlValue, SceneTemplateDefinition } from './catalog'
import { TemplateError } from './templateErrors'

export type TemplateControlInput = Readonly<Record<string, ControlValue | undefined>>
export type TemplateControlValues = Readonly<Record<string, ControlValue>>

const CONTROL_LABELS: Record<string, () => string> = {
  duration: () => i18n.t('scene3d:templateControls.labels.duration'),
  bpm: () => i18n.t('scene3d:templateControls.labels.bpm'),
  intensity: () => i18n.t('scene3d:templateControls.labels.intensity'),
}

function controlLabel(key: string): string {
  return CONTROL_LABELS[key]?.() ?? key
}

function checked(key: string, spec: ControlSpec, value: unknown): ControlValue {
  const label = controlLabel(key)
  if (spec.kind === 'number') {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < spec.min || value > spec.max) {
      throw new TemplateError('template_bad_control', i18n.t('scene3d:templateControls.range', { label, min: spec.min, max: spec.max }))
    }
    return value
  }
  if (spec.kind === 'choice') {
    if (typeof value !== 'string' || !spec.options.includes(value)) {
      throw new TemplateError('template_bad_control', i18n.t('scene3d:templateControls.choice', { label, options: spec.options.join(', ') }))
    }
    return value
  }
  // Code points, not UTF-16 units: the Python compile counts the same way.
  if (typeof value !== 'string' || [...value].length > spec.maxLength) {
    throw new TemplateError('template_bad_control', i18n.t('scene3d:templateControls.text', { label, max: spec.maxLength }))
  }
  return value
}

/** Every control of the card: the caller's value, else the alias preset, else the card default. Same checks and
 * codes as video2d_compile._controls in Python. */
export function resolveControls(template: SceneTemplateDefinition, preset: TemplateControlValues, input: TemplateControlInput): TemplateControlValues {
  for (const [key, value] of Object.entries(input)) {
    if (value !== undefined && !(key in template.controls)) throw new TemplateError('template_bad_control', i18n.t('scene3d:templateControls.unknown', { key, id: template.id }))
  }
  return Object.fromEntries(Object.entries(template.controls).map(([key, spec]) => {
    const value = input[key] !== undefined ? input[key] : key in preset ? preset[key] : spec.default
    return [key, checked(key, spec, value)]
  }))
}
