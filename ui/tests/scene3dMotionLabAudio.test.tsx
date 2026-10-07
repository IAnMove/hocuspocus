import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { applyScene3DTemplate } from '../src/features/scene3d/templates'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  MutationObserver: dom.window.MutationObserver, getComputedStyle: dom.window.getComputedStyle })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

class FakeSource {
  buffer: AudioBuffer | null = null
  playbackRate = { value: 1 }
  onended: (() => void) | null = null
  starts: number[][] = []
  stopped = 0
  connect() {}
  disconnect() {}
  start(...args: number[]) { this.starts.push(args) }
  stop() { this.stopped++ }
}
class FakeContext {
  static instances: FakeContext[] = []
  static rejectResume = false
  sampleRate = 32 // Test the real scheduling path with cheap PCM buffers.
  currentTime = 0
  destination = {}
  sources: FakeSource[] = []
  closed = 0
  constructor() { FakeContext.instances.push(this) }
  async resume() { if (FakeContext.rejectResume) throw new Error('Autoplay blocked') }
  async close() { this.closed++ }
  createBuffer(channels: number, length: number, rate: number) {
    const samples = new Float32Array(length)
    return { getChannelData: () => samples, numberOfChannels: channels, length, sampleRate: rate, duration: length / rate }
  }
  createBufferSource() {
    const source = new FakeSource()
    this.sources.push(source)
    return source
  }
}
function installAudio() {
  FakeContext.instances = []; FakeContext.rejectResume = false
  const original = Object.getOwnPropertyDescriptor(globalThis, 'AudioContext')
  Object.defineProperty(globalThis, 'AudioContext', { configurable: true, value: FakeContext })
  return () => {
    if (original) Object.defineProperty(globalThis, 'AudioContext', original)
    else Reflect.deleteProperty(globalThis, 'AudioContext')
  }
}

test('preview reuses its context and starts a fresh tape for every transport loop', async () => {
  const { render, act, cleanup } = await import('@testing-library/react')
  const { MotionLabAudio } = await import('../src/features/scene3d/motionlab/previewAudio')
  const restore = installAudio(), document = { ...applyScene3DTemplate('motion-bouncing-ball'), duration: 16 }
  try {
    const view = render(<MotionLabAudio document={document} seconds={15.9} playing speed={2} />)
    await act(async () => {})
    const context = FakeContext.instances[0]
    assert.equal(context.sources.length, 1)
    assert.ok(Math.abs(context.sources[0].starts[0][2] - .1) < 1e-9)
    for (let cycle = 1; cycle <= 3; cycle++) {
      view.rerender(<MotionLabAudio document={document} seconds={0} playing speed={2} />)
      assert.equal(FakeContext.instances.length, 1)
      assert.equal(context.sources.length, cycle + 1)
      assert.equal(context.sources[cycle - 1].stopped, 1)
      assert.deepEqual(context.sources[cycle].starts, [[0, 0, 16]])
      assert.equal(context.sources[cycle].playbackRate.value, 2)
      view.rerender(<MotionLabAudio document={document} seconds={15.9} playing speed={2} />)
      assert.equal(context.sources.length, cycle + 1, 'ordinary progress does not allocate another tape')
    }
    view.unmount()
    assert.equal(context.closed, 1)
    assert.equal(context.sources.at(-1)?.stopped, 1)
  } finally { cleanup(); restore() }
})

