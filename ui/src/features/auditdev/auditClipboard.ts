export type AuditFailedClip = {
  name: string
  jobId?: string
  prompt: string
}

export function formatFailedPromptDump(items: AuditFailedClip[]): string {
  const lines = [
    'AUDITDEV_FAILED_PROMPTS',
    `count: ${items.length}`,
    '',
  ]
  items.forEach((item, index) => {
    lines.push(`--- ${index + 1}/${items.length} ---`)
    lines.push(`file: ${item.name}`)
    lines.push(`job_id: ${item.jobId || ''}`)
    lines.push('prompt:')
    lines.push((item.prompt || '').trim() || '(no prompt in metadata)')
    lines.push('')
  })
  return lines.join('\n').trimEnd() + '\n'
}

export function promptFromMetadata(meta: {
  params?: Record<string, unknown> | null
} | null): string {
  const params = meta?.params
  if (!params) return ''
  const keys = ['prompt', 'video_prompt', 'enhanced_prompt']
  for (const key of keys) {
    const value = params[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return ''
}
