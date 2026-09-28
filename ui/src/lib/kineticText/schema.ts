import { KINETIC_PRESETS, TEXT_ALIGNS, TEXT_BOX_KINDS, TEXT_ENTERS, TEXT_EXITS, TEXT_FONTS, TEXT_LOOPS, TEXT_WEIGHTS } from './types'

const color = { type: 'string', pattern: '^#[0-9a-fA-F]{6}$' }
const span = (presets: readonly string[]) => ({
  type: 'object', additionalProperties: false,
  properties: { preset: { enum: [...presets] }, duration: { type: 'number', minimum: 0.05, maximum: 3 } },
  required: ['preset', 'duration'],
})

export const KINETIC_TEXT_SCHEMA = {
  type: 'array', maxItems: 48, items: {
    type: 'object', additionalProperties: false, required: ['id', 'text', 'start', 'end', 'preset'],
    properties: {
      id: { type: 'string' }, text: { type: 'string', maxLength: 240 },
      start: { type: 'number', minimum: 0 }, end: { type: 'number', minimum: 0 },
      preset: { enum: [...KINETIC_PRESETS] },
      x: { type: 'number', minimum: 0, maximum: 100 }, y: { type: 'number', minimum: 0, maximum: 100 },
      size: { type: 'number', minimum: 2, maximum: 25 }, color, rotation: { type: 'number', minimum: -45, maximum: 45 },
      font: { enum: [...TEXT_FONTS] },
      enter: span(TEXT_ENTERS), exit: span(TEXT_EXITS), loop: { enum: [...TEXT_LOOPS] },
      weight: { enum: [...TEXT_WEIGHTS] }, align: { enum: [...TEXT_ALIGNS] },
      maxWidth: { type: 'number', minimum: 10, maximum: 100 },
      lineHeight: { type: 'number', minimum: 0.8, maximum: 2 },
      letterSpacing: { type: 'number', minimum: -0.1, maximum: 0.5 },
      uppercase: { type: 'boolean' }, italic: { type: 'boolean' },
      stroke: { type: 'object', additionalProperties: false, properties: { color, width: { type: 'number', minimum: 0, maximum: 0.3 } }, required: ['color', 'width'] },
      shadow: { type: 'object', additionalProperties: false, properties: {
        color, blur: { type: 'number', minimum: 0, maximum: 2 }, x: { type: 'number', minimum: -1, maximum: 1 }, y: { type: 'number', minimum: -1, maximum: 1 },
      }, required: ['color', 'blur', 'x', 'y'] },
      fill: { type: 'object', additionalProperties: false, properties: {
        kind: { enum: ['solid', 'gradient'] }, from: color, to: color, angle: { type: 'number', minimum: -180, maximum: 180 },
      }, required: ['kind'] },
      box: { type: 'object', additionalProperties: false, properties: {
        kind: { enum: [...TEXT_BOX_KINDS] }, color, opacity: { type: 'number', minimum: 0, maximum: 1 },
        padding: { type: 'number', minimum: 0, maximum: 4 }, radius: { type: 'number', minimum: 0, maximum: 2 },
      }, required: ['kind', 'color', 'opacity', 'padding'] },
      counter: { type: 'object', additionalProperties: false, properties: {
        from: { type: 'number' }, to: { type: 'number' }, decimals: { type: 'integer', minimum: 0, maximum: 4 }, ease: { enum: ['linear', 'ease'] },
      }, required: ['from', 'to', 'decimals', 'ease'] },
      template: { type: 'string', maxLength: 80 },
      beatPulse: { type: 'number', minimum: 0, maximum: 1 },
      trap: { type: 'boolean' },
    },
  },
} as const
