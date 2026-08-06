/* Microphone capture for the recording studio.
 *
 * The browser's voice-processing features are all switched OFF deliberately.
 * echoCancellation, noiseSuppression and autoGainControl are tuned for phone
 * calls: they gate quiet passages, duck steady sounds they mistake for noise,
 * and ride the level between takes. A held /s/ is *exactly* what a noise
 * suppressor removes, and autoGain would make two takes of the same sound
 * incomparable - which would defeat the scoring that picks the best one.
 */
'use strict'

const Recorder = (() => {
  let ctx = null
  let node = null
  let source = null
  let stream = null
  let chunks = []
  let capturing = false

  async function init () {
    if (ctx) return
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        channelCount: 1
      }
    })
    ctx = new AudioContext()
    await ctx.audioWorklet.addModule('recorder-worklet.js')
    source = ctx.createMediaStreamSource(stream)
    node = new AudioWorkletNode(ctx, 'recorder-processor')
    node.port.onmessage = (e) => { if (capturing) chunks.push(e.data) }
    source.connect(node)
    // Not connected to the destination: monitoring would feed back through
    // the laptop speakers into the same microphone.
  }

  function start () {
    chunks = []
    capturing = true
    node.port.postMessage('start')
  }

  /** Stops and returns { b64, sampleRate, seconds, peak }. */
  function stop () {
    capturing = false
    if (node) node.port.postMessage('stop')
    let total = 0
    for (const c of chunks) total += c.length
    const flat = new Float32Array(total)
    let o = 0
    for (const c of chunks) { flat.set(c, o); o += c.length }
    chunks = []

    let peak = 0
    for (let i = 0; i < flat.length; i++) {
      const v = Math.abs(flat[i])
      if (v > peak) peak = v
    }

    // Base64 of the raw little-endian float bytes - the sidecar reads it back
    // with numpy directly, so nothing is re-encoded on the way.
    const bytes = new Uint8Array(flat.buffer)
    let bin = ''
    const STEP = 0x8000
    for (let i = 0; i < bytes.length; i += STEP) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + STEP))
    }
    return {
      b64: btoa(bin),
      sampleRate: ctx ? ctx.sampleRate : 48000,
      seconds: flat.length / (ctx ? ctx.sampleRate : 48000),
      peak
    }
  }

  /** Live input level 0..1, for the meter that shows the mic is working. */
  function level () {
    if (!chunks.length) return 0
    const last = chunks[chunks.length - 1]
    let s = 0
    for (let i = 0; i < last.length; i++) s += last[i] * last[i]
    return Math.min(1, Math.sqrt(s / last.length) * 4)
  }

  function release () {
    try {
      if (node) node.disconnect()
      if (source) source.disconnect()
      if (stream) stream.getTracks().forEach((t) => t.stop())
      if (ctx) ctx.close()
    } catch { /* nothing useful to do if teardown fails */ }
    ctx = node = source = stream = null
    chunks = []
    capturing = false
  }

  return { init, start, stop, level, release, ready: () => !!ctx }
})()
