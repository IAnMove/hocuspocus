import { isHostPath, portableFilename, redactSecrets } from '../../lib/generationRecord'
import type { JsonMap, StoredField } from './types'

export const UNKNOWN: StoredField<never> = { known: false }

export function known<T>(value: T): StoredField<T> {
  return { known: true, value }
}

export function asMap(value: unknown): JsonMap {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonMap : {}
}

export function text(value: unknown): string | null {
  if (typeof value === 'string') return value
  if (value == null) return null
  const candidate = String(value).trim()
  return candidate || null
}

export function storedString(record: JsonMap, key: string): StoredField<string> {
  if (!Object.prototype.hasOwnProperty.call(record, key)) return UNKNOWN
  const value = record[key]
  if (value == null) return UNKNOWN
  return known(typeof value === 'string' ? value : String(value))
}

export function firstStored(record: JsonMap, keys: string[]): StoredField<string> {
  for (const key of keys) {
    const field = storedString(record, key)
    if (field.known) return field
  }
  return UNKNOWN
}

export function mapAt(value: unknown, keys: string[]): JsonMap {
  let current: unknown = value
  for (const key of keys) current = asMap(current)[key]
  return asMap(current)
}

export function fieldValue<T>(field: StoredField<T>): T | undefined {
  return field.known ? field.value : undefined
}

export function displayField(field: StoredField<string | null>, unknownLabel: string): string {
  if (!field.known || field.value == null) return unknownLabel
  return field.value
}

export function mintId(prefix: string): string {
  const token = globalThis.crypto?.randomUUID?.().replace(/-/g, '')
    || `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`
  return `${prefix}_${token.slice(0, 24)}`
}

export function portableUri(value: unknown): string | null {
  const candidate = text(value)
  if (!candidate) return null
  if (isHostPath(candidate)) return null
  if (candidate.startsWith('/api/v1/')) return candidate
  return portableFilename(candidate)
}

export function redactedParams(value: unknown): Record<string, unknown> {
  return redactSecrets(asMap(value)) as Record<string, unknown>
}
