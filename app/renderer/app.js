/* Sound It Out - renderer.
 *
 * Talks only to window.soundout (app/preload.js), or to the stand-in in
 * mock.js when this page is opened outside Electron.
 *
 * Guiding rule for everything below: the person using this is the child's parent,
 * probably with a child pulling at their arm. Few controls, big targets, plain
 * words, and any message about a failure has to say what to do next.
 */
'use strict'

const api = window.soundout
const $ = (id) => document.getElementById(id)

/* Theme swatch colours mirror THEMES in gen/soundout.py so the preview is the
   real thing. Unknown ids fall back to something neutral rather than blank. */
const THEME_COLOURS = {
  night: { bg: '#0d1b2a', fg: '#f8f4e9', hl: '#ffd166' },
  paper: { bg: '#fdfaf3', fg: '#2b2b2b', hl: '#d62828' },
  contrast: { bg: '#000000', fg: '#ffffff', hl: '#4cc9f0' }
}
const THEME_FALLBACK = { bg: '#333333', fg: '#ffffff', hl: '#ffd166' }

const MINUTES = [
  { value: 5, label: '5 min' },
  { value: 10, label: '10 min' },
  { value: 20, label: '20 min' },
  { value: 30, label: '30 min' }
]
const REPS = [
  { value: 2, label: 'Twice' },
  { value: 3, label: '3 times' },
  { value: 4, label: '4 times' }
]
const PAUSES = [
  { value: 1, label: 'Short' },
  { value: 1.5, label: 'Just right' },
  { value: 2.5, label: 'Long' }
]

const PLACEHOLDER_NAMES = ['alex', 'mum', 'dad', 'nana', 'grandad']

let state = null
let savedText = ''
let currentJob = null
let currentMode = 'export'
let jobRunning = false

/* ------------------------------------------------------------------ boot */

async function boot () {
  // Lets the standalone preview be screenshotted in both appearances.
  const forced = new URLSearchParams(location.search).get('appearance')
  if (forced) document.documentElement.setAttribute('data-appearance', forced)

  try {
    state = await api.getState()
  } catch (err) {
    document.body.innerHTML =
      '<div class="screen"><h1>Something went wrong starting up</h1>' +
      '<p class="lede">Please close the app and open it again. If it keeps happening, ' +
      'restarting the computer usually clears it.</p></div>'
    console.error(err)
    return
  }

  setUpTabs()
  initVoice()
  initStudio()
  initScript()
  initReview()
  initReader()
  setUpWords()
  setUpMake()
  setUpSettings()
  setUpJobEvents()

  if (window.__soundoutMock) devPreview()
}

/* Only ever runs against the stand-in in mock.js: lets the standalone page be
   opened straight on a given screen or progress state, for eyeballing. */
function devPreview () {
  const q = new URLSearchParams(location.search)
  if (q.get('screen')) window.showScreen(q.get('screen'))

  const demo = q.get('demo')
  if (demo === 'working') {
    $('prog-stage').textContent = prettyStage('frames')
    $('prog-message').textContent = 'Drawing “Marshall”'
    setBar(23, 40)
    progressView('prog-working')
  } else if (demo === 'done') {
    currentMode = 'export'
    $('done-message').textContent = 'It’s saved and ready to copy onto a USB stick.'
    $('done-path').hidden = false
    $('done-path').textContent = state.outputDir + '/sound-it-out-level-1-20min.mp4'
    $('btn-open-file').hidden = false
    $('btn-open-folder').hidden = false
    progressView('prog-done')
  } else if (demo === 'install') {
    window.showScreen('settings')
    $('install-clone').click()
  } else if (demo === 'job') {
    window.showScreen('make')
    startJob('export')
  } else if (demo === 'error') {
    showJobError(
      "There wasn't enough room on the disk to save the video.",
      'Free up about 1 GB and try again, or pick a different folder in Settings.'
    )
  }
}

/* ------------------------------------------------------------------ tabs */

function setUpTabs () {
  const tabs = Array.from(document.querySelectorAll('.tab'))

  function show (name, focus) {
    tabs.forEach((t) => {
      const on = t.dataset.screen === name
      t.setAttribute('aria-selected', String(on))
      t.tabIndex = on ? 0 : -1
      const panel = $('screen-' + t.dataset.screen)
      panel.hidden = !on
      if (on && focus) t.focus()
    })
  }

  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => {
      if (jobRunning) return
      show(tab.dataset.screen, false)
    })
    tab.addEventListener('keydown', (e) => {
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
      if (!step) return
      e.preventDefault()
      const next = tabs[(i + step + tabs.length) % tabs.length]
      show(next.dataset.screen, true)
    })
  })

  window.showScreen = (name) => show(name, false)
}

/* ----------------------------------------------------------------- words */

function parseWordlist (text) {
  const groups = []
  let cur = null
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue

    const heading = line.match(/^\[(.+)\]$/)
    if (heading) {
      cur = { name: heading[1].trim(), words: [] }
      groups.push(cur)
      continue
    }
    const coloured = line.match(/^(.*?)\s+(#[0-9a-fA-F]{6})$/)
    const word = coloured ? coloured[1].trim() : line
    if (!word) continue
    if (!cur) { cur = { name: 'Words', words: [] }; groups.push(cur) }
    cur.words.push({ word, color: coloured ? coloured[2].toLowerCase() : null })
  }
  return groups
}

function setUpWords () {
  const box = $('wordlist')
  box.value = state.wordlistText || ''
  savedText = box.value

  box.addEventListener('input', () => {
    renderGroups(parseWordlist(box.value))
    setDirty(box.value !== savedText)
    $('words-error').hidden = true
  })

  $('save-words').addEventListener('click', saveWords)

  $('revert-words').addEventListener('click', () => {
    box.value = savedText
    renderGroups(parseWordlist(box.value))
    setDirty(false)
    $('words-error').hidden = true
    say('save-state', '')
    box.focus()
  })

  $('jump-people').addEventListener('click', () => selectPeopleGroup(box))

  // Cmd/Ctrl-S is what anyone who has ever used a Mac will reach for.
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
      e.preventDefault()
      if (!$('screen-words').hidden) saveWords()
    }
  })

  renderGroups(parseWordlist(box.value))
  setDirty(false)
}

function setDirty (isDirty) {
  $('dirty-dot').hidden = !isDirty
  if (isDirty) say('save-state', '')
}

