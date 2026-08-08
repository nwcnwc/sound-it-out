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
  initVoiceSettings()
  setUpWords()
  initSentences()
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

/* ------------------------------------------------------------- sentences */

/* The sentence library. One list drives two places: the Sentences tab (add,
 * record, remove) and the picker on the Make screen (which ones go in the
 * video). Both re-render from the same fetch so they can never disagree. */

let sentenceLib = []

async function refreshSentences () {
  if (!api.sentencesList) return
  try {
    const r = await api.sentencesList()
    sentenceLib = (r && r.sentences) || []
  } catch (err) {
    console.error(err)
  }
  renderSentenceLib()
  renderSentencePicker()
  updateSummary()
}

function renderSentenceLib () {
  const host = $('sentence-list')
  if (!host) return
  host.textContent = ''

  if (!sentenceLib.length) {
    const p = document.createElement('p')
    p.className = 'hint'
    p.textContent = 'Nothing here yet. Add a sentence above — anything you would like read.'
    host.appendChild(p)
    return
  }

  for (const s of sentenceLib) {
    const row = document.createElement('div')
    row.className = 'sentence-row'

    const text = document.createElement('div')
    text.className = 'sentence-text'
    text.textContent = s.text

    const stat = document.createElement('p')
    stat.className = 'sentence-status' + (s.ready ? ' is-ready' : '')
    if (s.ready) {
      stat.textContent = 'Recorded, in your own voice. Ready to use.'
    } else {
      const bits = []
      if (s.missing && s.missing.length) bits.push(s.missing.join(', '))
      if (!s.lineRecorded) bits.push('the whole line')
      stat.textContent = 'Still to record: ' + bits.join(', and ') +
        '. It can be used now — the built-in voice fills the gaps.'
    }

    const bar = document.createElement('div')
    bar.className = 'rowbar'

    const rec = document.createElement('button')
    rec.type = 'button'
    rec.className = s.ready ? 'btn btn-second' : 'btn btn-primary'
    rec.textContent = s.ready ? 'Record it again' : 'Record it'
    rec.addEventListener('click', () => {
      openStudio('sentence', { key: s.key }).catch((err) => {
        alert('Could not start recording: ' + (err.message || err))
      })
    })

    const del = document.createElement('button')
    del.type = 'button'
    del.className = 'btn btn-quiet'
    del.textContent = 'Remove'
    del.addEventListener('click', async () => {
      const sure = confirm(
        'Take this sentence off the list?\n\n' +
        'Its recordings are kept — the words serve your other sentences, and ' +
        'the line comes straight back if you ever re-add it.')
      if (!sure) return
      try {
        const r = await api.sentencesRemove(s.key)
        sentenceLib = (r && r.sentences) || []
      } catch (err) {
        alert('Could not remove it: ' + (err.message || err))
      }
      renderSentenceLib()
      renderSentencePicker()
      updateSummary()
    })

    bar.append(rec, del)
    row.append(text, stat, bar)
    host.appendChild(row)
  }
}

function initSentences () {
  const add = $('sentence-add')
  if (!add) return
  add.addEventListener('click', async () => {
    const box = $('sentence-input')
    const msg = $('sentence-error')
    msg.hidden = true
    let r
    try {
      r = await api.sentencesAdd(box.value)
    } catch (err) {
      r = { ok: false, error: String(err.message || err) }
    }
    if (r && r.ok === false) {
      msg.hidden = false
      msg.textContent = r.error || 'That could not be added.'
      return
    }
    box.value = ''
    sentenceLib = (r && r.sentences) || sentenceLib
    renderSentenceLib()
    renderSentencePicker()
    updateSummary()
  })
  refreshSentences()
}

/* The picker on the Make screen: same library, as tickboxes. */

function renderSentencePicker () {
  const host = $('level-sentences')
  if (!host) return
  const before = new Set(pickedSentences())
  const hadAny = host.querySelector('input') !== null
  host.textContent = ''

  if (!sentenceLib.length) {
    const p = document.createElement('p')
    p.className = 'hint'
    p.textContent = 'Add sentences on the Sentences tab first.'
    host.appendChild(p)
    return
  }

  for (const s of sentenceLib) {
    const label = document.createElement('label')
    label.className = 'choice'

    const input = document.createElement('input')
    input.type = 'checkbox'
    input.name = 'sentence'
    input.value = s.key
    // Everything ticked by default; after that, keep whatever she set.
    input.checked = hadAny ? before.has(s.key) : true

    const tick = document.createElement('span')
    tick.className = 'tick'
    tick.setAttribute('aria-hidden', 'true')

    const text = document.createElement('span')
    text.className = 'choice-text'
    const title = document.createElement('span')
    title.className = 'choice-title'
    title.textContent = s.text
    text.appendChild(title)
    if (!s.ready) {
      const d = document.createElement('span')
      d.className = 'choice-desc'
      d.textContent = 'Not fully recorded yet — the built-in voice fills the gaps.'
      text.appendChild(document.createElement('br'))
      text.appendChild(d)
    }

    label.append(input, tick, text)
    host.appendChild(label)
  }
}

