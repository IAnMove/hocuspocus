/* Runs inline in the sandboxed Video JS iframe. It owns the scene Worker so a
 * hung scene (infinite loop) can be terminated without freezing HocusPocus,
 * and relays frames to the parent as transferable ImageBitmaps. */
(() => {
  'use strict'
  const CHANNEL = 'hocuspocus-videojs'
  const LOAD_TIMEOUT_MS = 30000
  const FRAME_TIMEOUT_MS = 20000
  let worker = null
  let workerUrl = ''
  let parentOrigin = '*'
  let pending = null
  let activeScene = ''

  const reply = (message, transfer = []) => parent.postMessage({ channel: CHANNEL, ...message }, parentOrigin, transfer)

  function stopWorker() {
    if (worker) worker.terminate()
    if (workerUrl) URL.revokeObjectURL(workerUrl)
    worker = null
    workerUrl = ''
  }

  function settle(message, transfer) {
    if (!pending) return
    clearTimeout(pending.timer)
    reply({ ...message, id: pending.id }, transfer)
    pending = null
  }

  function arm(id, timeout) {
    pending = {
      id,
      timer: setTimeout(() => {
        stopWorker()
        settle({ type: 'fatal', error: { sceneId: activeScene, phase: 'timeout', message: 'The scene did not finish in time (infinite loop or too heavy). The sandbox was stopped.' } })
      }, timeout),
    }
  }

  function onWorkerMessage(event) {
    const message = event.data || {}
    if (message.type === 'begin') activeScene = String(message.sceneId || '')
    else if (message.type === 'ready') settle({ type: 'loaded', errors: message.errors || [] })
    else if (message.type === 'frame') settle({ type: 'frame', bitmap: message.bitmap, errors: message.errors || [] }, [message.bitmap])
    else if (message.type === 'fatal') settle({ type: 'fatal', error: message.error })
  }

  function load(message) {
    stopWorker()
    workerUrl = URL.createObjectURL(new Blob([message.runtime], { type: 'text/javascript' }))
    worker = new Worker(workerUrl)
    worker.onmessage = onWorkerMessage
    worker.onerror = event => {
      event.preventDefault()
      stopWorker()
      settle({ type: 'fatal', error: { sceneId: activeScene, phase: 'runtime', message: event.message || 'Scene worker failed' } })
    }
    arm(message.id, LOAD_TIMEOUT_MS)
    worker.postMessage({ type: 'init', document: message.document, three: message.three || null })
  }

  window.addEventListener('message', event => {
    const message = event.data
    if (event.source !== parent || !message || message.channel !== CHANNEL) return
    parentOrigin = event.origin && event.origin !== 'null' ? event.origin : '*'
    if (pending) {
      reply({ type: 'fatal', id: message.id, error: { sceneId: '', phase: 'runtime', message: 'Sandbox is busy' } })
      return
    }
    if (message.type === 'load') load(message)
    else if (message.type === 'frame' && worker) {
      arm(message.id, FRAME_TIMEOUT_MS)
      worker.postMessage({ type: 'frame', id: message.id, time: message.time })
    } else reply({ type: 'fatal', id: message.id, error: { sceneId: '', phase: 'runtime', message: 'Sandbox is not loaded' } })
  })
  reply({ type: 'boot' })
})()
