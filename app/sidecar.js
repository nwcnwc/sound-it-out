'use strict'
/**
 * Talks to the Python pipeline over JSON lines on stdio.
 *
 * In development this spawns the venv interpreter; in a packaged build it
 * spawns the PyInstaller-frozen `soundout-sidecar` binary from resources.
 * Nothing else in the app needs to know which.
 */

const { spawn } = require('child_process')
const path = require('path')
const fs = require('fs')
const readline = require('readline')

function resolveCommand (appRoot, resourcesPath) {
  // Packaged: a frozen single-file binary sits in resources/sidecar/.
  const exe = process.platform === 'win32' ? 'soundout-sidecar.exe' : 'soundout-sidecar'
  const frozen = resourcesPath && path.join(resourcesPath, 'sidecar', exe)
  if (frozen && fs.existsSync(frozen)) return { cmd: frozen, args: [] }

  // Development: the project venv.
  const venv = process.platform === 'win32'
    ? path.join(appRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(appRoot, '.venv', 'bin', 'python')
  if (fs.existsSync(venv)) return { cmd: venv, args: ['-m', 'gen.service'], cwd: appRoot }

  return { cmd: 'python3', args: ['-m', 'gen.service'], cwd: appRoot }
}

class Sidecar {
  constructor (appRoot, resourcesPath) {
    this.appRoot = appRoot
    this.resourcesPath = resourcesPath
    this.proc = null
    this.nextId = 1
    this.pending = new Map()
    this.listeners = new Set()
    this.stderr = []
  }

  start () {
    if (this.proc) return
    const { cmd, args, cwd } = resolveCommand(this.appRoot, this.resourcesPath)
    this.proc = spawn(cmd, args, {
      cwd: cwd || this.appRoot,
      env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
      stdio: ['pipe', 'pipe', 'pipe'],
      // The frozen sidecar must be a console app for stdio to work at all, so
      // Windows would flash up a console window without this.
      windowsHide: true
    })

    readline.createInterface({ input: this.proc.stdout }).on('line', (line) => {
      let msg
      try { msg = JSON.parse(line) } catch { return }
      if (msg.event) {
        for (const fn of this.listeners) fn(msg)
        return
      }
      const entry = this.pending.get(msg.id)
      if (!entry) return
      this.pending.delete(msg.id)
      if (msg.ok) entry.resolve(msg.result)
      else entry.reject(Object.assign(new Error(msg.error), { detail: msg.detail }))
    })

    // Keep only a tail of stderr: it is diagnostics, and a runaway warning
    // loop should not grow unbounded in memory.
    readline.createInterface({ input: this.proc.stderr }).on('line', (line) => {
      this.stderr.push(line)
      if (this.stderr.length > 200) this.stderr.shift()
    })

    this.proc.on('exit', (code) => {
      const err = new Error(
        `The engine stopped unexpectedly (code ${code}).\n` +
        this.stderr.slice(-8).join('\n')
      )
      for (const [, entry] of this.pending) entry.reject(err)
      this.pending.clear()
      this.proc = null
    })
  }

  onEvent (fn) { this.listeners.add(fn); return () => this.listeners.delete(fn) }

  call (method, params = {}) {
    this.start()
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.proc.stdin.write(JSON.stringify({ id, method, params }) + '\n')
    })
  }

  async stop () {
    if (!this.proc) return
    try { await this.call('shutdown') } catch { /* already gone */ }
    if (this.proc) this.proc.kill()
    this.proc = null
  }
}

module.exports = { Sidecar }