async function saveWords () {
  const box = $('wordlist')
  const btn = $('save-words')
  const err = $('words-error')

  btn.disabled = true
  say('save-state', 'Saving…')
  try {
    const res = await api.saveWordlist(box.value)
    if (!res || !res.ok) {
      err.textContent = (res && res.error) ||
        "Your words couldn't be saved. Check the folder still exists, then try again."
      err.hidden = false
      say('save-state', '')
      return false
    }
    err.hidden = true
    savedText = box.value
    state.wordlistText = box.value
    setDirty(false)
    renderGroups(res.groups && res.groups.length ? res.groups : parseWordlist(box.value))
    say('save-state', 'Saved ✓')
    updateSummary()
    return true
  } catch (e) {
    console.error(e)
    err.textContent = "Your words couldn't be saved just now. Try again in a moment."
    err.hidden = false
    say('save-state', '')
    return false
  } finally {
    btn.disabled = false
  }
}

function renderGroups (groups) {
  const host = $('groups')
  host.textContent = ''

  const total = groups.reduce((n, g) => n + g.words.length, 0)
  $('word-count').textContent = total === 0
    ? 'No words yet'
    : total + (total === 1 ? ' word' : ' words') +
      (total < 50 ? ' — around 50 is the point where sounding out starts to make sense' : '')

  if (!groups.length) {
    const p = document.createElement('p')
    p.className = 'empty-note'
    p.textContent = 'Type a word on a line of its own and it will show up here.'
    host.appendChild(p)
  }

  for (const g of groups) {
    const wrap = document.createElement('div')
    wrap.className = 'group'

    const h = document.createElement('h3')
    h.className = 'group-name'
    h.textContent = g.name
    const n = document.createElement('span')
    n.textContent = g.words.length + (g.words.length === 1 ? ' word' : ' words')
    h.appendChild(n)
    wrap.appendChild(h)

    const chips = document.createElement('div')
    chips.className = 'chips'
    for (const w of g.words) {
      const c = document.createElement('span')
      c.className = 'chip' + (w.color ? ' coloured' : '')
      c.textContent = w.word
      if (w.color) c.style.color = w.color
      chips.appendChild(c)
    }
    wrap.appendChild(chips)
    host.appendChild(wrap)
  }

  updatePeopleNudge(groups)
  updateSummary(total)
}

function updatePeopleNudge (groups) {
  const people = groups.find((g) => /people|family/i.test(g.name))
  const nudge = $('people-nudge')

  if (!people || !people.words.length) { nudge.hidden = true; return }
  const left = people.words.filter((w) => PLACEHOLDER_NAMES.includes(w.word.toLowerCase()))
  const untouched = left.length === people.words.length

  nudge.hidden = !untouched
  if (untouched) {
    $('people-nudge-text').innerHTML =
      'The <b>' + escapeHtml(people.name) + '</b> group still has only the example names in it — ' +
      left.map((w) => escapeHtml(w.word)).join(', ') + '.'
  }
}

function selectPeopleGroup (box) {
  const lines = box.value.split('\n')
  let start = -1
  let end = lines.length
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].trim().match(/^\[(.+)\]$/)
    if (!m) continue
    if (start === -1 && /people|family/i.test(m[1])) { start = i; continue }
    if (start !== -1) { end = i; break }
  }
  if (start === -1) { box.focus(); return }

  const offset = (n) => lines.slice(0, n).join('\n').length + (n ? 1 : 0)
  box.focus()
  box.setSelectionRange(offset(start), offset(end))
  // setSelectionRange does not reliably scroll, so aim the scroll by hand.
  const lineHeight = box.scrollHeight / Math.max(lines.length, 1)
  box.scrollTop = Math.max(0, (start - 2) * lineHeight)
}

/* ------------------------------------------------------------- make video */

function setUpMake () {
  const chosen = Object.assign(
    { level: null, theme: null, reps: 3, pauseSeconds: 1.5, minutes: 20 },
    state.settings || {}
  )

  renderLevels(chosen.level)
  renderThemes(chosen.theme)
  renderSegmented($('minutes'), 'minutes', MINUTES, chosen.minutes)
  renderSegmented($('reps'), 'reps', REPS, chosen.reps)
  renderSegmented($('pause'), 'pause', PAUSES, chosen.pauseSeconds)

  document.querySelectorAll('#screen-make input[type=radio]').forEach((r) => {
    r.addEventListener('change', () => { updateSummary(); persistChoices() })
  })

  $('btn-play').addEventListener('click', () => startJob('play'))
  $('btn-export').addEventListener('click', () => startJob('export'))

  updateSummary()
  updateExportDest()
}

function renderLevels (selected) {
  const host = $('levels')
  host.textContent = ''
  const levels = state.levels || []
  const firstAvailable = levels.find((l) => l.available)
  if (!levels.some((l) => l.available && String(l.id) === String(selected))) {
    selected = firstAvailable ? firstAvailable.id : null
  }

  for (const lvl of levels) {
    const label = document.createElement('label')
    label.className = 'choice' + (lvl.available ? '' : ' is-off')

    const input = document.createElement('input')
    input.type = 'radio'
    input.name = 'level'
    input.value = lvl.id
    input.disabled = !lvl.available
    input.checked = lvl.available && String(lvl.id) === String(selected)

    const tick = document.createElement('span')
    tick.className = 'tick'
    tick.setAttribute('aria-hidden', 'true')

    const text = document.createElement('span')
    text.className = 'choice-text'

    const title = document.createElement('span')
    title.className = 'choice-title'
    title.textContent = lvl.name
    text.appendChild(title)

    if (lvl.description) {
      const d = document.createElement('span')
      d.className = 'choice-desc'
      d.textContent = lvl.description
      text.appendChild(document.createElement('br'))
      text.appendChild(d)
    }
    if (!lvl.available) {
      const r = document.createElement('span')
      r.className = 'reason'
      r.textContent = lvl.reason || 'Not ready yet'
      text.appendChild(document.createElement('br'))
      text.appendChild(r)
    }

    label.append(input, tick, text)
    host.appendChild(label)
  }
}

