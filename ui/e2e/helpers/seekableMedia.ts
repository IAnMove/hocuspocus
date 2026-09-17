import type { Route } from '@playwright/test'

/** Serve a full media file including Chrome Range requests so currentTime/seeked work. */
export function fulfillSeekable(body: Buffer, contentType: string) {
  return (route: Route) => {
    const total = body.length
    const match = route.request().headers().range?.match(/^bytes=(\d+)-(\d*)$/i)
    const headers: Record<string, string> = { 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store' }
    if (!match) {
      return route.fulfill({ status: 200, contentType, headers: { ...headers, 'Content-Length': String(total) }, body })
    }
    const start = Math.min(Number(match[1]), total)
    const end = match[2] === '' ? Math.max(0, total - 1) : Math.min(Number(match[2]), Math.max(0, total - 1))
    if (start >= total || start > end) {
      return route.fulfill({ status: 416, headers: { ...headers, 'Content-Range': `bytes */${total}` }, body: Buffer.alloc(0) })
    }
    const slice = body.subarray(start, end + 1)
    return route.fulfill({
      status: 206,
      contentType,
      headers: { ...headers, 'Content-Range': `bytes ${start}-${end}/${total}`, 'Content-Length': String(slice.length) },
      body: slice,
    })
  }
}
