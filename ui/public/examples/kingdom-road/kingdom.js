const key = 'hocuspocus:kingdom-road:v1'
let notes = {}
try { notes = JSON.parse(localStorage.getItem(key) || '{}') || {} } catch { /* Export remains available. */ }
if (typeof notes !== 'object' || Array.isArray(notes)) notes = {}
for (const field of document.querySelectorAll('[data-rating]')) {
  const id = field.dataset.rating, textarea = field.querySelector('textarea')
  textarea.value = typeof notes[id]?.note === 'string' ? notes[id].note : ''
  const refresh = () => { for (const b of field.querySelectorAll('[data-value]')) b.setAttribute('aria-pressed', String(notes[id]?.rating === b.dataset.value)) }
  const save = () => {
    try { localStorage.setItem(key, JSON.stringify(notes)) }
    catch { document.getElementById('status').textContent = 'Descarga tus valoraciones: este navegador no permite guardarlas.' }
    refresh()
  }
  for (const button of field.querySelectorAll('[data-value]')) button.addEventListener('click', () => {
    notes[id] = { ...notes[id], rating: notes[id]?.rating === button.dataset.value ? '' : button.dataset.value }
    save()
  })
  textarea.addEventListener('input', () => { notes[id] = { ...notes[id], note: textarea.value }; save() })
  refresh()
}
for (const video of document.querySelectorAll('video')) video.addEventListener('play', () => {
  for (const other of document.querySelectorAll('video')) if (other !== video) other.pause()
})
for (const button of document.querySelectorAll('[data-fullscreen]')) button.addEventListener('click', async () => {
  const video = document.getElementById(button.dataset.fullscreen)
  try {
    if (video.requestFullscreen) await video.requestFullscreen()
    else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen()
    else video.scrollIntoView({ block: 'center' })
  } catch { video.scrollIntoView({ block: 'center' }) }
})
document.getElementById('export-notes').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify({ collection: 'kingdom-road', notes }, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = 'mis-valoraciones-reinos.json'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
})
