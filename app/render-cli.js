'use strict'
/**
 * Headless frame-rendering entry point.
 *
 *   electron app/render-cli.js <jobDir>
 *
 * Reads <jobDir>/frames.json  ->  [{id, html}, ...]
 * Writes <jobDir>/frames/<id>.png
 * Emits one JSON line per progress tick on stdout so the Python side can
 * report progress without a second IPC channel.
 *
 * This is how the pipeline renders frames both in development and inside the
 * packaged app - same Chromium either way.
 */

const { app } = require('electron')
const fs = require('fs/promises')
const path = require('path')
const { renderFrames } = require('./frames')

// A GPU is neither available nor useful for rasterising static text, and
// disabling it avoids a class of headless/CI failures.
app.disableHardwareAcceleration()
app.commandLine.appendSwitch('disable-gpu')
app.commandLine.appendSwitch('no-sandbox')
// Chromium allocates shared memory in /dev/shm, which is unavailable or too
// small in most containers and CI runners - it aborts on startup without this.
// Harmless elsewhere; this entry point is only ever used headlessly.
app.commandLine.appendSwitch('disable-dev-shm-usage')
if (process.env.SIO_SINGLE_PROCESS) app.commandLine.appendSwitch('single-process')

function emit (obj) {
  process.stdout.write(JSON.stringify(obj) + '\n')
}

app.whenReady().then(async () => {
  const jobDir = process.argv[process.argv.length - 1]
  try {
    const frames = JSON.parse(
      await fs.readFile(path.join(jobDir, 'frames.json'), 'utf8')
    )
    const outDir = path.join(jobDir, 'frames')
    const written = await renderFrames(frames, outDir, {
      onProgress: (done, total) => emit({ event: 'progress', done, total })
    })
    emit({ event: 'done', count: written.length })
    app.exit(0)
  } catch (err) {
    emit({ event: 'error', message: String(err && err.stack || err) })
    app.exit(1)
  }
})
