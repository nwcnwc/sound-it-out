'use strict'
/**
 * The application menu.
 *
 * Electron ships a default menu when you don't set one, and that default is
 * built for Electron developers: its Help menu links to electronjs.org docs,
 * community forums and the Electron issue tracker. A parent using this to teach
 * a child to read has no idea what Electron is and no reason to learn.
 *
 * Note this menu cannot simply be deleted. On macOS the Edit menu is what makes
 * Cmd+C / Cmd+V / Cmd+Z work at all in a text field - the roles are wired by
 * the menu, not by the web view - and the whole Words screen is a textarea.
 * Removing the menu would quietly break copy and paste.
 *
 * So: keep the parts that do real work (Edit, Window, full screen), drop the
 * developer-facing ones, and point Help at this project.
 */

const { app, Menu, shell, dialog } = require('electron')

const REPO = 'https://github.com/nwcnwc/sound-it-out'
const LINKS = {
  help: `${REPO}/blob/main/INSTALL.md`,
  recording: `${REPO}/blob/main/RECORDING.md`,
  project: REPO,
  releases: `${REPO}/releases/latest`
}

function aboutBox (win) {
  dialog.showMessageBox(win, {
    type: 'none',
    title: 'About Sound It Out',
    message: 'Sound It Out',
    detail:
      `Version ${app.getVersion()}\n\n` +
      'Offline phonics reading videos for the TV.\n\n' +
      'Everything runs on this computer. No internet connection is needed, ' +
      'no account, and nothing you record or type is ever sent anywhere.',
    buttons: ['OK'],
    defaultId: 0
  })
}

function build ({ onCheckForUpdates } = {}) {
  const isMac = process.platform === 'darwin'

  const template = [
    ...(isMac
      ? [{
          label: 'Sound It Out',
          submenu: [
            { label: 'About Sound It Out', click: (_i, win) => aboutBox(win) },
            { type: 'separator' },
            { role: 'hide', label: 'Hide Sound It Out' },
            { role: 'hideOthers' },
            { role: 'unhide' },
            { type: 'separator' },
            { role: 'quit', label: 'Quit Sound It Out' }
          ]
        }]
      : []),
    {
      label: 'File',
      submenu: [
        ...(isMac ? [] : [{ label: 'About Sound It Out', click: (_i, win) => aboutBox(win) },
                          { type: 'separator' }]),
        isMac ? { role: 'close' } : { role: 'quit', label: 'Exit' }
      ]
    },
    {
      // Required for clipboard shortcuts to work in the word list on macOS.
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        ...(isMac ? [{ role: 'pasteAndMatchStyle' }] : []),
        { role: 'delete' },
        { role: 'selectAll' }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'resetZoom', label: 'Actual Size' },
        { role: 'zoomIn', label: 'Bigger Text' },
        { role: 'zoomOut', label: 'Smaller Text' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        ...(isMac ? [{ role: 'zoom' }, { type: 'separator' }, { role: 'front' }]
                  : [{ role: 'close' }])
      ]
    },
    {
      role: 'help',
      label: 'Help',
      submenu: [
        {
          label: 'How to use Sound It Out',
          click: () => shell.openExternal(LINKS.help)
        },
        {
          label: 'Recording your voice',
          click: () => shell.openExternal(LINKS.recording)
        },
        { type: 'separator' },
        {
          label: 'Check for Updates...',
          click: () => { if (onCheckForUpdates) onCheckForUpdates() }
        },
        {
          label: 'Download the latest version',
          click: () => shell.openExternal(LINKS.releases)
        },
        { type: 'separator' },
        {
          label: 'Project page',
          click: () => shell.openExternal(LINKS.project)
        }
      ]
    }
  ]

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

module.exports = { build, LINKS }
