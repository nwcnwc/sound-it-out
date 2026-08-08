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
const { pathToFileURL } = require('url')
const { Sidecar } = require('./sidecar')
const { renderFrames } = require('./frames')
const updater = require('./updater')
const appMenu = require('./menu')

const APP_ROOT = path.join(__dirname, '..')
const isPackaged = app.isPackaged

// Chromium needs shared memory that containers and CI runners often deny.
// Harmless on a normal desktop.
app.commandLine.appendSwitch('disable-dev-shm-usage')

// On ChromeOS/Crostini the GPU process cannot initialise: the container's
// virtio-gpu does not support the native buffers Chromium wants, so it fails,
// retries, and floods the console with "Buffer handle is null" and
// "StagingBuffer's SharedImage failed" - hundreds of lines that look alarming
// and mean nothing. Chromium then falls back to software rendering, which is
// what actually draws the window. Skipping the doomed attempt gets the same
// result quietly, and makes a real error visible when there is one.
//
// Deliberately narrow: only where we can see we are in a Crostini container.
// Everywhere else the GPU works and is worth having.
if (process.platform === 'linux' && fs.existsSync('/opt/google/cros-containers')) {
  app.commandLine.appendSwitch('disable-gpu')
  app.commandLine.appendSwitch('disable-gpu-compositing')
}

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

  // Two things that both produce a silent black screen, and did:
  //
  //  1. The page must be a real file, not a data: URL. Chromium refuses to
  //     load file:// subresources from a data: document, so the <video> src
  //     is blocked and you get black with no error. (Same trap as frames.js.)
  //  2. The path must be a properly encoded file URL. The default output
  //     folder is "~/Sound It Out", and a raw space in a src is not a URL.
  //
  // pathToFileURL handles the encoding on all three platforms, including
  // Windows drive letters and backslashes.
  const videoUrl = pathToFileURL(file).href

  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;height:100%;background:#000;overflow:hidden}
    video{width:100%;height:100%;object-fit:contain;display:block}
    #err{position:fixed;inset:0;display:none;place-content:center;color:#f8f4e9;
         font:24px/1.5 system-ui,sans-serif;text-align:center;padding:8vw}
  </style></head><body>
    <video id="v" src="${videoUrl}" autoplay loop playsinline></video>
    <div id="err">The video could not be played.<br><small>Press Escape to go back.</small></div>
    <script>
      var v = document.getElementById('v')
      // Never fail silently to a black screen again - say so on screen.
      v.addEventListener('error', function () {
        v.style.display = 'none'
        document.getElementById('err').style.display = 'grid'
      })
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') window.close()
      })
    </script></body></html>`

  const page = path.join(app.getPath('temp'), 'sound-it-out-player.html')
  fs.writeFileSync(page, html, 'utf8')
  player.loadFile(page)
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

  // The sentence library. Text in, recording status out; the walk-through
  // recording itself goes through the studio channel with part "sentence".
  ipcMain.handle('sentences:list', async () => sidecar.call('sentences.list', {}))
  ipcMain.handle('sentences:add', async (_e, text) => {
    try {
      return { ok: true, ...(await sidecar.call('sentences.add', { text })) }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })
  ipcMain.handle('sentences:remove', async (_e, key) =>
    sidecar.call('sentences.remove', { key }))
  ipcMain.handle('sentences:clips', async (_e, key) =>
    sidecar.call('sentences.clips', { key }))
  ipcMain.handle('packs:list', async () => sidecar.call('packs.list', {}))
  ipcMain.handle('packs:add', async (_e, id) => sidecar.call('packs.add', { id }))

  ipcMain.handle('job:generate', (_e, opts) => runJob(opts || {}))

  ipcMain.handle('job:cancel', (_e, jobId) => {
    const j = jobs.get(String(jobId))
    if (j) j.cancelled = true
    return { ok: true }
  })

  ipcMain.handle('cloning:info', async () => {
    try {
      return { ok: true, ...(await sidecar.call('cloning.info', {})) }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })

  ipcMain.handle('cloning:install', async () => {
    try {
      await sidecar.call('cloning.install')
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })

  ipcMain.handle('update:check', async () => {
    try {
      return { ok: true, ...(await updater.checkForUpdate()) }
    } catch (err) {
      // Offline, or no releases published yet. Never nag about it - the app
      // works perfectly well without ever updating.
      return { ok: false, available: false, error: err.message }
    }
  })

  ipcMain.handle('update:install', async (_e, asset) => {
    try {
      const file = await updater.downloadUpdate(asset, (done, total) =>
        send('update:progress', { done, total }))
      return { ok: true, ...(await updater.applyUpdate(file)) }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })

  ipcMain.handle('recordings:choose', async () => {
    const r = await dialog.showOpenDialog(win, {
      title: 'Choose your recording',
      properties: ['openFile'],
      filters: [{ name: 'Audio', extensions: ['m4a', 'mp3', 'wav', 'aac', 'ogg', 'opus', 'flac', 'mp4'] }]
    })
    return { ok: !r.canceled, path: r.canceled ? null : r.filePaths[0] }
  })

  ipcMain.handle('recordings:import', async (_e, opts) => {
    try {
      const r = await sidecar.call('recordings.import', opts || {})
      return { ok: true, ...r }
    } catch (err) {
      return { ok: false, error: err.message }
    }
  })

  ipcMain.handle('studio:plan', async (_e, o) => sidecar.call('studio.plan', o || {}))
  ipcMain.handle('studio:passage', async (_e, o) => sidecar.call('studio.passage', o || {}))
  ipcMain.handle('passage:text', async () => sidecar.call('passage.text', {}))
  ipcMain.handle('passage:plan', async () => sidecar.call('passage.plan', {}))
  ipcMain.handle('passage:remove', async (_e, opts) => sidecar.call('passage.remove', opts || {}))
  ipcMain.handle('voice:info', async () => sidecar.call('voice.info', {}))

  ipcMain.handle('voice:export', async () => {
    const r = await dialog.showSaveDialog(win, {
      title: 'Save a backup of your recordings',
      defaultPath: path.join(os.homedir(), 'sound-it-out-voice-backup.zip'),
      filters: [{ name: 'Backup', extensions: ['zip'] }]
    })
    if (r.canceled) return { ok: false, canceled: true }
    try {
      return { ok: true, ...(await sidecar.call('voice.export', { path: r.filePath })) }
    } catch (err) { return { ok: false, error: err.message } }
  })

  ipcMain.handle('voice:restore', async () => {
    const r = await dialog.showOpenDialog(win, {
      title: 'Choose a backup to restore',
      properties: ['openFile'],
      filters: [{ name: 'Backup', extensions: ['zip'] }]
    })
    if (r.canceled) return { ok: false, canceled: true }
    try {
      return { ok: true, ...(await sidecar.call('voice.restore', { path: r.filePaths[0] })) }
    } catch (err) { return { ok: false, error: err.message } }
  })

  ipcMain.handle('studio:clip', async (_e, o) => sidecar.call('studio.clip', o || {}))
  ipcMain.handle('studio:remove', async (_e, o) => sidecar.call('studio.remove', o || {}))
  ipcMain.handle('studio:submit', async (_e, o) => sidecar.call('studio.submit', o || {}))

  ipcMain.handle('path:open', (_e, p) => { shell.openPath(p); return { ok: true } })

  ipcMain.handle('url:open', (_e, u) => {
    // Only ever our own docs; refuse anything else rather than becoming a
    // general-purpose link opener driven by renderer content.
    if (/^https:\/\/github\.com\/nwcnwc\//.test(String(u))) shell.openExternal(u)
    return { ok: true }
  })

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

  // Replaces Electron's default menu, whose Help items link to electronjs.org.
  appMenu.build({
    onCheckForUpdates: async () => {
      try {
        const r = await updater.checkForUpdate()
        if (r.available) {
          send('update:available', r)
        } else {
          dialog.showMessageBox(win, {
            type: 'info',
            title: 'Sound It Out',
            message: 'You have the latest version.',
            detail: `Version ${app.getVersion()}.`,
            buttons: ['OK']
          })
        }
      } catch (err) {
        // "Offline" was the wrong guess and the commonest case: before the
        // first release is published the API returns 404, which is not a
        // network problem at all. Saying so beats blaming the connection.
        const none = err && err.noReleases
        dialog.showMessageBox(win, {
          type: 'info',
          title: 'Sound It Out',
          message: none ? 'No updates have been published yet.'
                        : 'Could not check for updates.',
          detail: none
            ? `You are running version ${app.getVersion()}, which is the only ` +
              'version so far. The app will tell you when a newer one appears.'
            : 'The computer may be offline, or GitHub may be unavailable. ' +
              'Sound It Out works normally without checking.',
          buttons: ['OK']
        })
      }
    }
  })

  createWindow()

  // Check once, quietly, a few seconds after launch. Never blocks startup and
  // never interrupts a running job - the UI decides whether to mention it.
  setTimeout(() => {
    updater.checkForUpdate()
      .then((r) => { if (r.available) send('update:available', r) })
      .catch(() => {})
  }, 4000)

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', async () => {
  await sidecar?.stop()
  if (process.platform !== 'darwin') app.quit()
})
