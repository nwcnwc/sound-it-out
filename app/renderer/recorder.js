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
  let sink = null
  let analyser = null
  let probe = null
  let blocks = []
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
    node.port.onmessage = (e) => { if (capturing) blocks.push(e.data) }

    // The worklet MUST reach the destination or the graph never pulls audio
    // through it and process() is not called - which records pure silence.
    // Routing through a muted gain keeps it live without monitoring, which
    // would otherwise feed the laptop speakers back into the microphone.
    sink = ctx.createGain()
    sink.gain.value = 0
    source.connect(node)
    node.connect(sink)
    sink.connect(ctx.destination)

    // A separate analyser so the level meter works before and between takes,
    // not only while capturing. Without it there is no way to see the
    // microphone is alive until after committing to a recording.
    analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    probe = new Float32Array(analyser.fftSize)
    source.connect(analyser)
  }

  function start () {
    blocks = []
    capturing = true
    node.port.postMessage('start')
  }

  /* Pause keeps what has been captured so far, unlike start(). Reading a six
   * minute passage in one go is not realistic with a child in the house, so
   * the passage recorder pauses and carries on into the same take. */
  function pause () { capturing = false; if (node) node.port.postMessage('stop') }
  function resume () { capturing = true; if (node) node.port.postMessage('start') }
  function seconds () {
    let n = 0
    for (const c of blocks) n += c.length
    return n / (ctx ? ctx.sampleRate : 48000)
  }

  /** Stops and returns { b64, sampleRate, seconds, peak }. */
  function stop () {
    capturing = false
    if (node) node.port.postMessage('stop')
    let total = 0
    for (const c of blocks) total += c.length
    const flat = new Float32Array(total)
    let o = 0
    for (const c of blocks) { flat.set(c, o); o += c.length }
    blocks = []

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

  /** Live input level 0..1. Reads the analyser, so it works whether or not a
   *  take is in progress - that is what makes a microphone check possible. */
  function level () {
    if (!analyser) return 0
    analyser.getFloatTimeDomainData(probe)
    let s = 0
    for (let i = 0; i < probe.length; i++) s += probe[i] * probe[i]
    return Math.min(1, Math.sqrt(s / probe.length) * 4)
  }

  function release () {
    try {
      if (node) node.disconnect()
      if (sink) sink.disconnect()
      if (analyser) analyser.disconnect()
      if (source) source.disconnect()
      if (stream) stream.getTracks().forEach((t) => t.stop())
      if (ctx) ctx.close()
    } catch { /* nothing useful to do if teardown fails */ }
    ctx = node = source = stream = sink = analyser = probe = null
    blocks = []
    capturing = false
  }

  return { init, start, stop, pause, resume, seconds, level, release, ready: () => !!ctx }
})()
