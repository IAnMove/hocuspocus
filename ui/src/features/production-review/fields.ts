import type { TakeStatus } from './types.ts'

const STATUSES = new Set<TakeStatus>(['planned', 'queued', 'running', 'completed', 'failed', 'cancelled'])

export function text(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

export function firstText(...values: unknown[]): string {
  for (const value of values) {
    const next = text(value)
    if (next) return next
  }
  return ''
}

export function asMap(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

export function finiteNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const next = text(value)
    if (!next || seen.has(next)) continue
    seen.add(next)
    result.push(next)
  }
  return result
}

export function isTakeStatus(value: unknown): value is TakeStatus {
  return typeof value === 'string' && STATUSES.has(value as TakeStatus)
}

export function filenameOf(value: unknown): string {
  const raw = text(value).replace(/\\/g, '/')
  if (!raw) return ''
  return raw.split('/').pop() || raw
}
