const key = document.body.dataset.reviewKey || 'hocuspocus:perspective-review:v1'
const $ = id => document.getElementById(id)
const ratings = [['keep', 'Me encanta'], ['refine', 'Retocar'], ['discard', 'Descartar']]
let notes = {}, items = [], current = 0
try { notes = JSON.parse(localStorage.getItem(key) || '{}') || {} } catch { /* Export still works without storage. */ }
if (typeof notes !== 'object' || Array.isArray(notes)) notes = {}

function persist() {
  try { localStorage.setItem(key, JSON.stringify(notes)) }
  catch { $('storage').textContent = 'No se puede guardar en este navegador. Descarga tus valoraciones antes de cerrar la página.' }
  refresh()
}
function refresh() {
  let visible = 0
  for (const item of items) {
    const card = document.getElementById(item.id), rating = notes[item.id]?.rating || 'pending'
    card.dataset.rating = rating
    card.hidden = ($('filter').value !== 'all' && $('filter').value !== rating)
      || ($('style').value !== 'all' && $('style').value !== item.psx)
    if (card.hidden) card.querySelector('video').pause()
    else visible++
    for (const button of card.querySelectorAll('.ratings button')) button.setAttribute('aria-pressed', String(button.dataset.value === rating))
  }
  const reviewed = items.filter(item => ratings.some(([id]) => id === notes[item.id]?.rating)).length
  $('progress').textContent = `${reviewed} / ${items.length} evaluadas · ${visible} visibles`
  $('empty').hidden = visible > 0
}
function pauseOthers(active) { for (const video of document.querySelectorAll('video')) if (video !== active) video.pause() }
function watch(index) {
  current = (index + items.length) % items.length
  const item = items[current], video = $('large-video')
  pauseOthers(video)
  $('viewer-title').textContent = item.title
  $('viewer-count').textContent = `${current + 1} / ${items.length}`
  video.poster = item.poster; video.src = item.video
  if (!$('viewer').open) $('viewer').showModal()
  void video.play().catch(() => {})
}
function node(tag, className, text) {
  const element = document.createElement(tag)
  if (className) element.className = className
  if (text !== undefined) element.textContent = text
  return element
}
function card(item, index) {
  const article = node('article', 'card'); article.id = item.id
  const picture = node('div', 'picture'), video = node('video')
  video.controls = true; video.loop = true; video.playsInline = true; video.preload = 'none'
  video.poster = item.poster; video.src = item.video; video.setAttribute('aria-label', `Reproducir ${item.title}`)
  video.addEventListener('play', () => pauseOthers(video))
  video.addEventListener('error', () => { picture.querySelector('.number').textContent = 'Vídeo no disponible'; })
  picture.append(video, node('span', 'number', `${String(item.number).padStart(2, '0')} / ${item.duration} s`))
  const body = node('div', 'card-body'), title = node('div', 'title-row'), palette = node('span', 'palette')
  palette.setAttribute('aria-hidden', 'true')
  for (const color of item.colors) { const dot = node('i'); dot.style.backgroundColor = color; palette.append(dot) }
  title.append(node('h2', '', item.title), palette)
  body.append(title, node('p', 'tag', `PSX · ${item.psx}`), node('p', 'description', item.description))
  const actions = node('div', 'actions'), expand = node('button', '', 'Ver en grande ↗'), scene = node('a', '', 'Descargar plano ↓')
  expand.addEventListener('click', () => watch(index)); scene.href = item.scene; scene.download = ''
  actions.append(expand, scene); body.append(actions)
  if (item.backgroundVideo && item.staticLayer) {
    const layers = node('div', 'actions')
    for (const [label, url] of [['Solo vídeo exterior ↗', item.backgroundVideo], ['Imagen estática ↗', item.staticLayer]]) {
      const link = node('a', '', label); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; layers.append(link)
    }
    body.append(layers)
  }
  const choices = node('div', 'ratings'); choices.setAttribute('role', 'group'); choices.setAttribute('aria-label', `Valorar ${item.title}`)
  for (const [value, label] of ratings) {
    const button = node('button', '', label); button.dataset.value = value
    button.addEventListener('click', () => {
      notes[item.id] = { ...notes[item.id], rating: notes[item.id]?.rating === value ? 'pending' : value, updatedAt: new Date().toISOString() }
      persist()
    }); choices.append(button)
  }
  const label = node('label', 'note-label', 'Qué conservarías o cambiarías'), textarea = node('textarea')
  textarea.maxLength = 4000; textarea.rows = 2; textarea.placeholder = 'La cámara, el contraste, una pieza…'
  textarea.value = typeof notes[item.id]?.note === 'string' ? notes[item.id].note : ''
  textarea.addEventListener('input', () => { notes[item.id] = { ...notes[item.id], note: textarea.value, updatedAt: new Date().toISOString() }; persist() })
  label.append(textarea)
  const template = node('a', 'template-link', 'Plantilla reutilizable ↓'); template.href = item.template; template.download = ''
  body.append(choices, label, template); article.append(picture, body)
  return article
}
$('filter').addEventListener('change', refresh); $('style').addEventListener('change', refresh)
$('export').addEventListener('click', () => {
  const report = { collection: document.body.dataset.collection || 'hocuspocus-perspectives-20260915', version: 1, exportedAt: new Date().toISOString(),
    items: items.map(item => ({ id: item.id, title: item.title, rating: notes[item.id]?.rating || 'pending', note: notes[item.id]?.note || '', updatedAt: notes[item.id]?.updatedAt })) }
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))
  const link = node('a'); link.href = url; link.download = document.body.dataset.reportFilename || 'mis-valoraciones-perspectivas.json'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
})
$('close').addEventListener('click', () => $('viewer').close())
$('viewer').addEventListener('close', () => { $('large-video').pause(); $('large-video').removeAttribute('src'); $('large-video').load() })
$('large-video').addEventListener('play', () => pauseOthers($('large-video')))
$('ocean-video')?.addEventListener('play', () => pauseOthers($('ocean-video')))
$('previous').addEventListener('click', () => watch(current - 1)); $('next').addEventListener('click', () => watch(current + 1))
document.addEventListener('visibilitychange', () => { if (document.hidden) pauseOthers(null) })
try {
  const response = await fetch('collection.json')
  if (!response.ok) throw new Error('collection unavailable')
  items = (await response.json()).items
  $('grid').replaceChildren(...items.map(card)); refresh()
} catch { $('progress').textContent = 'No se pudo cargar la colección. Recarga la página.' }
