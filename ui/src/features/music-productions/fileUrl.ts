/** Workspace file URL. A name with a slash or `..` is not a workspace file. */
export function musicProductionFileUrl(workspace: string, name: string | null | undefined): string | null {
  if (!name || name.includes('/') || name.includes('..')) return null
  return `/api/v1/file/${encodeURIComponent(name)}?workspace=${encodeURIComponent(workspace)}`
}
