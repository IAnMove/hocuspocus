const OMIT = new Set([
  'prompt', 'negative_prompt', 'lyrics', 'prompt_full', 'prompt_original',
  'prompt_effective', 'prompt_display', 'enhanced_prompt', 'video_prompt',
  'cookie', 'cookies', 'set_cookie',
])

const SENSITIVE_PARTS = [
  'api_key', 'apikey', 'access_token', 'refresh_token', 'authorization',
  'password', 'passwd', 'client_secret', 'private_key', 'cookie', 'session',
  'secret', 'credential',
]

const BEARER = /\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi
const QUERY = /([?&](?:token|api[_-]?key|access[_-]?token|session)=)[^&#\s]+/gi
const COOKIE = /((?:cookie|set-cookie)\s*[:=]\s*)[^\r\n]+/gi
const ASSIGN = /\b(api[_-]?key|access[_-]?token|password|secret|session|token)\s*[:=]\s*[^\s,;]+/gi
const SK = /\bsk-[A-Za-z0-9_-]+/gi

export function sensitiveAction(key: string): 'omit' | 'redact' | 'keep' {
  const token = key.trim().toLowerCase().replace(/-/g, '_')
  if (OMIT.has(token)) return 'omit'
  if (token === 'token' || token.endsWith('_token')) return 'redact'
  if (SENSITIVE_PARTS.some(part => token.includes(part))) return 'redact'
  return 'keep'
}

export function redactString(value: string): string {
  return value
    .replace(BEARER, '$1 [REDACTED]')
    .replace(QUERY, '$1[REDACTED]')
    .replace(COOKIE, '$1[REDACTED]')
    .replace(ASSIGN, '$1=[REDACTED]')
    .replace(SK, '[REDACTED]')
    .slice(0, 2000)
}

function redactMapping(value: Record<string, unknown>, depth: number): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value).slice(0, 80)) {
    const action = sensitiveAction(key)
    if (action === 'omit') continue
    result[key] = action === 'redact' ? '[REDACTED]' : sanitizePack(item, depth + 1)
  }
  return result
}

export function sanitizePack(value: unknown, depth = 0): unknown {
  if (depth > 8) return null
  if (typeof value === 'string') return redactString(value)
  if (Array.isArray(value)) return value.slice(0, 80).map(item => sanitizePack(item, depth + 1))
  if (value && typeof value === 'object') {
    return redactMapping(value as Record<string, unknown>, depth)
  }
  return value
}

export function packContainsSecret(pack: unknown, secret: string): boolean {
  return JSON.stringify(pack).includes(secret)
}
