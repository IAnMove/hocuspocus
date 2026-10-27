import { controlLabel, firstControlReason } from './controlLabel'

/** The parent lock wins. Otherwise the first missing condition, in the order given. */
export function reasonAfterLock(
  panelDisabled: boolean,
  panelTitle: string | undefined,
  causes: ReadonlyArray<readonly [boolean | undefined, string]> = [],
) {
  if (panelDisabled) return panelTitle || controlLabel('disabled.panelLocked')
  return firstControlReason(causes)
}