function renderThemes (selected) {
  const host = $('themes')
  host.textContent = ''
  const themes = state.themes || []
  if (!themes.some((t) => t.id === selected)) selected = themes.length ? themes[0].id : null

  for (const t of themes) {
    const c = THEME_COLOURS[t.id] || THEME_FALLBACK

    const label = document.createElement('label')
    label.className = 'theme-card'

    const input = document.createElement('input')
    input.type = 'radio'
    input.name = 'theme'
    input.value = t.id
    input.checked = t.id === selected

    const sw = document.createElement('span')
    sw.className = 'swatch'
    sw.style.setProperty('--sw-bg', c.bg)
    sw.style.setProperty('--sw-fg', c.fg)
    sw.style.setProperty('--sw-hl', c.hl)
    sw.setAttribute('aria-hidden', 'true')
    sw.innerHTML = '<span class="sw-word"><b>s</b>at</span>'

    const name = document.createElement('span')
    name.className = 'theme-name'
    name.textContent = t.name

    label.append(input, sw, name)
    host.appendChild(label)
  }
}

function renderSegmented (host, name, options, selected) {
  host.textContent = ''
  if (!options.some((o) => o.value === selected)) selected = options[1] ? options[1].value : options[0].value

  for (const o of options) {
    const label = document.createElement('label')
    label.className = 'seg'

    const input = document.createElement('input')
    input.type = 'radio'
    input.name = name
    input.value = String(o.value)
    input.checked = o.value === selected

    label.append(input, document.createTextNode(o.label))
    host.appendChild(label)
  }
}

function picked (name) {
  const el = document.querySelector('input[name="' + name + '"]:checked')
  return el ? el.value : null
}

function currentOptions () {
  return {
    level: picked('level'),
    theme: picked('theme'),
    reps: Number(picked('reps')),
    pauseSeconds: Number(picked('pause')),
    minutes: Number(picked('minutes'))
  }
}

let persistTimer = null
function persistChoices () {
  clearTimeout(persistTimer)
  persistTimer = setTimeout(() => {
    Promise.resolve(api.saveSettings(currentOptions())).catch((e) => console.error(e))
  }, 400)
}

function updateSummary (knownTotal) {
  const el = $('make-summary')
  if (!el) return
  const o = currentOptions()
  const level = (state.levels || []).find((l) => String(l.id) === String(o.level))
  const total = typeof knownTotal === 'number'
    ? knownTotal
    : parseWordlist($('wordlist').value).reduce((n, g) => n + g.words.length, 0)

  if (!level) {
    const any = (state.levels || []).some((l) => l.available)
    el.textContent = any
      ? 'Pick a level to start.'
      : 'None of the levels are ready yet — Settings explains what each one needs.'
    $('btn-play').disabled = true
    $('btn-export').disabled = true
    return
  }
  $('btn-play').disabled = false
  $('btn-export').disabled = false

  const usesWords = String(o.level) === '1' || String(o.level) === '2'
  const words = usesWords ? ', drawn from the ' + total + ' words on your list' : ''
  el.textContent = o.minutes + ' minutes of ' + level.name + words +
    ', each one shown ' + o.reps + ' times, then it loops.'
}

function updateExportDest () {
  $('export-dest').textContent = state.outputDir
    ? 'Saved videos go to ' + state.outputDir + '. You can change that in Settings.'
    : ''
}

/* -------------------------------------------------------------- progress */

const STAGE_WORDS = {
  words: 'Reading your word list',
  wordlist: 'Reading your word list',
  audio: 'Putting the sounds together',
  voice: 'Putting the sounds together',
  tts: 'Putting the sounds together',
  frames: 'Drawing the words',
  render: 'Drawing the words',
  video: 'Making the video file',
  encode: 'Making the video file',
  ffmpeg: 'Making the video file',
  finish: 'Nearly there',
  done: 'Nearly there'
}

function prettyStage (stage) {
  if (!stage) return 'Working on it'
  const key = String(stage).toLowerCase()
  if (STAGE_WORDS[key]) return STAGE_WORDS[key]
  return key.charAt(0).toUpperCase() + key.slice(1).replace(/[-_]/g, ' ')
}

function progressView (which) {
  for (const id of ['prog-working', 'prog-done', 'prog-error']) $(id).hidden = id !== which
  $('screen-progress').hidden = false
  jobRunning = which === 'prog-working'
  document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-disabled', String(jobRunning)))
  behindTheOverlay(true)
}

/* The progress card covers the window, so nothing underneath should still be
   reachable by tabbing to it. */
function behindTheOverlay (off) {
  document.querySelectorAll('.topbar, .screen:not(#screen-progress)')
    .forEach((el) => { el.inert = off })
}

function closeProgress () {
  $('screen-progress').hidden = true
  jobRunning = false
  currentJob = null
  behindTheOverlay(false)
  document.querySelectorAll('.tab').forEach((t) => t.removeAttribute('aria-disabled'))
  $('btn-cancel').disabled = false
  $('btn-cancel').textContent = 'Stop making it'
}

async function startJob (mode) {
  currentMode = mode

  // Saving the words first is what the user would expect; asking would just be a
  // dialog in the way.
  if ($('wordlist').value !== savedText) {
    const ok = await saveWords()
    if (!ok) {
      window.showScreen('words')
      $('words-error').scrollIntoView({ block: 'center' })
      return
    }
  }

  $('progress-title').textContent = mode === 'play' ? 'Getting it ready to play' : 'Making your video'
  $('prog-stage').textContent = 'Getting started'
  $('prog-message').textContent = ''
  setBar(0, 0)
  progressView('prog-working')
  $('btn-cancel').focus()

  try {
    const res = await api.generate(Object.assign(currentOptions(), { mode }))
    currentJob = res && res.jobId
  } catch (e) {
    console.error(e)
    showJobError(
      "The video couldn't be started.",
      'Close the app and open it again, then try once more.'
    )
  }
}

function setBar (done, total) {
  const bar = $('prog-bar')
  const fill = $('prog-fill')
  if (!total || total <= 0) {
    bar.classList.add('unknown')
    bar.removeAttribute('aria-valuenow')
    bar.setAttribute('aria-valuetext', 'Working')
    return
  }
  const pct = Math.max(0, Math.min(100, Math.round((done / total) * 100)))
  bar.classList.remove('unknown')
  bar.setAttribute('aria-valuemin', '0')
  bar.setAttribute('aria-valuemax', '100')
  bar.setAttribute('aria-valuenow', String(pct))
  bar.setAttribute('aria-valuetext', pct + '% done')
  fill.style.width = pct + '%'
}

