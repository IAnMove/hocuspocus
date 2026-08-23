export function workspaceRewriteSystemPrompt(instruction: string, shorten: boolean): string {
  const task = instruction.trim() || 'Keep the same meaning.'
  return [
    'You edit exactly one Director / MiniMax H3 shot prompt.',
    `Apply ONLY this instruction: ${task}`,
    'Return ONLY the rewritten prompt. No preface, no quotes, no markdown.',
    'Keep official field names if they already exist: subject_definitions, summary, retention_analysis, detailed_description, integrated_multimodal_description, overall_soundscape, non_diegetic_music.',
    'Keep <Picture N>, <Video N>, <Audio N>, <Subject N>, <d>...</d> and [Shot 1] when they already exist.',
    'Do not invent a modern rapper, MC, hoodie performer or concert crowd unless the instruction asks for one.',
    'Do not add readable on-screen lyrics or captions.',
    shorten
      ? 'Tighten the visual body: cut filler and repeated identity, keep one camera move and the concrete action. Do not drop official fields or reference tags.'
      : '',
  ].filter(Boolean).join('\n')
}

export function extractRewrittenPrompt(text: string, fallback: string): string {
  let out = String(text || '').trim()
  const fence = out.match(/```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)```/)
  if (fence) out = fence[1].trim()
  out = out.replace(/^(?:rewritten prompt|prompt)\s*:\s*/i, '').trim()
  return out || fallback
}
