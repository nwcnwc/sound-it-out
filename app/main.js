'use strict'
/**
 * Electron main process.
 *
 * Orchestrates a three-phase generation, splitting the work between the two
 * runtimes along the line each is actually good at:
 *
 *   1. plan   (Python)   audio synthesis, storyboard, timing
 *   2. frames (Electron) HTML -> PNG, using this app's own Chromium
 *   3. encode (Python)   ffmpeg mux
 *
 * Phase 2 lives here specifically so the packaged app has no dependency on an
 * external Chrome, and so a frame renders identically on macOS, Windows and
 * Linux - every install ships the same Chromium build. For an app whose whole
 * job is precisely-rendered letterforms, that consistency is the point.
 */

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron')
const path = require('path')
const fs = require('fs')
const os = require('os')
const { Sidecar } = require('./sidecar')
const { renderFrames } = require('./frames')

const APP_ROOT = path.join(__dirname, '..')
const isPackaged = app.isPackaged

// Chromium needs shared memory that containers and CI runners often deny.
// Harmless on a normal desktop.
app.commandLine.appendSwitch('disable-dev-shm-usage')

let win = null
let player = null
let sidecar = null
const jobs = new Map() // jobId -> {cancelled}

function userDataFile (name) {
  const d = app.getPath('userData')
  fs.mkdirSync(d, { recursive: true })
  return path.join(d, name)
}

function readSettings () {
  try {
    return JSON.parse(fs.readFileSync(userDataFile('settings.json'), 'utf8'))
  } catch {
    return {}   // absent or corrupt settings must never block startup
  }
}

function writeSettings (patch) {
  const next = { ...readSettings(), ...patch }
  fs.writeFileSync(userDataFile('settings.json'), JSON.stringify(next, null, 2))
  return next
}

function outputDir () {
  const d = readSettings().outputDir || path.join(os.homedir(), 'Sound It Out')
  try {
    fs.mkdirSync(d, { recursive: true })
    return d
  } catch {
    // A saved folder can vanish (external drive, renamed). Fall back rather
    // than failing every generation from then on.
    const home = path.join(os.homedir(), 'Sound It Out')
    fs.mkdirSync(home, { recursive: true })
    return home
  }
}

function createWindow () {
  win = new BrowserWindow({
    width: 1100,
    height: 820,
    minWidth: 900,
    minHeight: 680,
    title: 'Sound It Out',
    backgroundColor: '#faf7f2',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false // preload needs require(); the renderer stays isolated
    }
  })
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'))
  win.on('closed', () => { win = null })
}

function send (channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload)
}

// ------------------------------------------------------------------ jobs

async function runJob (opts) {
  const jobId = String(Date.now())
  jobs.set(jobId, { cancelled: false })
  const state = jobs.get(jobId)
  const check = () => { if (state.cancelled) throw new Error('CANCELLED') }

  ;(async () => {
    try {
      // 1. Python: synthesis + storyboard
      const plan = await sidecar.call('plan', {
        jobId,
        level: opts.level,
        theme: opts.theme,
        options: opts
      })
      check()

      // 2. Electron: rasterise the frames
      const jobDir = plan.jobDir
      const frames = JSON.parse(
        fs.readFileSync(path.join(jobDir, 'frames.json'), 'utf8')
      )
      send('job:progress', {
        jobId, stage: 'frames', done: 0, total: frames.length,
        message: 'Drawing the words...'
      })
      try {
        await renderFrames(frames, path.join(jobDir, 'frames'), {
          onProgress: (done, total) => {
            check()
            send('job:progress', {
              jobId, stage: 'frames', done, total, message: 'Drawing the words...'
            })
          }
        })
      } catch (err) {
        if (String(err.message) === 'CANCELLED') throw err
        // Chromium's renderer cannot start in some constrained environments
        // (containers that intercept syscalls, locked-down /dev/shm). Rather
        // than fail the whole video, hand the same HTML to the Python side,
        // which drives an external Chrome. Identical markup, identical output.
        console.warn('[frames] built-in renderer failed, falling back:', err.message)
        send('job:progress', {
          jobId, stage: 'frames', done: 0, total: frames.length,
          message: 'Drawing the words...'
        })
        await sidecar.call('render.chrome', { jobId })
      }
      check()

      // 3. Python: mux
      const name = `sound-it-out-level${opts.level}-${opts.theme}.mp4`
      const output = path.join(opts.outputDir || outputDir(), name)
      await sidecar.call('encode', { jobId, output })
      check()

      send('job:done', { jobId, output, voice: plan.voice })
      if (opts.mode === 'play') openPlayer(output)
    } catch (err) {
      if (String(err.message) === 'CANCELLED') {
        send('job:error', { jobId, message: 'Stopped.', hint: '' })
      } else {
        send('job:error', {
          jobId,
          message: err.message || 'Something went wrong making the video.',
          hint: 'If this keeps happening, try a shorter video or fewer words.'
        })
      }
    } finally {
      jobs.delete(jobId)
    }
  })()

  return { jobId }
}

