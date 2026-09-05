export interface KeyedWriteSequencer {
  enqueue: (key: string, write: () => Promise<unknown>) => Promise<void>
  hasPending: (key: string) => boolean
}

/** Serialize durable writes for one logical record without blocking others. */
export function createKeyedWriteSequencer(): KeyedWriteSequencer {
  const tails = new Map<string, Promise<void>>()

  const enqueue = (key: string, write: () => Promise<unknown>): Promise<void> => {
    const previous = tails.get(key) || Promise.resolve()
    const operation = previous
      .catch(() => undefined)
      .then(async () => { await write() })
    const tracked = operation.finally(() => {
      if (tails.get(key) === tracked) tails.delete(key)
    })
    tails.set(key, tracked)
    return tracked
  }

  return {
    enqueue,
    hasPending: key => tails.has(key),
  }
}
