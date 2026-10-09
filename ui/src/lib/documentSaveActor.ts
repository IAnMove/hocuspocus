// A Wizard scene action saves through the same fetch as a person. The depth is set only while that
// action's listener is running, so a later save from the editor stays a person's save.

let depth = 0

export function documentSaveHeaders(): Record<string, string> {
  return depth > 0 ? { 'X-Hocus-UI-Surface': 'wizard' } : {}
}

export async function wizardDocumentSave<T>(run: () => Promise<T>): Promise<T> {
  depth += 1
  try {
    return await run()
  } finally {
    depth -= 1
  }
}