function mine (e) {
  return !currentJob || !e || !e.jobId || e.jobId === currentJob
}

function setUpJobEvents () {
  api.onProgress((e) => {
    if ($('screen-progress').hidden || !mine(e)) return
    const stage = prettyStage(e.stage)
    $('prog-stage').textContent = stage
    // Don't say the same thing twice in a row.
    $('prog-message').textContent = e.message && e.message !== stage ? e.message : ''
    setBar(e.done, e.total)
  })

  api.onDone((e) => {
    if (!mine(e)) return
    progressView('prog-done')

    const playing = currentMode === 'play' || !e || !e.output
    $('done-title').textContent = playing ? "It's playing now" : "Your video is ready"
    $('done-message').textContent = playing
      ? 'It carries on looping until you stop it. Press Esc on the big screen to come back.'
      : 'It’s saved and ready to copy onto a USB stick.'

    const pathEl = $('done-path')
    pathEl.hidden = playing
    pathEl.textContent = playing ? '' : e.output

    const openFile = $('btn-open-file')
    const openFolder = $('btn-open-folder')
    openFile.hidden = playing
    openFolder.hidden = playing
    openFile.textContent = 'Play it now'
    openFile.onclick = () => api.openPath(e.output)
    openFolder.onclick = () => api.openPath(folderOf(e.output))
    ;(playing ? $('btn-done-back') : openFile).focus()
  })

  api.onError((e) => {
    if (!mine(e)) return
    showJobError(
      (e && e.message) || "The video couldn't be made.",
      (e && e.hint) || 'Try again. If it happens twice, close the app and open it again.'
    )
  })

  $('btn-cancel').addEventListener('click', async () => {
    $('btn-cancel').disabled = true
    $('btn-cancel').textContent = 'Stopping…'
    try { await api.cancelJob(currentJob) } catch (e) { console.error(e) }
    closeProgress()
    window.showScreen('make')
    $('btn-export').focus()
  })

  $('btn-done-back').addEventListener('click', () => { closeProgress(); $('btn-export').focus() })
  $('btn-error-back').addEventListener('click', () => { closeProgress(); $('btn-export').focus() })
  $('btn-retry').addEventListener('click', () => { closeProgress(); startJob(currentMode) })

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || $('screen-progress').hidden) return
    if (jobRunning) $('btn-cancel').click()
    else closeProgress()
  })
}

function showJobError (message, hint) {
  $('error-message').textContent = message
  $('error-hint').textContent = hint || ''
  $('error-hint').hidden = !hint
  progressView('prog-error')
  $('btn-retry').focus()
}

function folderOf (p) {
  const cut = Math.max(String(p).lastIndexOf('/'), String(p).lastIndexOf('\\'))
  return cut > 0 ? String(p).slice(0, cut) : String(p)
}

/* -------------------------------------------------------------- settings */

function setUpSettings () {
  $('outdir-display').textContent = state.outputDir || 'Not set'

  $('open-outdir').addEventListener('click', () => {
    if (state.outputDir) api.openPath(state.outputDir)
  })

  const editor = $('outdir-editor')
  const toggle = $('change-outdir')
  toggle.addEventListener('click', () => {
    const open = editor.hidden
    editor.hidden = !open
    toggle.setAttribute('aria-expanded', String(open))
    if (open) {
      $('outdir-input').value = state.outputDir || ''
      $('outdir-input').focus()
    }
  })
  $('cancel-outdir').addEventListener('click', () => {
    editor.hidden = true
    toggle.setAttribute('aria-expanded', 'false')
    toggle.focus()
  })
  $('save-outdir').addEventListener('click', async () => {
    const value = $('outdir-input').value.trim()
    if (!value) return
    try {
      await api.saveSettings({ outputDir: value })
      state.outputDir = value
      $('outdir-display').textContent = value
      editor.hidden = true
      toggle.setAttribute('aria-expanded', 'false')
      updateExportDest()
      toggle.focus()
    } catch (e) {
      console.error(e)
    }
  })

  // Dropping a folder from Finder onto the box fills in its path.
  const input = $('outdir-input')
  input.addEventListener('dragover', (e) => e.preventDefault())
  input.addEventListener('drop', (e) => {
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]
    if (file && file.path) { e.preventDefault(); input.value = file.path }
  })

  renderCapabilities()
  setUpCloning()
}

function renderCapabilities () {
  const caps = state.capabilities || {}
  const rows = [
    {
      on: !!caps.recordings,
      what: 'Your recordings',
      yes: 'Ready. Levels 1 to 5 are your own voice, exactly as you said the words.',
      no: 'Not added yet. Until they are, a stand-in voice is used.'
    },
    {
      on: !!caps.kokoro,
      what: 'The built-in voice',
      yes: 'Ready. Used wherever there is no recording of yours.',
      no: 'Missing. Reinstalling the app should put it back.'
    },
    {
      on: !!caps.cloning,
      what: 'The extra voice for later levels',
      yes: 'Installed.',
      no: "Not installed. You don't need it to start."
    }
  ]

  const host = $('capabilities')
  host.textContent = ''
  for (const r of rows) {
    const li = document.createElement('li')
    const dot = document.createElement('span')
    dot.className = 'dot' + (r.on ? '' : ' off')
    dot.setAttribute('aria-hidden', 'true')
    const text = document.createElement('span')
    const what = document.createElement('b')
    what.className = 'ready-what'
    what.textContent = r.what + ' — '
    const note = document.createElement('span')
    note.className = 'ready-note'
    note.textContent = r.on ? r.yes : r.no
    text.append(what, note)
    li.append(dot, text)
    host.appendChild(li)
  }
}

function setUpCloning () {
  const btn = $('install-clone')
  const status = $('install-status')
  const bar = $('install-bar')
  const fill = $('install-bar-fill')

  if (state.capabilities && state.capabilities.cloning) { showInstalled(); return }

  api.onInstallProgress((e) => {
    status.hidden = false
    bar.hidden = false
    const pct = e && e.total ? Math.round((e.done / e.total) * 100) : 0
    fill.style.width = pct + '%'
    status.textContent = (e && e.message) || 'Downloading…'
  })

  btn.addEventListener('click', async () => {
    btn.disabled = true
    btn.textContent = 'Downloading…'
    status.hidden = false
    status.textContent = 'Starting the download. This can take a while — it carries on in the background.'
    try {
      const res = await api.installCloning()
      if (res && res.ok === false) throw new Error('install failed')
      state = await api.getState()
      renderCapabilities()
      renderLevels(picked('level'))
      updateSummary()
      showInstalled()
    } catch (e) {
      console.error(e)
      btn.disabled = false
      btn.textContent = 'Try the download again'
      bar.hidden = true
      status.textContent =
        "The download didn't finish. Check the internet connection and try again — " +
        'it picks up where it left off. Nothing else is affected.'
    }
  })

  function showInstalled () {
    const host = $('clone-state')
    host.textContent = ''
    const badge = document.createElement('p')
    badge.className = 'installed'
    badge.textContent = '✓ Installed — the later levels are unlocked'
    host.appendChild(badge)
  }
}

