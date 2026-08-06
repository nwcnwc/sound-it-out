'use strict'
/**
 * Render storyboard frames to PNG using Electron's own Chromium.
 *
 * This replaces shelling out to an external `google-chrome`, which cannot be
 * assumed to exist on a user's machine. Every install ships the same Chromium
 * build, so a frame renders identically on macOS, Windows and Linux - which
 * matters here because the entire product is precisely-rendered letterforms.
 *
 * One PNG per *visual state*, not per video frame: the display is static text
 * with discrete highlight changes, so a 20 minute video is a few hundred PNGs.
 */

const { BrowserWindow } = require('electron')
const fs = require('fs/promises')
const path = require('path')

const WIDTH = 1920
const HEIGHT = 1080

/** Andika must be embedded by URL - the packaged app cannot rely on a system font. */
function fontFaceCss (fontDir) {
  const url = (f) =>
    'file://' + path.join(fontDir, f).split(path.sep).join('/')
  return `
@font-face { font-family:'Andika'; font-weight:400; font-style:normal;
             src:url('${url('Andika-Regular.ttf')}') format('truetype'); }
@font-face { font-family:'Andika'; font-weight:700; font-style:normal;
             src:url('${url('Andika-Bold.ttf')}') format('truetype'); }
`
}

/**
 * @param {{id:string, html:string}[]} frames
 * @param {string} outDir       where PNGs are written
 * @param {object} [opts]
 * @param {string} [opts.fontDir]
 * @param {(done:number,total:number)=>void} [opts.onProgress]
 * @returns {Promise<string[]>} written PNG paths, in input order
 */
async function renderFrames (frames, outDir, opts = {}) {
  const fontDir = opts.fontDir || path.join(__dirname, 'fonts')
  const css = fontFaceCss(fontDir)
  // loadFile() resolves relative paths against the app directory, not the cwd.
  outDir = path.resolve(outDir)
  await fs.mkdir(outDir, { recursive: true })

  const win = new BrowserWindow({
    width: WIDTH,
    height: HEIGHT,
    show: false,
    frame: false,
    useContentSize: true,
    backgroundColor: '#000000',
    webPreferences: {
      offscreen: false,
      nodeIntegration: false,
      contextIsolation: true,
      // Frames come from our own generator, but they are still untrusted
      // input in the sense that a word list is user-supplied text.
      sandbox: true,
      javascript: true
    }
  })

  // Pages are written to disk rather than loaded as data: URLs. Chromium
  // refuses to load file:// subresources from a data: URL, so the @font-face
  // fetch fails and takes the whole page down with it.
  const htmlDir = path.join(outDir, '_html')
  await fs.mkdir(htmlDir, { recursive: true })

  const written = []
  try {
    for (let i = 0; i < frames.length; i++) {
      const { id, html } = frames[i]
      // Inject the @font-face block; the fit script in the page measures real
      // glyph widths, so the font must be loaded before it runs.
      const page = html.replace('<style>', '<style>' + css)
      const pageFile = path.join(htmlDir, `${id}.html`)
      await fs.writeFile(pageFile, page, 'utf8')

      await win.loadFile(pageFile)
      // Fonts load asynchronously. Without this the fit script measures a
      // fallback font and every frame comes out the wrong size.
      await win.webContents.executeJavaScript(
        'document.fonts.ready.then(() => { if (window.__refit) window.__refit(); return true })',
        true
      )

      const image = await win.webContents.capturePage()
      const file = path.join(outDir, `${id}.png`)
      await fs.writeFile(file, image.toPNG())
      written.push(file)
      if (opts.onProgress) opts.onProgress(i + 1, frames.length)
    }
  } finally {
    if (!win.isDestroyed()) win.destroy()
  }
  return written
}

module.exports = { renderFrames, WIDTH, HEIGHT }
