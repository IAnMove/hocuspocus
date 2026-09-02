import { useSyncExternalStore } from 'react'
import type { CanonicalTask } from '../../api/client'

let snapshot: CanonicalTask[] = []
const listeners = new Set<() => void>()

export function publishCanonicalTasks(tasks: CanonicalTask[]): void {
  snapshot = tasks
  listeners.forEach(listener => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useCanonicalTaskFeed(): CanonicalTask[] {
  return useSyncExternalStore(subscribe, () => snapshot, () => snapshot)
}
