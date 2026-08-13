'use strict'
/**
 * Update checking against GitHub Releases.
 *
 * Deliberately NOT electron-updater. Its macOS path goes through Squirrel.Mac,
 * which refuses to install an update onto an app without a valid Apple code
 * signature - and unsigned is a deliberate choice here, to avoid $99/yr for a
 * family project. On macOS electron-updater
 * would fail at the last step, after downloading, which is the worst place to
 * fail. So: check and download ourselves, then hand over.
 *
 * What that means per platform:
 *
 *   Windows   the downloaded NSIS installer is launched; it replaces the app
 *   Linux     the AppImage is downloaded and revealed
 *   macOS     the .dmg is downloaded and revealed, and the user drags it across
 *
 * The user's work is never at risk either way. Everything they create - word lists,
 * recordings, settings, finished videos - lives in the OS user-data directory
 * (gen/paths.py DATA), which is outside the app bundle. Replacing the
 * application cannot touch it. That is by design, not luck.
 */

const { app, shell } = require('electron')
const fs = require('fs')
const fsp = require('fs/promises')
const https = require('https')
const path = require('path')

// This repo is public, so its release assets download without any
// authentication - which is the whole point: a non-technical user clicks a
// link in a browser and gets an installer. No account, no CLI, no token.
//
// (If the source were ever made private again, release assets would need auth
// and this would have to point at a separate public releases repo instead.)
const RELEASES_REPO = process.env.SIO_RELEASES_REPO || 'nwcnwc/sound-it-out'
const API = `https://api.github.com/repos/${RELEASES_REPO}/releases/latest`
const UA = 'SoundItOut-Updater'

function get (url, { json = false } = {}) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { 'User-Agent': UA, Accept: 'application/vnd.github+json' } },
      (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          res.resume()
          return resolve(get(res.headers.location, { json }))
        }
        if (res.statusCode === 404) {
          res.resume()
          return reject(Object.assign(new Error('no releases yet'), { noReleases: true }))
        }
        if (res.statusCode !== 200) {
          res.resume()
          return reject(new Error(`GitHub returned ${res.statusCode}`))
        }
        if (!json) return resolve(res)
        let body = ''
        res.setEncoding('utf8')
        res.on('data', (c) => { body += c })
        res.on('end', () => {
          try { resolve(JSON.parse(body)) } catch (e) { reject(e) }
        })
      }).on('error', reject)
  })
}

/** Compare dotted numeric versions. Returns true if `remote` is newer. */
function isNewer (remote, local) {
  const norm = (v) => String(v).replace(/^v/, '').split(/[.-]/).map((n) => parseInt(n, 10) || 0)
  const a = norm(remote)
  const b = norm(local)
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] || 0) > (b[i] || 0)) return true
    if ((a[i] || 0) < (b[i] || 0)) return false
  }
  return false
}

/** The installer asset for this platform, or null if the release lacks one. */
function pickAsset (assets) {
  const want = process.platform === 'darwin'
    ? [process.arch === 'arm64' ? /arm64.*\.dmg$/i : /(x64|intel).*\.dmg$/i, /\.dmg$/i]
    : process.platform === 'win32' ? [/\.exe$/i] : [/\.AppImage$/i]
  for (const re of want) {
    const hit = assets.find((a) => re.test(a.name))
    if (hit) return hit
  }
  return null
}

async function checkForUpdate () {
  const release = await get(API, { json: true })
  const latest = release.tag_name || release.name || ''
  const current = app.getVersion()
  if (!isNewer(latest, current)) {
    return { available: false, current, latest }
  }
  const asset = pickAsset(release.assets || [])
  return {
    available: true,
    current,
    latest,
    notes: (release.body || '').slice(0, 2000),
    asset: asset && { name: asset.name, url: asset.browser_download_url, size: asset.size }
  }
}

/**
 * Download an update to a temp file, reporting progress.
 * Verifies the byte count - a truncated installer that still launches is a
 * far worse outcome than a failed download.
 */
async function downloadUpdate (asset, onProgress) {
  const dir = path.join(app.getPath('temp'), 'sound-it-out-update')
  await fsp.mkdir(dir, { recursive: true })
  const dest = path.join(dir, asset.name)

  const res = await get(asset.url)
  const total = parseInt(res.headers['content-length'], 10) || asset.size || 0
  let done = 0

  await new Promise((resolve, reject) => {
    const out = fs.createWriteStream(dest)
    res.on('data', (buf) => {
      done += buf.length
      if (onProgress) onProgress(done, total)
    })
    res.pipe(out)
    out.on('finish', resolve)
    out.on('error', reject)
    res.on('error', reject)
  })

  const stat = await fsp.stat(dest)
  if (total && stat.size !== total) {
    await fsp.unlink(dest).catch(() => {})
    throw new Error('The download did not finish properly. Please try again.')
  }
  return dest
}

/**
 * Hand the downloaded file over to the OS.
 * Returns what the user still has to do, so the UI can say it plainly.
 */
async function applyUpdate (file) {
  if (process.platform === 'win32') {
    // The NSIS installer replaces the app in place; it must run after we exit.
    shell.openPath(file)
    setTimeout(() => app.quit(), 1200)
    return { action: 'installing', message: 'Installing the update...' }
  }
  shell.showItemInFolder(file)
  return {
    action: 'manual',
    message: process.platform === 'darwin'
      ? 'Open the file that just appeared, then drag Sound It Out into Applications, replacing the old one. Everything you have made is kept.'
      : 'The new version has been downloaded. Everything you have made is kept.'
  }
}

module.exports = { checkForUpdate, downloadUpdate, applyUpdate, isNewer, RELEASES_REPO }