// --------------------------------------------------------------- player

function openPlayer (file) {
  if (player && !player.isDestroyed()) player.destroy()
  player = new BrowserWindow({
    fullscreen: true,
    backgroundColor: '#000000',
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false }
  })
  // Loops forever with no controls and no chrome - it is meant to be left
  // running on a TV, not operated.
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;height:100%;background:#000;overflow:hidden}
    video{width:100%;height:100%;object-fit:contain;display:block}
  </style></head><body>
    <video src="file://${file.replace(/\\/g, '/')}" autoplay loop playsinline></video>
    <script>
      document.addEventListener('keydown', e => {
        if (e.key === 'Escape') window.close()
      })
    </script></body></html>`
  player.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html))
  player.on('closed', () => { player = null })
}

// ------------------------------------------------------------------ ipc

function registerIpc () {
  ipcMain.handle('state:get', async () => {
    const caps = await sidecar.call('capabilities')
    const wl = await sidecar.call('wordlist.load')
    return {
      levels: caps.levels,
      capabilities: caps.capabilities,
      themes: [
        { id: 'night', name: 'Night', bg: '#0d1b2a', fg: '#f8f4e9', hl: '#ffd166' },
        { id: 'paper', name: 'Paper', bg: '#fdfaf3', fg: '#2b2b2b', hl: '#d62828' },
        { id: 'contrast', name: 'High contrast', bg: '#000000', fg: '#ffffff', hl: '#4cc9f0' }
      ],
      wordlistText: wl.text,
      groups: wl.groups,
      outputDir: outputDir(),
      settings: readSettings()
    }
  })

  ipcMain.handle('settings:save', (_e, patch) => {
    try {
      return { ok: true, settings: writeSettings(patch || {}) }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })

  ipcMain.handle('wordlist:save', async (_e, text) => {
    try {
      const r = await sidecar.call('wordlist.save', { text })
      return { ok: true, groups: r.groups }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })

  ipcMain.handle('job:generate', (_e, opts) => runJob(opts || {}))

  ipcMain.handle('job:cancel', (_e, jobId) => {
    const j = jobs.get(String(jobId))
    if (j) j.cancelled = true
    return { ok: true }
  })

  ipcMain.handle('cloning:install', async () => {
    try {
      await sidecar.call('cloning.install')
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })

  ipcMain.handle('path:open', (_e, p) => { shell.openPath(p); return { ok: true } })

  ipcMain.handle('dir:choose', async () => {
    const r = await dialog.showOpenDialog(win, { properties: ['openDirectory', 'createDirectory'] })
    return { ok: !r.canceled, path: r.canceled ? null : r.filePaths[0] }
  })
}

// ----------------------------------------------------------------- boot

app.whenReady().then(() => {
  sidecar = new Sidecar(isPackaged ? process.resourcesPath : APP_ROOT,
                        isPackaged ? process.resourcesPath : null)
  sidecar.onEvent((msg) => {
    if (msg.event === 'progress') send('job:progress', msg)
    else if (msg.event === 'installProgress') send('cloning:progress', msg)
  })
  sidecar.start()
  registerIpc()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', async () => {
  await sidecar?.stop()
  if (process.platform !== 'darwin') app.quit()
})