function pickedSentences () {
  return Array.from(document.querySelectorAll('input[name="sentence"]:checked'))
    .map((i) => i.value)
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
  renderSegmented($('stage'), 'stage', STAGES, chosen.stage || 2)

  // Delegated, because renderLevels() and renderSegmented() replace their
  // inputs - a listener bound to the elements that exist right now would stop
  // firing the moment the level list is re-rendered, which it is every time
  // recordings change.
  $('screen-make').addEventListener('change', (e) => {
    if (e.target && (e.target.type === 'radio' || e.target.type === 'checkbox')) {
      showLevelExtras()
      updateSummary()
      persistChoices()
    }
  })

  const box = $('level-text')
  if (box) {
    box.value = chosen.text || ''
    box.addEventListener('input', () => {
      updateTextCount()
      updateSummary()
      persistChoices()
    })
  }
  showLevelExtras()

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
  // The list is rebuilt whenever recordings change, which can move the
  // selection - the extras have to follow it.
  if (typeof showLevelExtras === 'function') showLevelExtras()
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

const STAGES = [
  { value: 1, label: 'Just the first few' },
  { value: 2, label: 'A good number' },
  { value: 3, label: 'Most of them' }
]

function currentOptions () {
  const o = {
    level: picked('level'),
    theme: picked('theme'),
    reps: Number(picked('reps')),
    pauseSeconds: Number(picked('pause')),
    minutes: Number(picked('minutes')),
    // Only meaningful to the open-ended levels; harmless everywhere else.
    text: ($('level-text') && $('level-text').value) || '',
    stage: Number(picked('stage')) || 2
  }
  // Which library sentences to read. Only for level 13: an empty list must
  // mean "none ticked" there, and nothing at all everywhere else.
  if (String(o.level) === '13') o.sentences = pickedSentences()
  return o
}

/* The open-ended levels need something the fixed ones do not - text to read,
 * or how far the child has got. Showing those controls all the time would put
 * a big empty textarea in front of someone making a Paw Patrol video, so they
 * appear only for the level they belong to. */
function showLevelExtras () {
  const id = String(picked('level'))
  const lvl = (state.levels || []).find((l) => String(l.id) === id)
  const textWrap = $('level-text-wrap')
  const stageWrap = $('level-stage-wrap')
  const sentWrap = $('level-sentences-wrap')
  if (textWrap) textWrap.hidden = !(lvl && lvl.needsText)
  if (stageWrap) stageWrap.hidden = id !== '12'
  if (sentWrap) sentWrap.hidden = !(lvl && lvl.needsSentences)
  updateTextCount()
  updateStageNote()
}

function updateTextCount () {
  const box = $('level-text')
  const out = $('level-text-count')
  if (!box || !out) return
  const words = box.value.trim().split(/\s+/).filter(Boolean).length
  const lines = box.value.trim()
    ? box.value.trim().split(/(?<=[.!?])\s+/).filter(Boolean).length : 0
  out.textContent = words
    ? `${words} words, about ${lines} line${lines === 1 ? '' : 's'} to read.`
    : 'Nothing pasted in yet.'
}

function updateStageNote () {
  const note = $('stage-note')
  if (!note) return
  const n = Number(picked('stage')) || 2
  note.textContent = [
    '',
    'The story stays very short - only s, a, t, p, i, n.',
    'Sam, the cat and the dog appear.',
    'Nearly the whole story, including "the".'
  ][n] || ''
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

  const id = String(o.level)
  const usesWords = id === '1' || id === '2'
  let words = usesWords ? ', drawn from the ' + total + ' words on your list' : ''

  // The open-ended levels are worth describing differently: what makes them
  // interesting is where the content comes from, and that is the thing a
  // parent cannot see by reading the level name.
  if (id === '13') {
    const n = (o.sentences || []).length
    if (!n) {
      el.textContent = sentenceLib.length
        ? 'Tick at least one sentence to read.'
        : 'Add a sentence or two on the Sentences tab first.'
      $('btn-play').disabled = true
      $('btn-export').disabled = true
      return
    }
    words = ', building up ' + n + ' of your own sentence' + (n === 1 ? '' : 's')
  } else if (id === '10') {
    const n = (o.text || '').trim().split(/(?<=[.!?])\s+/).filter(Boolean).length
    words = n ? ', reading the ' + n + ' line' + (n === 1 ? '' : 's') + ' you pasted in' : ''
  } else if (id === '11') {
    words = ', built from the names and things on your own list'
  } else if (id === '12') {
    words = ', using only the letters they have learned so far'
  }

  el.textContent = o.minutes + ' minutes of ' + level.name + words +
    ', each one shown ' + o.reps + ' times, then it loops.'

  // These are the levels the cloned voice exists for. Say so once, here,
  // where the choice is being made - not on a settings screen they may never
  // open.
  if (level.kind === 'open' && level.reason) {
    el.textContent += ' ' + level.reason
  }

  // And if it IS installed, say what it will cost in time.
  //
  // Making speech in her voice runs far slower than realtime on an ordinary
  // laptop - measured at about 128 seconds of computing per second of speech.
  // A page of pasted text is therefore an hours-long job the first time, which
  // is survivable if you know before you start and infuriating if you find out
  // afterwards. Every clip is cached, so this is a one-off per sentence.
  const warn = $('make-slow')
  if (warn) {
    const rate = (state.cloneInfo && state.cloneInfo.seconds_per_second) || 0
    const lines = id === '10'
      ? (o.text || '').trim().split(/(?<=[.!?])\s+/).filter(Boolean).length
      : id === '11' ? 20 : 25
    const usingClone = level.kind === 'open' &&
      state.capabilities && state.capabilities.cloning
    if (usingClone && rate && lines) {
      // ~1.6s of speech per line, from the measured samples.
      const mins = Math.round(lines * 1.6 * rate / 60)
      warn.hidden = false
      warn.textContent = mins < 5
        ? `The first time, this takes a few minutes to say in your voice. After that it is instant.`
        : `Heads up: making this in your voice takes roughly ${
            mins < 90 ? mins + ' minutes' : (mins / 60).toFixed(1) + ' hours'
          } the first time, because your computer has to generate every line. ` +
          `You can leave it running. Once made, each line is kept and is instant afterwards.`
    } else {
      warn.hidden = true
    }
  }
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

  // Catch the empty-textarea case here rather than letting the sidecar raise
  // it. The backend message is correct but arrives after the progress screen
  // has taken over, which reads as a crash rather than as something missing.
  const lvl = (state.levels || []).find((l) => String(l.id) === String(picked('level')))
  if (lvl && lvl.needsText && !($('level-text').value || '').trim()) {
    const box = $('level-text')
    $('level-text-wrap').hidden = false
    box.focus()
    box.scrollIntoView({ block: 'center' })
    setText('level-text-count',
      'Paste something in first - this level reads whatever you give it.')
    return
  }

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

  // Say up front what this needs and whether the computer has it. The space
  // check is instant, and finding out you are short only after committing to a
  // 3 GB download is a bad way to learn it.
  api.cloningInfo().then((info) => {
    // Kept for the time estimate on the open-ended levels, which is the one
    // number that decides whether a parent starts a render or walks away.
    if (info && info.ok !== false) { state.cloneInfo = info; updateSummary() }
    if (!info || info.ok === false || info.enough_space !== false) return
    const gb = (n) => (n / 1e9).toFixed(1) + ' GB'
    btn.disabled = true
    status.hidden = false
    status.className = 'install-status is-bad'
    status.textContent =
      `This needs about ${gb(info.install_bytes)} free while it installs, and ` +
      `there is ${gb(info.free_bytes)} on this computer. Free up about ` +
      `${gb(info.install_bytes - info.free_bytes)} and reopen this screen. ` +
      'Everything else works without it.'
  }).catch(() => { /* the button still works; the check is a courtesy */ })

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
    status.className = 'install-status'
    // Clear the previous attempt's message. Without this a retry that fails
    // the same way instantly looks like a dead button: same text, no bar, no
    // visible change at all.
    status.textContent = 'Starting the download. This can take a while — it carries on in the background.'
    try {
      const res = await api.installCloning()
      // res.error is the real reason - out of disk space, no network, a
      // refused connection. It used to be replaced here with a generic
      // "install failed" and then reported as an internet problem, so
      // somebody 2 GB short of disk was told to check their wifi and given a
      // button that could only fail again.
      if (res && res.ok === false) throw new Error(res.error || 'The download did not finish.')
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
      status.className = 'install-status is-bad'
      const why = String((e && e.message) || '').trim()
      status.textContent = why ||
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

const PART_NAMES = {
  phonemes: 'sounds', words: 'words', sentences: 'sentences', passage: 'reading passage'
}

async function voiceCounts (caps) {
  const p = (caps && caps.recorded_phonemes) || 0
  const w = (caps && caps.recorded_words) || 0
  const sn = (caps && caps.recorded_sentences) || 0

  // Totals come from the plan so the denominator is always the real list -
  // adding a word to the word list changes what "finished" means.
  let totals = { phonemes: 42, words: w, sentences: sn }
  try {
    const [ps, ws, ss] = await Promise.all([
      api.studioPlan({ part: 'phonemes' }), api.studioPlan({ part: 'words' }),
      api.studioPlan({ part: 'sentences' })
    ])
    totals = { phonemes: ps.total, words: ws.total, sentences: ss.total }
  } catch { /* fall back to what we know */ }

  showPartProgress('phonemes', p, totals.phonemes)
  showPartProgress('words', w, totals.words)
  showPartProgress('sentences', sn, totals.sentences)
  showPassageState()
  for (const [part, n] of [['phonemes', p], ['words', w], ['sentences', sn]]) {
    const b = document.querySelector(`.vpart-review[data-part="${part}"]`)
    if (b) b.hidden = n === 0
  }

  const foot = $('voice-foot')
  if (!foot) return
  const total = totals.phonemes + totals.words + totals.sentences
  const done = p + w + sn
  foot.textContent = done === 0
    ? 'Nothing recorded yet \u2014 the computer voice is being used for now.'
    : done >= total
      ? 'All recorded. Everything in the early levels is your own voice.'
      : `${done} of ${total} recorded. You can stop and carry on whenever \u2014 ` +
        'it picks up where you left off.'
}

/* The passage had no state on screen at all - no length, no level, no way to
 * hear it. Six minutes of reading went in and the app said nothing back, so
 * there was no way to tell a good recording from six minutes of silence until
 * the cloned voice came out wrong.
 *
 * It is one file rather than a list, so it gets its own small readout instead
 * of a progress bar. */
let passageAudio = null

async function showPassageState () {
  const btn = $('play-passage')
  try {
    const r = await api.studioClip({ part: 'passage' })
    if (!r || !r.path) {
      setText('count-passage', '')
      if (btn) btn.hidden = true
      return
    }
    const clock = (s) => Math.floor(s / 60) + ':' +
      String(Math.round(s % 60)).padStart(2, '0')
    setText('count-passage', r.silent
      ? '— recorded, but silent'
      : r.short
        // Stopping early is invisible otherwise: the file is real and plays
        // fine, it is just not the whole script, and the only symptom is a
        // cloned voice that never sounds quite right.
        ? `— only ${clock(r.seconds)} recorded, and the whole passage takes ` +
          `about ${clock(r.expectedSeconds)}. It looks like it stopped early.`
        : `— ${clock(r.seconds)} recorded`)
    if (btn) btn.hidden = false
  } catch {
    if (btn) btn.hidden = true
  }
}

async function playPassage () {
  const btn = $('play-passage')
  if (!btn) return

  // Second press stops it. Six minutes is far too long to sit through with no
  // way out, and there is nowhere obvious to put a separate Stop button.
  if (passageAudio) {
    passageAudio.pause()
    passageAudio = null
    btn.textContent = 'Listen back'
    return
  }
  try {
    const r = await api.studioClip({ part: 'passage' })
    if (!r || !r.path) return
    if (r.silent) {
      setText('count-passage', '— recorded, but silent - record it again')
      return
    }
    passageAudio = new Audio('file://' + encodeURI(r.path).replace(/#/g, '%23'))
    btn.textContent = 'Stop'
    const done = () => { passageAudio = null; btn.textContent = 'Listen back' }
    passageAudio.addEventListener('ended', done)
    passageAudio.addEventListener('error', () => {
      done()
      setText('count-passage', '— could not play it here; the file itself is fine')
    })
    await passageAudio.play()
  } catch (err) {
    passageAudio = null
    btn.textContent = 'Listen back'
    setText('count-passage', '— could not play: ' + (err.message || err))
  }
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
 *
 * How many takes comes from the plan, not from here - gen/studio.py asks for
 * three on the phonemes and one on the words. Three attempts at an isolated
 * /t/ is worth it; three attempts at "dog" is just a longer afternoon. The
 * safety net on a single take is the scorer, which flags anything she could
 * fix and stops rather than sliding on to the next word.
 */

const studio = {
  items: [], i: 0, takes: 3, part: 'phonemes',
  buf: [], running: false, cancelled: false, paused: false, advanceTimer: null
}

// "line" is a whole sentence read aloud to a child - unhurried, it needs
// several seconds. Missing from this table, it fell through to `free` and
// the recording stopped at 1.6s, mid-line.
const TAKE_MS = { hold: 2600, crisp: 1200, free: 1600, line: 6000 }
const GAP_MS = 500

function sEl (id) { return $(id) }

async function openStudio (part, extra) {
  studio.part = part
  studio.cancelled = false
  // `plan` is used well below, so it must not be scoped to the try block.
  let plan
  try {
    // `extra` carries anything beyond the part itself - the sentence
    // walk-through passes the sentence's key this way.
    plan = await api.studioPlan(Object.assign({ part }, extra || {}))
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
  startMicCheck()
}

/* Runs before the first item. Requires actually HEARING something before the
 * session can start, because "record 42 sounds, then discover the microphone
 * was dead" is a 15 minute loss and it has already happened once. */
function startMicCheck () {
  const check = $('miccheck')
  const stage = $('studio-stage')
  if (!check || !stage) { showItem(); return }
  check.hidden = false
  stage.hidden = true
  let best = 0
  studio.micWaits = 0
  clearInterval(studio.micTimer)
  studio.micTimer = setInterval(() => {
    const l = Recorder.level()
    best = Math.max(best, l)
    $('mic-meter').style.width = Math.round(l * 100) + '%'
    if (best > 0.06) {
      $('mic-verdict').textContent = 'That is working. Press Start recording when ready.'
      $('mic-ok').disabled = false
    } else {
      studio.micWaits = (studio.micWaits || 0) + 1
      // After ~8 seconds of nothing, stop saying "waiting" and say what to do.
      $('mic-verdict').textContent = studio.micWaits > 80
        ? 'Still not hearing anything. The computer may be blocking microphone ' +
          'access for this app - check your system sound settings, and that the ' +
          'right microphone is selected.'
        : 'Waiting to hear you\u2026'
    }
  }, 100)
}

function endMicCheck () {
  clearInterval(studio.micTimer)
  $('miccheck').hidden = true
  $('studio-stage').hidden = false
  showItem()
}

function closeStudio () {
  clearInterval(studio.micTimer)
  studio.cancelled = true
  studio.paused = false
  clearTimeout(studio.advanceTimer)
  studio.running = false
  Recorder.release()
  $('studio').hidden = true
  document.body.classList.remove('studio-open')
  refreshVoiceState()
  // A sentence walk-through changes what the Sentences tab and the Make
  // picker should show, whichever screen she goes back to.
  refreshSentences()
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
  sEl('studio-redo').textContent = 'Do that one again'
  sEl('studio-go').hidden = false
  sEl('studio-go').disabled = false
  // Clear the "Carry on" role a flagged take may have left on this button,
  // or the next press would skip an item instead of recording it.
  delete sEl('studio-go').dataset.next
  sEl('studio-go').textContent = studio.i === 0 ? 'Start recording' : 'Record this one'
  sEl('studio-pause').hidden = true
  sEl('studio-skip').hidden = false
  sEl('studio-meter').hidden = false
  sEl('studio-close').textContent = 'Finish for now'
  setPaused(false)
  renderTakeDots(0)
}

function renderTakeDots (done) {
  const host = sEl('studio-takes')
  host.innerHTML = ''
  // One take needs no progress dots - a single dot says nothing that the
  // recording indicator does not already say.
  if (studio.takes < 2) return
  for (let i = 0; i < studio.takes; i++) {
    const d = document.createElement('span')
    d.className = 'take-dot' + (i < done ? ' is-done' : '')
    host.appendChild(d)
  }
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms))

/* Pausing has to be possible mid-item, not only between items: a child
 * interrupts on their own schedule, and 42 sounds x 3 takes is a long sit,
 * with over a hundred words after it.
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
  if (studio.items[studio.i]) studio.items[studio.i].done = true
  sEl('studio-redo').hidden = false

  // Kept, but something is off that she could fix. Say what, and let her
  // decide - the clip is already saved, so carrying on costs nothing and
  // having another go costs one word.
  //
  // This must NOT auto-advance. On a single take there is no better attempt
  // to fall back on, so a warning that scrolls past on a timer is the same as
  // no warning at all.
  if (r.weak) {
    box.className = 'studio-result is-warn'
    box.textContent = 'Saved, but ' + (r.advice || []).join(', and ') +
      '. Have another go, or carry on.'
    sEl('studio-go').hidden = false
    sEl('studio-go').disabled = false
    sEl('studio-go').textContent = 'Carry on'
    sEl('studio-go').dataset.next = '1'
    sEl('studio-redo').textContent = 'Try that one again'
    clearTimeout(studio.advanceTimer)
    return
  }

  box.className = 'studio-result is-good'
  // The wording of r.reason already follows the number of takes, so do not
  // prepend anything here - "Got it. Best of the takes..." was the result of
  // saying it in two places at once.
  box.textContent = studio.takes < 2
    ? (r.reason || 'Got it.')
    : 'Kept take ' + (r.best + 1) + '. ' + (r.reason || '')
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
  // The header last rendered when the final item was SHOWN - i.e. before it
  // was recorded - which is why it read "42 of 42 - 41 recorded". Recount here.
  const total = studio.items.length
  const done = studio.items.filter((x) => x.done).length
  const missed = total - done

  sEl('studio-progress').textContent = `${done} of ${total} recorded`
  const fill = $('studio-bar-fill')
  if (fill) fill.style.width = Math.round((done / total) * 100) + '%'

  const what = studio.part === 'phonemes' ? 'sounds'
    : studio.part === 'sentence' ? 'parts' : 'words'
  sEl('studio-word').textContent = missed ? 'Finished' : 'All done'
  sEl('studio-say').textContent = missed
    ? `${done} of the ${total} ${what} are recorded. ` +
      `${missed} ${missed === 1 ? 'was' : 'were'} skipped \u2014 you can come ` +
      'back to those any time from Listen back.'
    : `All ${total} ${what} recorded, in your own voice.`

  // Nothing left to act on here, so leave only the way out.
  sEl('studio-state').textContent = ''
  sEl('studio-pause').hidden = true
  sEl('studio-go').hidden = true
  sEl('studio-redo').hidden = true
  sEl('studio-skip').hidden = true
  sEl('studio-takes').innerHTML = ''
  sEl('studio-result').hidden = true
  sEl('studio-meter').hidden = true
  sEl('studio-close').textContent = 'Done'
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
    b.addEventListener('click', () => {
      openStudio(b.dataset.part).catch((err) => {
        console.error(err)
        alert('Recording could not start: ' + (err.message || err))
      })
    })
  }
  on('mic-ok', endMicCheck)
  on('mic-skip', endMicCheck)
  on('studio-close', closeStudio)
  on('studio-pause', () => setPaused(!studio.paused))
  on('studio-go', () => {
    // After a flagged take this button means "carry on", not "record".
    if (sEl('studio-go').dataset.next === '1') {
      studio.i += 1
      showItem()
      if (studio.items[studio.i]) recordItem()
      return
    }
    recordItem()
  })
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
  const title = 'What to say - the ' + (PART_NAMES[part] || 'words')
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
  const note = btn.parentElement.querySelector('.rev-state')
  try {
    const r = await api.studioClip({ part: review.part, key: it.key })
    if (!r || !r.path) { if (note) note.textContent = 'not found'; return }

    // Say what is in the clip, so silence on playback can be told apart from
    // a headphone problem. Without this both look identical.
    if (r.silent) {
      if (note) note.textContent = 'this clip is silent - re-record it'
      btn.textContent = 'Play'
      return
    }
    if (note) note.textContent = `${r.seconds}s, level ${Math.round(r.peak * 100)}%`

    if (review.audio) { review.audio.pause(); review.audio = null }
    review.audio = new Audio('file://' + encodeURI(r.path).replace(/#/g, '%23'))
    btn.textContent = 'Playing'
    review.audio.addEventListener('ended', () => { btn.textContent = 'Play' })
    review.audio.addEventListener('error', () => {
      btn.textContent = 'Play'
      if (note) note.textContent = 'could not play it here - the clip itself is fine'
    })
    await review.audio.play()
  } catch (err) {
    btn.textContent = 'Play'
    if (note) note.textContent = 'could not play: ' + (err.message || err)
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
  const what = PART_NAMES[review.part] || 'recordings'
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

/* Plays a tone through the same audio path the clips use. If this is silent
 * the problem is the speakers or the output device, not the recordings - which
 * is otherwise impossible to tell from the app. */
async function testSpeakers (btn) {
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = 440
    gain.gain.value = 0.18
    osc.connect(gain).connect(ctx.destination)
    btn.textContent = 'Playing a tone…'
    osc.start()
    await new Promise((r) => setTimeout(r, 900))
    osc.stop()
    await ctx.close()
    btn.textContent = 'Heard it? Speakers are fine'
  } catch (err) {
    btn.textContent = 'Could not play a tone: ' + (err.message || err)
  }
}

function initReview () {
  const t = $('review-test')
  if (t) t.addEventListener('click', () => testSpeakers(t))
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
 * Recorded one section at a time, and resumable.
 *
 * It used to be a single unbroken take of about five minutes, on the reasoning
 * that the passage is the voice-cloning reference and connected prosody is its
 * whole value. The prosody argument is right; the conclusion was not. Five
 * undisturbed minutes is precisely what a parent with a small child does not
 * have, and what actually happened was a session interrupted part-way, leaving
 * thirty-three seconds of a five-minute script on disk - a real, playable file
 * that simply was not the passage.
 *
 * Sections are 20-70 seconds each, which is far more connected speech than a
 * reference needs, and they break where PASSAGE.md has always told her she may
 * stop. Splitting any finer - per paragraph, per sentence - would start eating
 * into the prosody that matters, so it is not offered.
 */

const reader = { recording: false, paused: false, tick: null, plan: null, i: 0 }

function clockText (s) {
  return Math.floor(s / 60) + ':' + String(Math.round(s % 60)).padStart(2, '0')
}

async function openReader () {
  try {
    reader.plan = await api.passagePlan()
  } catch (err) {
    alert('Could not load the passage: ' + (err.message || err))
    return
  }
  if (!reader.plan.total) {
    alert('The passage could not be read from this copy of the app.')
    return
  }
  try {
    await Recorder.init()
  } catch {
    alert('The microphone could not be used. Check this app is allowed to use it.')
    return
  }
  // Pick up where she left off rather than making her find her place.
  reader.i = Math.min(reader.plan.resumeAt, reader.plan.total - 1)
  $('reader-result').hidden = true
  $('reader').hidden = false
  document.body.classList.add('script-open')
  showSection()
}

/* The row of section chips: progress, and a way to go back and redo one. */
function renderParts () {
  const host = $('reader-parts')
  if (!host) return
  host.innerHTML = ''
  reader.plan.sections.forEach((sec, n) => {
    const b = document.createElement('button')
    b.type = 'button'
    b.className = 'part-chip' +
      (sec.done ? ' is-done' : '') + (n === reader.i ? ' is-current' : '')
    b.textContent = (n + 1) + (sec.done ? ' \u2713' : '')
    b.title = sec.title + (sec.done ? ` \u2014 ${clockText(sec.seconds)} recorded` : '')
    b.setAttribute('aria-label',
      `Part ${n + 1}, ${sec.title}` + (sec.done ? ', recorded' : ', not recorded yet'))
    // Not while recording: switching mid-take would silently bin it.
    b.addEventListener('click', () => {
      if (reader.recording) return
      reader.i = n
      showSection()
    })
    host.appendChild(b)
  })
}

function showSection () {
  const sec = reader.plan.sections[reader.i]
  if (!sec) return finishedAll()

  renderParts()
  setText('reader-title', `Part ${reader.i + 1} of ${reader.plan.total}: ${sec.title}`)

  const left = reader.plan.total - reader.plan.done
  setText('reader-lede', sec.done
    ? `You have already read this one (${clockText(sec.seconds)}). ` +
      'Reading it again replaces it.'
    : `About ${clockText(sec.expectedSeconds)}. ` +
      (left > 1
        ? `${left} parts left \u2014 you can stop after any of them and carry on later.`
        : 'This is the last one.'))

  const body = $('reader-body')
  body.innerHTML = ''
  for (const para of sec.text.split('\n\n')) {
    const el = document.createElement('p')
    el.textContent = para
    body.appendChild(el)
  }
  body.scrollTop = 0

  $('reader-result').hidden = true
  $('reader-clock').textContent = '0:00'
  $('reader-go').hidden = false
  $('reader-go').textContent = sec.done ? 'Read this part again' : 'Start reading'
  $('reader-pause').hidden = true
  $('reader-done').hidden = true
}

function finishedAll () {
  setText('reader-title', 'That is the whole passage')
  setText('reader-lede', '')
  renderParts()
  $('reader-body').innerHTML = ''
  const box = $('reader-result')
  box.hidden = false
  box.className = 'reader-result is-good'
  box.textContent = 'All ' + reader.plan.total + ' parts recorded, ' +
    clockText(reader.plan.recordedSeconds) + ' in total. ' +
    'You can pick any part above to read it again.'
  $('reader-go').hidden = true
  $('reader-pause').hidden = true
  $('reader-done').hidden = true
}

function readerClock () {
  $('reader-clock').textContent = clockText(Recorder.seconds())
  $('reader-level').style.width = Math.round(Recorder.level() * 100) + '%'
}

function startReading () {
  Recorder.start()
  reader.recording = true
  reader.paused = false
  $('reader-go').hidden = true
  $('reader-pause').hidden = false
  $('reader-done').hidden = false
  $('reader-result').hidden = true
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
  const sec = reader.plan.sections[reader.i]
  $('reader-pause').hidden = true
  $('reader-pause').textContent = 'Pause'
  $('reader-done').hidden = true
  const box = $('reader-result')
  box.hidden = false
  box.className = 'reader-result'
  box.textContent = 'Saving this part\u2026'
  try {
    const r = await api.studioPassage({
      audio: take.b64, sampleRate: take.sampleRate, index: reader.i
    })
    if (r.plan) reader.plan = r.plan
    const saved = reader.plan.sections[reader.i]
    const fails = (r.issues || []).filter((i) => i.severity === 'fail')

    // Cut short is the one failure this whole arrangement exists to catch, so
    // it is checked per part rather than only at the end.
    if (saved && saved.short) {
      box.className = 'reader-result is-warn'
      box.textContent = `Saved, but that was only ${clockText(saved.seconds)} and this ` +
        `part takes about ${clockText(saved.expectedSeconds)}. If you stopped early, ` +
        'read it again - otherwise carry on.'
      $('reader-go').hidden = false
      $('reader-go').textContent = 'Read this part again'
      renderParts()
      refreshVoiceState()
      return
    }

    box.className = 'reader-result ' + (fails.length ? 'is-bad' : 'is-good')
    box.textContent = fails.length
      ? fails.map((i) => i.message).join(' ')
      : 'Saved. ' + ((r.notes || []).join(' ') || '')

    // On to the next unrecorded part, so a parent with a spare minute does not
    // have to decide anything to use it.
    const next = reader.plan.sections.findIndex((x) => !x.done)
    if (next === -1) return finishedAll()
    reader.i = next
    setTimeout(() => { if (!reader.recording && !$('reader').hidden) showSection() }, 1200)
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
  refreshVoiceState()
}

function initReader () {
  const on = (id, fn) => { const e = $(id); if (e) e.addEventListener('click', fn) }
  on('read-passage', openReader)
  on('play-passage', playPassage)
  on('reader-go', startReading)
  on('reader-pause', toggleReaderPause)
  on('reader-done', finishReading)
  on('reader-close', closeReader)
}


/* ------------------------------------------------------- recordings settings
 *
 * The clips live in the app's data folder - inside Library on macOS, where
 * nobody would find them and nothing would back them up. Showing the path is
 * the small part; the backup button is the point.
 */

function human (bytes) {
  if (!bytes) return '0 MB'
  const mb = bytes / 1048576
  return mb < 1 ? Math.round(bytes / 1024) + ' KB' : mb.toFixed(1) + ' MB'
}

async function refreshVoiceSettings () {
  try {
    const v = await api.voiceInfo()
    setText('voice-dir', v.dir)
    setText('voice-info', v.count
      ? `${v.count} recordings, ${human(v.bytes)}` +
        (v.hasPassage ? ', including the reading passage.' : '.')
      : 'Nothing recorded yet.')
    const b = $('voice-backup')
    if (b) b.disabled = !v.count
  } catch { /* Settings is still usable without this */ }
}

function voiceStatus (msg, bad) {
  const el = $('voice-status')
  if (!el) return
  el.hidden = false
  el.textContent = msg
  el.style.color = bad ? 'var(--bad)' : ''
}

function initVoiceSettings () {
  const on = (id, fn) => { const e = $(id); if (e) e.addEventListener('click', fn) }
  on('voice-open', async () => {
    const v = await api.voiceInfo().catch(() => null)
    if (v && v.dir) api.openPath(v.dir)
  })
  on('voice-backup', async () => {
    voiceStatus('Saving…')
    const r = await api.voiceExport()
    if (r.canceled) { voiceStatus(''); $('voice-status').hidden = true; return }
    voiceStatus(r.ok
      ? `Saved ${r.count} recordings to ${r.path}`
      : 'Could not save the backup: ' + (r.error || ''), !r.ok)
  })
  on('voice-restore', async () => {
    voiceStatus('Restoring…')
    const r = await api.voiceRestore()
    if (r.canceled) { voiceStatus(''); $('voice-status').hidden = true; return }
    voiceStatus(r.ok ? `Restored ${r.restored} recordings.`
                     : 'Could not restore: ' + (r.error || ''), !r.ok)
    refreshVoiceSettings()
    refreshVoiceState()
  })
  refreshVoiceSettings()
}
