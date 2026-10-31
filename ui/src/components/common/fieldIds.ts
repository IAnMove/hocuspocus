import { useId } from 'react'

/** One id base per component instance. The suffix distinguishes fields, including rows in a list. */
export function useFieldIds() {
  const base = useId()
  return (suffix: string) => `${base}-${suffix}`
}
