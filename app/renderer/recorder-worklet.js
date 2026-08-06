/* Captures raw Float32 PCM from the microphone.
 *
 * An AudioWorklet rather than MediaRecorder, because MediaRecorder only gives
 * compressed audio (Opus/webm). These clips are the primary audio a child will
 * hear thousands of times, and a held /s/ is broadband noise - exactly what a
 * lossy codec models worst. Capturing raw PCM avoids the question entirely.
 *
 * ScriptProcessorNode would have been simpler but runs on the main thread and
 * glitches under load; the worklet runs on the audio thread.
 */
class RecorderProcessor extends AudioWorkletProcessor {
  constructor () {
    super()
    this.recording = false
    this.port.onmessage = (e) => {
      if (e.data === 'start') this.recording = true
      else if (e.data === 'stop') this.recording = false
    }
  }

  process (inputs) {
    const input = inputs[0]
    if (this.recording && input && input[0]) {
      // Copy: the buffer is reused by the audio thread after this returns.
      this.port.postMessage(new Float32Array(input[0]))
    }
    return true
  }
}

registerProcessor('recorder-processor', RecorderProcessor)