/* ---------------------------------------------------------------- helpers */

function say (id, text) { $(id).textContent = text }

function escapeHtml (s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

boot()


/* ---------------------------------------------------------------- your voice
 *
 * The import pipeline existed long before this screen did, which meant the one
 * feature the whole voice design rests on could only be reached from a
 * terminal. This is the way in.
 */

const PART_NAMES = { phonemes: 'sounds', words: 'words', passage: 'reading passage' }

async function voiceCounts (caps) {
  const p = (caps && caps.recorded_phonemes) || 0
  const w = (caps && caps.recorded_words) || 0

  // Totals come from the plan so the denominator is always the real list -
  // adding a word to the word list changes what "finished" means.
  let totals = { phonemes: 42, words: w }
  try {
    const [ps, ws] = await Promise.all([
      api.studioPlan({ part: 'phonemes' }), api.studioPlan({ part: 'words' })
    ])
    totals = { phonemes: ps.total, words: ws.total }
  } catch { /* fall back to what we know */ }

  showPartProgress('phonemes', p, totals.phonemes)
  showPartProgress('words', w, totals.words)
  for (const [part, n] of [['phonemes', p], ['words', w]]) {
    const b = document.querySelector(`.vpart-review[data-part="${part}"]`)
    if (b) b.hidden = n === 0
  }

  const foot = $('voice-foot')
  if (!foot) return
  const total = totals.phonemes + totals.words
  const done = p + w
  foot.textContent = done === 0
    ? 'Nothing recorded yet \u2014 the computer voice is being used for now.'
    : done >= total
      ? 'All recorded. Everything in the early levels is your own voice.'
      : `${done} of ${total} recorded. You can stop and carry on whenever \u2014 ` +
        'it picks up where you left off.'
}

function showPartProgress (part, done, total) {
  setText('count-' + part, total ? `\u2014 ${done} of ${total} recorded` : '')
  const fill = $('bar-' + part)
  const wrap = $('barwrap-' + part)
  if (fill && total) {
    fill.style.width = Math.round((done / total) * 100) + '%'
    if (wrap) wrap.hidden = false
  } else if (wrap) {
    wrap.hidden = true
  }
}

function setText (id, txt) { const el = $(id); if (el) el.textContent = txt }

function renderImportResult (part, r) {
  const box = $('result-' + part)
  if (!box) return
  box.hidden = false
  box.innerHTML = ''

  if (!r.ok) {
    box.className = 'vpart-result is-bad'
    box.textContent = r.error || 'That recording could not be read.'
    return
  }

  const fails = (r.issues || []).filter((i) => i.severity === 'fail')
  const checks = (r.issues || []).filter((i) => i.severity !== 'fail')
  box.className = 'vpart-result ' + (fails.length ? 'is-warn' : 'is-good')

  const head = document.createElement('p')
  head.className = 'vres-head'
  if (part === 'passage') {
    head.textContent = fails.length
      ? 'That recording needs another go.'
      : 'Saved. That is everything needed for the later levels.'
  } else {
    head.textContent = `Found ${r.found} of ${r.expected} ${PART_NAMES[part]}` +
      (r.saved ? `, and saved ${r.saved}.` : '.')
  }
  box.appendChild(head)

  if (r.found != null && r.expected != null && r.found !== r.expected) {
    const m = document.createElement('p')
    m.className = 'vres-note'
    m.textContent = r.found < r.expected
      ? 'Fewer than expected. Usually that means two items ran together, or one was skipped \u2014 the names after that point may be wrong, so it is worth checking.'
      : 'More than expected, which usually means a retake. The last version of each was kept.'
    box.appendChild(m)
  }

  for (const [title, list, cls] of [
    ['Worth re-recording', fails, 'bad'],
    ['Worth a listen', checks, 'warn']
  ]) {
    if (!list.length) continue
    const h = document.createElement('p')
    h.className = 'vres-subhead'
    h.textContent = `${title} (${list.length})`
    box.appendChild(h)
    const ul = document.createElement('ul')
    ul.className = 'vres-list vres-' + cls
    for (const i of list.slice(0, 40)) {
      const li = document.createElement('li')
      li.textContent = i.message
      ul.appendChild(li)
    }
    box.appendChild(ul)
  }

  if (!fails.length && !checks.length && part !== 'passage') {
    const ok = document.createElement('p')
    ok.className = 'vres-note'
    ok.textContent = 'Nothing sounded wrong. That is a good take.'
    box.appendChild(ok)
  }
}

async function importPart (part) {
  const btn = document.querySelector(`.vpart-pick[data-part="${part}"]`)
  const chosen = await window.soundout.chooseRecording()
  if (!chosen || !chosen.ok) return

  setText('file-' + part, chosen.path.split(/[\\/]/).pop())
  if (btn) { btn.disabled = true; btn.textContent = 'Working on it\u2026' }
  const box = $('result-' + part)
  if (box) { box.hidden = false; box.className = 'vpart-result'; box.textContent = 'Splitting the recording up\u2026 this takes a moment.' }

  try {
    const r = await window.soundout.importRecording({ path: chosen.path, part })
    renderImportResult(part, r)
    // levels and counts depend on what is now recorded
    const st = await window.soundout.getState()
    state.capabilities = st.capabilities
    state.levels = st.levels
    voiceCounts(st.capabilities)
    if (typeof renderLevels === 'function') renderLevels()
  } catch (err) {
    renderImportResult(part, { ok: false, error: String(err && err.message || err) })
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Choose the recording\u2026' }
  }
}

function initVoice () {
  for (const b of document.querySelectorAll('.vpart-pick')) {
    b.addEventListener('click', () => importPart(b.dataset.part))
  }
  const g = $('open-guide')
  if (g) {
    g.addEventListener('click', (e) => {
      e.preventDefault()
      // window.open is blocked in the renderer; the main process opens links.
      if (api.openExternal) api.openExternal(GUIDE_URL)
    })
  }
  voiceCounts(state.capabilities)
}

const GUIDE_URL = 'https://github.com/nwcnwc/sound-it-out/blob/main/RECORDING.md'


/* ------------------------------------------------------------- the studio
 *
 * Prompt an item, record a few takes, score them, keep the best. The scoring
 * lives in gen/studio.py; this is only the pacing and the words on screen.
 *
 * Deliberately automatic: she is reading aloud, often holding a child, and
 * pressing a button between every one of ~40 sounds x 3 takes would be the
 * thing that makes her stop. Press once, and it runs the takes itself.
 */

const studio = {
  items: [], i: 0, takes: 3, part: 'phonemes',
  buf: [], running: false, cancelled: false, paused: false, advanceTimer: null
}

const TAKE_MS = { hold: 2600, crisp: 1200, free: 1600 }
const GAP_MS = 500

function sEl (id) { return $(id) }

async function openStudio (part) {
  studio.part = part
  studio.cancelled = false
  try {
    const plan = await api.studioPlan({ part })
    studio.items = plan.items || []
    studio.takes = plan.takes || 3
  } catch (err) {
    alert('Could not work out what to record: ' + (err.message || err))
    return
  }
  if (!studio.items.length) {
    alert('There is nothing to record yet. Add some words on the Words tab first.')
    return
  }
  // Start where she left off. Progress comes from the saved clips themselves,
  // so it survives quitting, updating, or a week between sittings.
  studio.i = Math.min(plan.resumeAt || 0, Math.max(0, studio.items.length - 1))
  studio.doneCount = plan.done || 0
  if ((plan.done || 0) >= studio.items.length) {
    const again = confirm(
      `All ${studio.items.length} are already recorded.\n\n` +
      'Start again from the beginning?')
    if (!again) return
    studio.i = 0
  }
  $('studio').hidden = false
  document.body.classList.add('studio-open')
  try {
    await Recorder.init()
  } catch (err) {
    sEl('studio-state').textContent =
      'The microphone could not be used. Check that this app is allowed to use it, then try again.'
    return
  }
  showItem()
}

function closeStudio () {
  studio.cancelled = true
  studio.paused = false
  clearTimeout(studio.advanceTimer)
  studio.running = false
  Recorder.release()
  $('studio').hidden = true
  document.body.classList.remove('studio-open')
  refreshVoiceState()
}

function showItem () {
  const it = studio.items[studio.i]
  if (!it) return finishStudio()
  const total = studio.items.length
  const done = studio.items.filter((x) => x.done).length
  sEl('studio-progress').textContent =
    `${studio.i + 1} of ${total}  \u00b7  ${done} recorded`
  const fill = $('studio-bar-fill')
  if (fill) fill.style.width = Math.round((done / total) * 100) + '%'
  sEl('studio-word').textContent = it.display
  sEl('studio-say').textContent = it.say
  sEl('studio-state').textContent = ''
  sEl('studio-result').hidden = true
  sEl('studio-redo').hidden = true
  sEl('studio-go').hidden = false
  sEl('studio-go').disabled = false
  sEl('studio-go').textContent = studio.i === 0 ? 'Start recording' : 'Record this one'
  sEl('studio-pause').hidden = true
  setPaused(false)
  renderTakeDots(0)
}

function renderTakeDots (done) {
  const host = sEl('studio-takes')
  host.innerHTML = ''
  for (let i = 0; i < studio.takes; i++) {
    const d = document.createElement('span')
    d.className = 'take-dot' + (i < done ? ' is-done' : '')
    host.appendChild(d)
  }
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms))

