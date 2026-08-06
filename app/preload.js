'use strict'
/**
 * The only bridge between the renderer and the rest of the app.
 *
 * Deliberately a small, fixed surface: the renderer gets these functions and
 * nothing else - no ipcRenderer, no require, no fs. Word lists are user text
 * that ends up rendered as HTML, so the renderer is treated as untrusted.
 */

const { contextBridge, ipcRenderer } = require('electron')

const sub = (channel) => (cb) => {
  const handler = (_e, payload) => cb(payload)
  ipcRenderer.on(channel, handler)
  return () => ipcRenderer.removeListener(channel, handler)
}

contextBridge.exposeInMainWorld('soundout', {
  getState: () => ipcRenderer.invoke('state:get'),
  saveWordlist: (text) => ipcRenderer.invoke('wordlist:save', text),
  saveSettings: (patch) => ipcRenderer.invoke('settings:save', patch),
  generate: (opts) => ipcRenderer.invoke('job:generate', opts),
  cancelJob: (jobId) => ipcRenderer.invoke('job:cancel', jobId),
  installCloning: () => ipcRenderer.invoke('cloning:install'),
  openPath: (p) => ipcRenderer.invoke('path:open', p),
  checkForUpdate: () => ipcRenderer.invoke('update:check'),
  installUpdate: (asset) => ipcRenderer.invoke('update:install', asset),
  chooseDirectory: () => ipcRenderer.invoke('dir:choose'),

  onProgress: sub('job:progress'),
  onDone: sub('job:done'),
  onError: sub('job:error'),
  onInstallProgress: sub('cloning:progress'),
  onUpdateAvailable: sub('update:available'),
  onUpdateProgress: sub('update:progress')
})
