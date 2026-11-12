import type { InstallComponent, InstallStatus } from '../api/installManager'

/** What a row may offer right now. Pure, so the rules are tested without a browser. */
export interface RowActions {
  /** Install a missing component, or update one whose environment is out of date. */
  primary: 'install' | 'update' | null
  canUninstall: boolean
  /** Why the buttons are disabled, if they are. */
  blockedBy: 'busy' | 'launcher' | null
}

export function rowActions(row: InstallComponent, status: Pick<InstallStatus, 'busy' | 'launcher'>): RowActions {
  if (row.state === 'unsupported' || row.state === 'running') {
    return { primary: null, canUninstall: false, blockedBy: null }
  }
  const primary = row.state === 'not_installed' ? 'install' : row.state === 'needs_update' ? 'update' : null
  const canUninstall = row.state === 'installed' || row.state === 'needs_update'
  if (status.busy) return { primary, canUninstall, blockedBy: 'busy' }
  // Removing needs no Pinokio, only installing does.
  return { primary, canUninstall, blockedBy: primary && !status.launcher.available ? 'launcher' : null }
}

export interface SizeLabel {
  bytes: number | null
  /** measured: on disk now. estimated: what an install is expected to take. measuring: still counting. */
  kind: 'measured' | 'estimated' | 'measuring'
}

export function sizeLabel(row: InstallComponent): SizeLabel {
  if (row.state === 'not_installed' || row.state === 'unsupported') return { bytes: row.estimatedBytes, kind: 'estimated' }
  if (row.sizeBytes === null) return { bytes: null, kind: 'measuring' }
  return { bytes: row.sizeBytes, kind: 'measured' }
}

export interface ReclaimLabel {
  /** Bytes a removal really frees; null while the server is still measuring. */
  bytes: number | null
  /** Most of the folder is packages Pinokio keeps in its shared cache, so the folder size overstates the gain. */
  mostlyShared: boolean
}

export function reclaimLabel(row: InstallComponent): ReclaimLabel | null {
  if (row.state !== 'installed' && row.state !== 'needs_update') return null
  const bytes = row.reclaimableBytes
  const mostlyShared = bytes !== null && row.sizeBytes !== null && bytes < row.sizeBytes / 2
  return { bytes, mostlyShared }
}

/** An install of a missing component that the free disk space cannot hold. */
export function exceedsFreeSpace(row: InstallComponent, freeBytes: number): boolean {
  return row.state === 'not_installed' && row.estimatedBytes > freeBytes
}

/** A success is news for a while; a failure stays until the next attempt replaces it. */
export const SUCCESS_NOTICE_MS = 30 * 60 * 1000

/** The job outcome worth telling the person about once the component is idle again. */
export function finishedNotice(row: InstallComponent, now: number = Date.now()): 'installed' | 'removed' | 'failed' | null {
  const job = row.job
  if (!job || job.state === 'running') return null
  if (job.state === 'failed') return 'failed'
  if (job.finishedAt !== null && now - job.finishedAt * 1000 > SUCCESS_NOTICE_MS) return null
  return job.kind === 'install' ? 'installed' : 'removed'
}