/* Pausing has to be possible mid-item, not only between items: a child
 * interrupts on their own schedule, and 42 sounds x 3 takes is a long sit.
 * Every delay in the sequence goes through here, so Pause takes effect at the
 * next step instead of after the whole item. A take interrupted part-way is
 * discarded and redone on resume - half a sound is worse than none. */
async function pauseGate () {
  while (studio.paused && !studio.cancelled) await wait(120)
  return !studio.cancelled
}

function setPaused (on) {
  studio.paused = on
  const b = $('studio-pause')
  if (b) b.textContent = on ? 'Carry on' : 'Pause'
  if (on) {
    clearTimeout(studio.advanceTimer)
    sEl('studio-state').textContent = 'Paused'
    sEl('studio-meter-fill').style.width = '0%'
    sEl('studio-word').classList.remove('is-live')
  }
}

async function recordItem () {
  const it = studio.items[studio.i]
  studio.running = true
  studio.buf = []
  sEl('studio-go').hidden = true
  sEl('studio-skip').disabled = true

  const dur = TAKE_MS[it.length] || TAKE_MS.free

  sEl('studio-pause').hidden = false

  for (let t = 0; t < studio.takes;) {
    if (!(await pauseGate())) return
    renderTakeDots(t)

    let interrupted = false
    for (let c = 3; c > 0 && !interrupted; c--) {
      sEl('studio-state').textContent = `Ready… ${c}`
      await wait(360)
      if (studio.cancelled) return
      if (studio.paused) interrupted = true
    }
    if (interrupted) continue          // redo this take from the countdown

    sEl('studio-state').textContent = t === 0 ? 'Say it now' : 'Again'
    sEl('studio-word').classList.add('is-live')
    Recorder.start()
    const meter = setInterval(() => {
      sEl('studio-meter-fill').style.width = Math.round(Recorder.level() * 100) + '%'
    }, 60)
    // Slice the wait so a pause lands mid-take rather than after it.
    const step = 100
    for (let waited = 0; waited < dur; waited += step) {
      await wait(step)
      if (studio.cancelled || studio.paused) { interrupted = true; break }
    }
    clearInterval(meter)
    sEl('studio-meter-fill').style.width = '0%'
    const take = Recorder.stop()
    sEl('studio-word').classList.remove('is-live')
    if (studio.cancelled) return
    if (interrupted) continue          // discard the part-take, redo it on resume

    studio.buf.push(take)
    t += 1
    renderTakeDots(t)
    if (t < studio.takes) await wait(GAP_MS)
  }
  sEl('studio-pause').hidden = true

  sEl('studio-state').textContent = 'Checking…'
  try {
    const r = await api.studioSubmit({
      item: it,
      sampleRate: studio.buf[0].sampleRate,
      takes: studio.buf.map((b) => b.b64)
    })
    showTakeResult(r)
  } catch (err) {
    showTakeResult({ allFailed: true, reason: String(err.message || err) })
  }
  studio.running = false
  sEl('studio-skip').disabled = false
}