test('paused/read-only views and muted or nonmusical sets never open audio; muting closes playback', async () => {
  const { render, act, cleanup } = await import('@testing-library/react')
  const { MotionLabAudio } = await import('../src/features/scene3d/motionlab/previewAudio')
  const restore = installAudio(), document = applyScene3DTemplate('motion-music-machine')
  try {
    const view = render(<MotionLabAudio document={document} seconds={0} playing={false} speed={1} />)
    const muted = { ...document, motionLab: { ...document.motionLab!, sound: false } }
    const zeroVolume = { ...document, motionLab: { ...document.motionLab!, volume: 0 } }
    for (const silent of [muted, zeroVolume, applyScene3DTemplate('motion-sunset-flight')]) {
      view.rerender(<MotionLabAudio document={silent} seconds={0} playing speed={1} />)
    }
    assert.equal(FakeContext.instances.length, 0)
    view.rerender(<MotionLabAudio document={document} seconds={0} playing speed={1} />)
    await act(async () => {})
    const context = FakeContext.instances[0]
    assert.equal(context.sources.length, 1)
    view.rerender(<MotionLabAudio document={muted} seconds={.5} playing speed={1} />)
    assert.equal(context.sources[0].stopped, 1)
    assert.equal(context.closed, 1)
    assert.equal(FakeContext.instances.length, 1)
  } finally { cleanup(); restore() }
})

test('a blocked resume schedules no sound, hides on pause, and clears after a successful retry', async () => {
  const { render, act, cleanup } = await import('@testing-library/react')
  const { MotionLabAudio } = await import('../src/features/scene3d/motionlab/previewAudio')
  const restore = installAudio(), document = applyScene3DTemplate('motion-bouncing-ball')
  FakeContext.rejectResume = true
  try {
    const view = render(<MotionLabAudio document={document} seconds={0} playing speed={1} />)
    await act(async () => {})
    assert.ok(view.queryByRole('alert'))
    assert.equal(FakeContext.instances[0].sources.length, 0)
    view.rerender(<MotionLabAudio document={document} seconds={0} playing={false} speed={1} />)
    assert.equal(view.queryByRole('alert'), null)
    assert.equal(FakeContext.instances[0].closed, 1)
    FakeContext.rejectResume = false
    view.rerender(<MotionLabAudio document={document} seconds={1} playing speed={1} />)
    await act(async () => {})
    assert.equal(view.queryByRole('alert'), null)
    assert.equal(FakeContext.instances[1].sources.length, 1)
    assert.equal(FakeContext.instances[1].sources[0].starts[0][2], document.duration - 1)
  } finally { cleanup(); restore() }
})

test('export mixes original local music without voice tracks, clips at output time and respects silence and duration gates', async () => {
  const { mixSceneSpeech } = await import('../src/features/scene3d/speech/audio')
  const original = Object.getOwnPropertyDescriptor(globalThis, 'OfflineAudioContext')
  class FakeOfflineContext extends FakeContext {
    constructor(public channels: number, public length: number, public outputRate: number) { super() }
    async startRendering() { return { duration: this.length / this.outputRate, numberOfChannels: this.channels } }
  }
  Object.defineProperty(globalThis, 'OfflineAudioContext', { configurable: true, value: FakeOfflineContext })
  FakeContext.instances = []
  const document = { ...applyScene3DTemplate('motion-music-machine'), duration: 600, playbackSpeed: 4 }
  try {
    const buffer = await mixSceneSpeech(document)
    assert.equal(buffer?.duration, 150)
    assert.equal(buffer?.numberOfChannels, 2)
    const context = FakeContext.instances[0]
    assert.equal(context.sources.length, 1)
    assert.equal(context.sources[0].playbackRate.value, 4)
    assert.deepEqual(context.sources[0].starts, [[0, 0, 600]])
    assert.ok(context.sources[0].buffer!.getChannelData(0).some(sample => sample !== 0))
    for (const motionLab of [{ ...document.motionLab!, sound: false }, { ...document.motionLab!, volume: 0 }]) {
      assert.equal(await mixSceneSpeech({ ...document, motionLab }), undefined)
    }
    assert.equal(FakeContext.instances.length, 1, 'silent export allocates no context')
    await assert.rejects(mixSceneSpeech({ ...document, playbackSpeed: 1 }), /180/)
    assert.equal(FakeContext.instances.length, 1, 'oversized audible export fails before allocating')
  } finally {
    if (original) Object.defineProperty(globalThis, 'OfflineAudioContext', original)
    else Reflect.deleteProperty(globalThis, 'OfflineAudioContext')
  }
})
