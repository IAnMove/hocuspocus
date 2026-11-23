import { runBatch } from './imageBatch'

type Snapshot = { busy: boolean; stopping: boolean; status: string; archive?: Blob }

let snapshot: Snapshot = { busy: false, stopping: false, status: '' }
let controller: AbortController | undefined
const listeners = new Set<() => void>()

function update(changes: Partial<Snapshot>) {
  snapshot = { ...snapshot, ...changes }
  listeners.forEach(listener => listener())
}

export function getImageBatchSession() {
  return snapshot
}

export function subscribeImageBatchSession(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export async function startImageBatch(file: File) {
  if (controller) return
  const run = new AbortController()
  controller = run
  update({ busy: true, archive: undefined, status: 'Importando ZIP…' })
  try {
    const { archive, done, total, cancelled } = await runBatch(file, status => update({ status }), run.signal)
    update({
      archive,
      status: `${done} de ${total} imágenes generadas · ${total - done - cancelled} fallidas${cancelled ? ` · ${cancelled} canceladas` : ''}`,
    })
  } catch (error) {
    update({ status: run.signal.aborted ? 'Lote cancelado' : error instanceof Error ? error.message : String(error) })
  } finally {
    controller = undefined
    update({ busy: false, stopping: false })
  }
}

export function stopImageBatch() {
  if (!controller || snapshot.stopping) return
  controller.abort()
  update({ stopping: true, status: 'Cancelando lote…' })
}
