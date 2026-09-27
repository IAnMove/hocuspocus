import assert from 'node:assert/strict'
import test from 'node:test'
import { importLrc, importLyricsText, importPlainLyrics, importSrt, importTimingBundle, parseSceneLyrics } from '../src/lib/kineticText.ts'

test('LRC and SRT imports keep word times and fill missing words by length', () => {
  const lrc = importLrc('[00:01.00] <00:01.00>Hello <00:01.50>world\n[00:03.00]Only a line', 1)
  assert.equal(lrc[0].start, 2)
  assert.equal(lrc[0].words[0].text, 'Hello')
  assert.equal(lrc[0].words[0].start, 2)
  assert.equal(lrc[0].words[1].start, 2.5)
  assert.equal(lrc[1].words.length, 3)
  assert.ok(lrc[1].words[2].end > lrc[1].words[0].start)
  const plain = importLrc('[00:00.00]Hi there', 0)
  assert.equal(plain[0].words.length, 2)
  const srt = importSrt('1\n00:00:01,000 --> 00:00:03,000\nHola mundo\n', 0.5)
  assert.equal(srt[0].start, 1.5)
  assert.equal(srt[0].end, 3.5)
  assert.equal(srt[0].words.length, 2)
  assert.ok(srt[0].words[1].end - srt[0].words[1].start >= srt[0].words[0].end - srt[0].words[0].start)
})

test('plain text, timing bundles and the scene cap stay bounded', () => {
  const plain = importPlainLyrics('one\ntwo', 4, 1)
  assert.equal(plain.length, 2)
  assert.equal(plain[0].start, 1)
  assert.equal(plain[1].end, 5)
  const bundle = importTimingBundle({ timeline: [{ text: 'Bird', start: 0, end: 1, words: [{ text: 'Bird', start: 0, end: 1 }] }] }, 2)
  assert.equal(bundle[0].words[0].start, 2)
  const capped = parseSceneLyrics({ mode: 'karaoke', lines: Array.from({ length: 500 }, (_, index) => ({ id: `l${index}`, start: index, end: index + 0.5, words: [{ text: 'a', start: index, end: index + 0.4 }] })), style: { font: 'sans', size: 7, color: '#ffffff', activeColor: '#ffdd88', x: 50, y: 80, maxWidth: 80, align: 'center', visibleLines: 1 } })
  assert.equal(capped?.lines.length, 400)
  assert.equal(capped?.mode, 'karaoke')
})

test('MiniMax section tags are not treated as LRC and do not become cues', () => {
  const tagged = '[Verse]\nI walk the line\n[Chorus]\nKeep the name'
  const previousHeuristic = tagged.includes('-->') ? importSrt(tagged, 0) : tagged.includes('[') ? importLrc(tagged, 0) : importPlainLyrics(tagged, 8, 0)
  assert.equal(previousHeuristic.length, 0)
  const imported = importLyricsText(tagged, 8, 0)
  assert.deepEqual(imported.map(line => line.words.map(word => word.text).join(' ')), ['I walk the line', 'Keep the name'])
  assert.equal(imported[0].start, 0)
  assert.equal(imported[1].end, 8)
  const scene = parseSceneLyrics({ mode: 'karaoke', lines: imported, style: { font: 'sans', size: 7, color: '#f4efe6', activeColor: '#ffe08a', x: 50, y: 78, maxWidth: 80, align: 'center', visibleLines: 2 } })
  assert.equal(scene?.lines.length, 2)
})

test('timestamped LRC and SRT still win over section tags in the same paste', () => {
  const lrc = importLyricsText('[ti:Harbour]\n[00:01.00]Hello world\n[00:03.00]Keep the name', 8, 0)
  assert.equal(lrc.length, 2)
  assert.equal(lrc[0].start, 1)
  assert.equal(lrc[0].words[0].text, 'Hello')
  const srt = importLyricsText('1\n00:00:01,000 --> 00:00:03,000\nHola mundo\n', 8, 0.5)
  assert.equal(srt[0].start, 1.5)
  assert.equal(srt[0].words.length, 2)
})
