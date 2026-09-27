// CSS colors for screen effects. Hex stops stay `#rrggbbaa` so existing cues
// paint the same pixels. Functional colors cannot take a hex suffix.

const HEX_BYTE = /^[0-9a-f]{2}$/i

function hexWithAlpha(color: string, alpha: string): string | null {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(color)
  if (!match || !HEX_BYTE.test(alpha)) return null
  const digits = match[1]
  const body = digits.length <= 4 ? digits.slice(0, 3).split('').map(channel => channel + channel).join('') : digits.slice(0, 6)
  return `#${body}${alpha}`
}

function alphaUnit(alpha: string): string {
  const value = HEX_BYTE.test(alpha) ? parseInt(alpha, 16) / 255 : Number(alpha)
  if (!Number.isFinite(value) || value <= 0) return '0'
  if (value >= 1) return '1'
  return String(Math.round(value * 10000) / 10000)
}

function functionalChannels(args: string): string[] | null {
  const head = args.split('/')[0]?.trim() ?? ''
  if (!head) return null
  const parts = (head.includes(',') ? head.split(',') : head.split(/\s+/)).map(part => part.trim()).filter(Boolean)
  return parts.length >= 3 ? parts.slice(0, 3) : null
}

/** `alpha` is two hex digits (`00`, `70`, `aa`) or a 0..1 number. */
export function withAlpha(color: string, alpha: string): string {
  const trimmed = color.trim()
  const hex = hexWithAlpha(trimmed, alpha)
  if (hex) return hex
  const functional = /^(rgba?|hsla?)\((.*)\)$/i.exec(trimmed)
  const channels = functional ? functionalChannels(functional[2]) : null
  if (!functional || !channels) return trimmed
  const space = functional[1].toLowerCase().startsWith('rgb') ? 'rgba' : 'hsla'
  return `${space}(${channels.join(', ')}, ${alphaUnit(alpha)})`
}