function showTakeResult (r) {
  const box = sEl('studio-result')
  box.hidden = false
  sEl('studio-state').textContent = ''
  if (r.allFailed) {
    box.className = 'studio-result is-bad'
    const why = (r.takes || []).map((t) => t.fatal).filter(Boolean)[0] || r.reason
    box.textContent = 'None of those could be used. ' + (why || '') + ' Have another go.'
    sEl('studio-redo').hidden = false
    sEl('studio-go').hidden = true
    return
  }
  box.className = 'studio-result is-good'
  box.textContent = 'Kept take ' + (r.best + 1) + '. ' + (r.reason || '')
  if (studio.items[studio.i]) studio.items[studio.i].done = true
  sEl('studio-redo').hidden = false
  // Move on by itself - stopping after every item would double the session.
  clearTimeout(studio.advanceTimer)
  studio.advanceTimer = setTimeout(async () => {
    if (!(await pauseGate())) return
    if (!studio.running && !sEl('studio').hidden) {
      studio.i += 1
      showItem()
      if (studio.items[studio.i]) recordItem()
    }
  }, 1400)
}

function finishStudio () {
  sEl('studio-word').textContent = 'All done'
  sEl('studio-say').textContent = 'That is the whole list recorded.'
  sEl('studio-pause').hidden = true
  sEl('studio-state').textContent = ''
  sEl('studio-go').hidden = true
  sEl('studio-redo').hidden = true
}

async function refreshVoiceState () {
  try {
    const st = await api.getState()
    state.capabilities = st.capabilities
    state.levels = st.levels
    voiceCounts(st.capabilities)
    if (typeof renderLevels === 'function') renderLevels()
  } catch { /* the screen is still usable without a refresh */ }
}

function initStudio () {
  const on = (id, fn) => { const e = $(id); if (e) e.addEventListener('click', fn) }
  for (const b of document.querySelectorAll('.vpart-record')) {
    b.addEventListener('click', () => openStudio(b.dataset.part))
  }
  on('studio-close', closeStudio)
  on('studio-pause', () => setPaused(!studio.paused))
  on('studio-go', recordItem)
  on('studio-skip', () => { studio.i += 1; showItem() })
  on('studio-redo', () => { sEl('studio-result').hidden = true; recordItem() })
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('studio').hidden) closeStudio()
  })
}


/* ---------------------------------------------------------------- the script
 *
 * The importer aligns POSITIONALLY - the nth thing said becomes the nth label -
 * so saying items in a different order mislabels everything after that point.
 * Asking someone to record without telling them what to say, in what order, was
 * not a viable ask. This prints the list from the same source the importer uses,
 * so the two cannot disagree.
 *
 * It is also a single numbered column on purpose: RECORDING.md presents the
 * sounds as two side-by-side columns, which can be read across or downwards,
 * and those give different orders.
 */

async function showScript (part) {
  let plan
  try {
    plan = await api.studioPlan({ part })
  } catch (err) {
    alert('Could not build the list: ' + (err.message || err))
    return
  }
  const title = part === 'phonemes' ? 'What to say - the sounds'
                                    : 'What to say - the words'
  $('script-title').textContent = title

  const body = $('script-body')
  body.innerHTML = ''

  const intro = document.createElement('div')
  intro.className = 'script-intro'
  intro.innerHTML =
    '<h1>' + escapeHtml(title) + '</h1>' +
    '<p><b>Say these in this order</b>, leaving about two seconds of silence between ' +
    'each one. The order matters: the app matches what it hears to this list by ' +
    'position, so a swap puts the wrong name on everything after it.</p>' +
    '<p>If you fluff one, pause and say it again - the last go is the one kept.</p>'
  body.appendChild(intro)

  const ol = document.createElement('ol')
  ol.className = 'script-list'
  for (const it of plan.items) {
    const li = document.createElement('li')
    const big = document.createElement('span')
    big.className = 'script-item'
    big.textContent = it.display
    li.appendChild(big)
    if (it.say) {
      const hint = document.createElement('span')
      hint.className = 'script-hint'
      hint.textContent = it.say
      li.appendChild(hint)
    }
    ol.appendChild(li)
  }
  body.appendChild(ol)

  $('script').hidden = false
  document.body.classList.add('script-open')
}

function initScript () {
  for (const b of document.querySelectorAll('.vpart-script')) {
    b.addEventListener('click', () => showScript(b.dataset.part))
  }
  const close = $('script-close')
  if (close) {
    close.addEventListener('click', () => {
      $('script').hidden = true
      document.body.classList.remove('script-open')
    })
  }
  const pr = $('script-print')
  if (pr) pr.addEventListener('click', () => window.print())
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('script').hidden) {
      $('script').hidden = true
      document.body.classList.remove('script-open')
    }
  })
}


/* -------------------------------------------------------- listen back & redo
 *
 * The first thing anyone does after hearing their own voice is want to redo
 * three of them, so choosing individual items has to be as easy as recording
 * them. Deleting a clip IS the redo: progress is read from the files, so
 * removing one puts exactly that item back in the queue and leaves the rest
 * alone.
 */

const review = { part: 'phonemes', items: [], chosen: new Set(), audio: null }

async function openReview (part) {
  review.part = part
  review.chosen.clear()
  let plan
  try {
    plan = await api.studioPlan({ part })
  } catch (err) {
    alert('Could not load the list: ' + (err.message || err))
    return
  }
  review.items = plan.items || []
  $('review-title').textContent =
    part === 'phonemes' ? 'Listen back - the sounds' : 'Listen back - the words'
  $('review-hint').textContent =
    `${plan.done} of ${plan.total} recorded. Press a word to hear it. ` +
    'Tick any you want to do again, then Re-record selected.'
  renderReview()
  $('review').hidden = false
  document.body.classList.add('script-open')
}

