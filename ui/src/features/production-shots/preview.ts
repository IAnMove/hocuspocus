const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$/

export function previewUrl(file: string | null, workspace: string): string | null {
  if (!file || file.includes('..') || !SAFE_NAME.test(file)) return null
  const name = encodeURIComponent(file)
  const scope = encodeURIComponent(workspace)
  return `/api/v1/file/${name}?workspace=${scope}`
}
