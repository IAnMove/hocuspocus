#!/usr/bin/env node

import { readFile, writeFile } from 'node:fs/promises'

function argument(name, fallback = '') {
  const index = process.argv.indexOf(`--${name}`)
  return index >= 0 ? String(process.argv[index + 1] || '') : fallback
}

const debugUrl = argument('debug-url').replace(/\/$/, '')
const pageUrl = argument('page-url')
const expression = argument('expression')
const scriptPath = argument('script')
const screenshotPath = argument('screenshot')
const method = argument('method')
const paramsText = argument('params', '{}')

if (!debugUrl) {
  throw new Error('--debug-url is required')
}
if (!expression && !scriptPath && !screenshotPath && !method) {
  throw new Error('Pass --expression, --script, --screenshot or --method')
}

const targetsResponse = await fetch(`${debugUrl}/json`)
if (!targetsResponse.ok) throw new Error(`CDP target discovery failed: HTTP ${targetsResponse.status}`)
const targets = await targetsResponse.json()
const target = targets.find(item => item.type === 'page' && (!pageUrl || item.url.startsWith(pageUrl)))
if (!target?.webSocketDebuggerUrl) throw new Error('No matching browser page was found')

const socket = new WebSocket(target.webSocketDebuggerUrl)
const pending = new Map()
let nextId = 1

socket.addEventListener('message', event => {
  const message = JSON.parse(String(event.data))
  const waiter = pending.get(message.id)
  if (!waiter) return
  pending.delete(message.id)
  if (message.error) waiter.reject(new Error(message.error.message || JSON.stringify(message.error)))
  else waiter.resolve(message.result)
})

await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true })
  socket.addEventListener('error', reject, { once: true })
})

function send(method, params = {}) {
  const id = nextId++
  socket.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
}

try {
  if (method) {
    const result = await send(method, JSON.parse(paramsText))
    console.log(JSON.stringify(result ?? null))
  } else if (screenshotPath) {
    const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
    await writeFile(screenshotPath, Buffer.from(result.data, 'base64'))
    console.log(JSON.stringify({ screenshot: screenshotPath }))
  } else {
    const source = scriptPath ? await readFile(scriptPath, 'utf8') : expression
    const result = await send('Runtime.evaluate', {
      expression: source,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    })
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text)
    }
    console.log(JSON.stringify(result.result?.value ?? null))
  }
} finally {
  socket.close()
}
