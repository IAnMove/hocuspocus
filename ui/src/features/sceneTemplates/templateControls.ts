import type { ControlSpec, ControlValue, SceneTemplateDefinition } from './catalog'
import { TemplateError } from './templateErrors'

export type TemplateControlInput = Readonly<Record<string, ControlValue | undefined>>
export type TemplateControlValues = Readonly<Record<string, ControlValue>>

const LABELS: Record<string, string> = { duration: 'Duración', bpm: 'BPM', intensity: 'Intensidad' }

function checked(key: string, spec: ControlSpec, value: unknown): ControlValue {
  const label = LABELS[key] ?? key
  if (spec.kind === 'number') {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < spec.min || value > spec.max) {
      throw new TemplateError('template_bad_control', `${label}: debe estar entre ${spec.min} y ${spec.max}.`)
    }
    return value
  }
  if (spec.kind === 'choice') {
    if (typeof value !== 'string' || !spec.options.includes(value)) {
      throw new TemplateError('template_bad_control', `${label}: debe ser ${spec.options.join(', ')}.`)
    }
    return value
  }
  // Code points, not UTF-16 units: the Python compile counts the same way.
  if (typeof value !== 'string' || [...value].length > spec.maxLength) {
    throw new TemplateError('template_bad_control', `${label}: texto de hasta ${spec.maxLength} caracteres.`)
  }
  return value
}

/** Every control of the card: the caller's value, else the alias preset, else the card default. Same checks and
 * codes as video2d_compile._controls in Python. */
export function resolveControls(template: SceneTemplateDefinition, preset: TemplateControlValues, input: TemplateControlInput): TemplateControlValues {
  for (const [key, value] of Object.entries(input)) {
    if (value !== undefined && !(key in template.controls)) throw new TemplateError('template_bad_control', `${key}: control desconocido en ${template.id}.`)
  }
  return Object.fromEntries(Object.entries(template.controls).map(([key, spec]) => {
    const value = input[key] !== undefined ? input[key] : key in preset ? preset[key] : spec.default
    return [key, checked(key, spec, value)]
  }))
}
