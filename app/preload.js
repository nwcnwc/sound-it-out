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
  cloningInfo: () => ipcRenderer.invoke('cloning:info'),
  openPath: (p) => ipcRenderer.invoke('path:open', p),
  openExternal: (u) => ipcRenderer.invoke('url:open', u),
  chooseRecording: () => ipcRenderer.invoke('recordings:choose'),
  importRecording: (opts) => ipcRenderer.invoke('recordings:import', opts),
  studioPlan: (opts) => ipcRenderer.invoke('studio:plan', opts),
  studioSubmit: (opts) => ipcRenderer.invoke('studio:submit', opts),
  studioClip: (opts) => ipcRenderer.invoke('studio:clip', opts),
  voiceInfo: () => ipcRenderer.invoke('voice:info'),
  voiceExport: () => ipcRenderer.invoke('voice:export'),
  voiceRestore: () => ipcRenderer.invoke('voice:restore'),
  studioRemove: (opts) => ipcRenderer.invoke('studio:remove', opts),
  studioPassage: (opts) => ipcRenderer.invoke('studio:passage', opts),
  passageText: () => ipcRenderer.invoke('passage:text'),
  passagePlan: () => ipcRenderer.invoke('passage:plan'),
  passageRemove: (opts) => ipcRenderer.invoke('passage:remove', opts),
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
