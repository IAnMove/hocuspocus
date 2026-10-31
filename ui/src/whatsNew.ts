/**
 * Newest first. One short line per user-facing change since 5 October 2026.
 * Bump WHATS_NEW_MIN_PR when the first entry changes. The test fails when the
 * newest line falls behind that number.
 */
export const WHATS_NEW_MIN_PR = 1204

export const WHATS_NEW = [
  { pr: 1204, key: 'welcome.lines.pr1204' },
  { pr: 1201, key: 'welcome.lines.pr1201' },
  { pr: 1178, key: 'welcome.lines.pr1178' },
  { pr: 1172, key: 'welcome.lines.pr1172' },
  { pr: 1170, key: 'welcome.lines.pr1170' },
  { pr: 1169, key: 'welcome.lines.pr1169' },
  { pr: 1168, key: 'welcome.lines.pr1168' },
  { pr: 1167, key: 'welcome.lines.pr1167' },
  { pr: 1163, key: 'welcome.lines.pr1163' },
  { pr: 1157, key: 'welcome.lines.pr1157' },
  { pr: 1152, key: 'welcome.lines.pr1152' },
  { pr: 961, key: 'welcome.lines.pr961' },
] as const

export const WELCOME_SEEN_KEY = 'hocuspocus_welcome_seen_v2'

export function latestWhatsNewPr(): number {
  return WHATS_NEW[0]?.pr ?? 0
}