function renderReview () {
  const host = $('review-list')
  host.innerHTML = ''
  for (const it of review.items) {
    const row = document.createElement('div')
    row.className = 'rev-row' + (it.done ? '' : ' is-todo')

    const box = document.createElement('input')
    box.type = 'checkbox'
    box.id = 'rev-' + it.key
    box.disabled = !it.done
    box.checked = review.chosen.has(it.key)
    box.addEventListener('change', () => {
      if (box.checked) review.chosen.add(it.key)
      else review.chosen.delete(it.key)
      $('review-redo').disabled = review.chosen.size === 0
      $('review-redo').textContent = review.chosen.size
        ? `Re-record ${review.chosen.size} selected` : 'Re-record selected'
    })
    row.appendChild(box)

    const label = document.createElement('label')
    label.setAttribute('for', box.id)
    label.className = 'rev-name'
    label.textContent = it.display
    row.appendChild(label)

    const state = document.createElement('span')
    state.className = 'rev-state'
    state.textContent = it.done ? '' : 'not recorded yet'
    row.appendChild(state)

    if (it.done) {
      const play = document.createElement('button')
      play.type = 'button'
      play.className = 'btn btn-quiet rev-play'
      play.textContent = 'Play'
      play.addEventListener('click', () => playClip(it, play))
      row.appendChild(play)
    }
    host.appendChild(row)
  }
}

async function playClip (it, btn) {
  try {
    const r = await api.studioClip({ part: review.part, key: it.key })
    if (!r || !r.path) return
    if (review.audio) { review.audio.pause(); review.audio = null }
    // The renderer is a file:// page, so a file:// media source loads.
    review.audio = new Audio('file://' + encodeURI(r.path).replace(/#/g, '%23'))
    btn.textContent = 'Playing'
    review.audio.addEventListener('ended', () => { btn.textContent = 'Play' })
    await review.audio.play()
  } catch {
    btn.textContent = 'Play'
  }
}

async function redoSelected () {
  const keys = [...review.chosen]
  if (!keys.length) return
  await api.studioRemove({ part: review.part, keys })
  closeReview()
  openStudio(review.part)
}

async function clearPart () {
  const what = review.part === 'phonemes' ? 'sounds' : 'words'
  if (!confirm(`Delete all recorded ${what} and start that part again?\n\n` +
               'The recordings are removed from this computer. This cannot be undone.')) return
  await api.studioRemove({ part: review.part })
  closeReview()
  refreshVoiceState()
}

function closeReview () {
  if (review.audio) { review.audio.pause(); review.audio = null }
  $('review').hidden = true
  document.body.classList.remove('script-open')
  refreshVoiceState()
}

function initReview () {
  for (const b of document.querySelectorAll('.vpart-review')) {
    b.addEventListener('click', () => openReview(b.dataset.part))
  }
  const on = (id, fn) => { const e = $(id); if (e) e.addEventListener('click', fn) }
  on('review-close', closeReview)
  on('review-redo', redoSelected)
  on('review-clear', clearPart)
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('review').hidden) closeReview()
  })
}


/* ------------------------------------------------------------- the passage
 *
 * Continuous, not take-based. The passage is the voice-cloning reference and
 * its whole value is connected prosody - rhythm, melody, where the breaths
 * fall - so it must be read straight through rather than assembled from
 * fragments. Pause carries on into the same take rather than starting a new
 * one, because six unbroken minutes is not realistic with a child in the house.
 */

const reader = { recording: false, paused: false, tick: null }

async function openReader () {
  try {
    const t = await api.passageText()
    const body = $('reader-body')
    body.innerHTML = ''
    for (const block of (t.markdown || '').split('\n\n')) {
      const line = block.trim()
      if (!line) continue
      const el = document.createElement(line.startsWith('##') ? 'h3' : 'p')
      el.textContent = line.replace(/^#+\s*/, '')
      body.appendChild(el)
    }
  } catch (err) {
    alert('Could not load the passage: ' + (err.message || err))
    return
  }
  try {
    await Recorder.init()
  } catch {
    alert('The microphone could not be used. Check this app is allowed to use it.')
    return
  }
  $('reader-result').hidden = true
  $('reader').hidden = false
  document.body.classList.add('script-open')
}

function readerClock () {
  const s = Math.floor(Recorder.seconds())
  $('reader-clock').textContent =
    Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0')
  $('reader-level').style.width = Math.round(Recorder.level() * 100) + '%'
}

function startReading () {
  Recorder.start()
  reader.recording = true
  reader.paused = false
  $('reader-go').hidden = true
  $('reader-pause').hidden = false
  $('reader-done').hidden = false
  reader.tick = setInterval(readerClock, 200)
}

function toggleReaderPause () {
  if (!reader.recording) return
  reader.paused = !reader.paused
  if (reader.paused) Recorder.pause()
  else Recorder.resume()
  $('reader-pause').textContent = reader.paused ? 'Carry on' : 'Pause'
}

async function finishReading () {
  clearInterval(reader.tick)
  reader.recording = false
  const take = Recorder.stop()
  $('reader-pause').hidden = true
  $('reader-done').hidden = true
  const box = $('reader-result')
  box.hidden = false
  box.className = 'reader-result'
  box.textContent = 'Checking the recording…'
  try {
    const r = await api.studioPassage({ audio: take.b64, sampleRate: take.sampleRate })
    const fails = (r.issues || []).filter((i) => i.severity === 'fail')
    box.className = 'reader-result ' + (fails.length ? 'is-bad' : 'is-good')
    box.textContent = (fails.length
      ? fails.map((i) => i.message).join(' ')
      : 'Saved. ' + (r.notes || []).join(' ')) +
      (fails.length ? ' Press Start reading to go again.' : '')
    $('reader-go').hidden = false
    $('reader-go').textContent = fails.length ? 'Read it again' : 'Record it again'
  } catch (err) {
    box.className = 'reader-result is-bad'
    box.textContent = 'That could not be saved: ' + (err.message || err)
    $('reader-go').hidden = false
  }
  refreshVoiceState()
}

function closeReader () {
  clearInterval(reader.tick)
  if (reader.recording) Recorder.stop()
  reader.recording = false
  Recorder.release()
  $('reader').hidden = true
  document.body.classList.remove('script-open')
}

function initReader () {
  const on = (id, fn) => { const e = $(id); if (e) e.addEventListener('click', fn) }
  on('read-passage', openReader)
  on('reader-go', startReading)
  on('reader-pause', toggleReaderPause)
  on('reader-done', finishReading)
  on('reader-close', closeReader)
}
