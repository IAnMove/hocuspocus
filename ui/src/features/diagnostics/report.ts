import { sanitizePack } from './redact.ts'
import { DIAGNOSTICS_SCHEMA, type ReportPack } from './types.ts'

export function isReportPack(value: unknown): value is ReportPack {
  if (!value || typeof value !== 'object') return false
  const pack = value as ReportPack
  return pack.schema === DIAGNOSTICS_SCHEMA && Array.isArray(pack.availability)
}

export function parsePack(value: unknown): ReportPack {
  const sanitized = sanitizePack(value)
  if (!isReportPack(sanitized)) {
    throw new Error('unexpected diagnostics schema')
  }
  return sanitized
}

export function serializeReportPack(pack: ReportPack): string {
  return JSON.stringify(sanitizePack(pack), null, 2)
}

export function reportFilename(stamp = new Date().toISOString().slice(0, 10)): string {
  return `hocuspocus-diagnostics-${stamp}.json`
}

export function triggerDownload(pack: ReportPack, stamp?: string): string {
  const name = reportFilename(stamp)
  const blob = new Blob([serializeReportPack(pack)], { type: 'application/json' })
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(href)
  return name
}
