/* Stand-in for the preload bridge.
 *
 * The real app exposes `window.soundout` from app/preload.js. This file only
 * does anything when that is missing - i.e. when index.html is opened straight
 * in a browser to look at the layout. It fakes plausible data and plausible
 * timings so the whole UI, including progress and errors, can be exercised
 * without Electron.
 *
 * Nothing in app.js knows or cares which one it is talking to.
 */
(function () {
  'use strict'
  if (window.soundout) return

  const WORDLIST = `# Sight words for Sound It Out
# =============================
#
# THIS FILE IS YOURS TO EDIT. Add, remove or change anything.
#
# One word per line. Lines starting with # are notes.
# [Square brackets] start a new group.


[Paw Patrol]
# Colours are each pup's kit, so the word looks like the character.
Chase        #4da6ff
Marshall     #ff5a4d
Skye         #ff8fc7
Rubble       #ffd23f
Rocky        #6fcf6f
Zuma         #ff9f45
pup
pups
truck
badge
rescue


[People]
# >>> REPLACE THESE WITH YOUR REAL NAMES. <<<
Alex
Mum
Dad
Nana
Grandad
# brother or sister names here
# pet names here


[Home]
home
bed
car
dog
cat
ball
book
cup
shoes
bath
teddy
park


[First words]
I
me
my
you
go
stop
yes
no
more
look
like
love
big
little
up
down
`

  const state = {
    levels: [
      { id: 1, name: 'Level 1 — Favourite names', description: 'Whole words he already loves, learned by sight. Chase, Marshall, Skye.', available: true },
      { id: 2, name: 'Level 2 — Everyday words', description: 'Family, home and first little phrases. Around fifty words.', available: true },
      { id: 3, name: 'Level 3 — Single sounds', description: 'One letter at a time: s, a, t, p, i, n.', available: true },
      { id: 4, name: 'Level 4 — Two sounds together', description: 'Joining two sounds: sa, at, ip, um.', available: true },
      { id: 5, name: 'Level 5 — Three sounds', description: 'Short words he can sound out: sat, pin, tap.', available: true },
      { id: 6, name: 'Level 6 — sh, ch, th, ck', description: 'Two letters making one sound: ship, chat, duck.', available: false, reason: 'Needs the extra voice download — see Settings' },
      { id: 7, name: 'Level 7 — Trickier clusters', description: 'st, bl, nd, mp: stop, black, hand.', available: false, reason: 'Needs the extra voice download — see Settings' },
      { id: 8, name: 'Level 8 — Whole sentences', description: 'Longer words, then sentences read together.', available: false, reason: 'Needs the extra voice download — see Settings' }
    ],
    themes: [
      { id: 'night', name: 'Night' },
      { id: 'paper', name: 'Book page' },
      { id: 'contrast', name: 'High contrast' }
    ],
    capabilities: { fallback_voice: true, recordings: true, cloning: false },
    wordlistText: WORDLIST,
    sightWordsText: 'Chase\nNana',
    outputDir: '/Users/mum/Movies/Sound It Out',
    settings: { level: '1', theme: 'night', reps: 3, pauseSeconds: 1.5, minutes: 20 }
  }

  const mockSentences = [
    {
      key: 'chase',
      text: 'Chase',
      kind: 'word',
      words: 1,
      missing: [],
      lineRecorded: true,
      ready: true
    },
    {
      key: 's',
      text: 's',
      kind: 'letter',
      words: 1,
      missing: [],
      lineRecorded: true,
      ready: true
    },
    {
      key: 'sam_sat_on_a_mat',
      text: 'Sam sat on a mat.',
      kind: 'sentence',
      words: 5,
      missing: [],
      lineRecorded: true,
      ready: true
    },
    {
      key: 'the_dog_can_nap',
      text: 'The dog can nap.',
      kind: 'sentence',
      words: 4,
      missing: ['nap'],
      lineRecorded: false,
      ready: false
    }
  ]

  const mockPacks = [
    { id: 'own-words', group: 'favourites', name: 'Your word list', description: 'Everything from your old word list.', count: 44, added: 1 },
    { id: 'paw-patrol', group: 'favourites', name: 'Paw Patrol', description: 'The pups and their lines.', count: 10, added: 0 },
    { id: 'veggie-tales', group: 'favourites', name: 'VeggieTales', description: 'Bob, Larry, and the song at the end of the show.', count: 5, added: 0 },
    { id: 'gods-world', group: 'favourites', name: "God's world", description: 'Short lines of faith and thanks.', count: 8, added: 0 },
    { id: 'letters', group: 'skills', name: 'Letter sounds', description: 'One letter at a time, in phonics order.', count: 19, added: 1 },
    { id: 'ladder', group: 'skills', name: 'Building up', description: 'The whole journey in order, ending in sentences.', count: 22, added: 22 }
  ]

  const listeners = { progress: [], done: [], error: [], install: [] }
  const fire = (k, payload) => listeners[k].forEach((fn) => { try { fn(payload) } catch (e) { console.error(e) } })
  const wait = (ms) => new Promise((r) => setTimeout(r, ms))

  let jobSeq = 0
  let cancelled = null

  const STAGES = [
    { stage: 'words', total: 1, message: 'Reading your word list' },
    { stage: 'audio', total: 24, message: 'Putting the sounds together' },
    { stage: 'frames', total: 40, message: 'Drawing the words' },
    { stage: 'video', total: 16, message: 'Making the video file' }
  ]

  async function runJob (jobId, opts) {
    await wait(400)
    for (const s of STAGES) {
      for (let done = 1; done <= s.total; done++) {
        if (cancelled === jobId) return
        fire('progress', { jobId, stage: s.stage, done, total: s.total, message: s.message })
        await wait(60)
      }
    }
    if (cancelled === jobId) return
    // window.__mockFail, or ?fail=1, exercises the error screen.
    if (window.__mockFail || new URLSearchParams(location.search).get('fail')) {
      fire('error', {
        jobId,
        message: "There wasn't enough room on the disk to save the video.",
        hint: 'Free up about 1 GB and try again, or choose a different folder in Settings.'
      })
      return
    }
    const out = opts.mode === 'export'
      ? state.outputDir + '/sound-it-out-level-' + opts.level + '-' + opts.minutes + 'min.mp4'
      : ''
    fire('done', { jobId, output: out })
  }

  function mockSightWords () {
    const out = []
    const seen = new Set()
    for (const raw of String(state.sightWordsText || '').split(/[\s,;]+/)) {
      const w = raw.replace(/^[.,!?;:'"“”‘’]+|[.,!?;:'"“”‘’]+$/g, '')
      if (!w || !/[a-z]/i.test(w) || seen.has(w.toLowerCase())) continue
      seen.add(w.toLowerCase())
      out.push(w)
    }
    return out
  }

  window.soundout = {
    async getState () { await wait(120); return JSON.parse(JSON.stringify(state)) },

    async saveWordlist (text) {
      await wait(180)
      if (!text.trim()) {
        return { ok: false, error: 'The list is empty. Add at least one word before saving.' }
      }
      state.wordlistText = text
      const groups = []
      let cur = null
      for (const raw of text.split(/\r?\n/)) {
        const line = raw.trim()
        if (!line || line.startsWith('#')) continue
        const g = line.match(/^\[(.+)\]$/)
        if (g) { cur = { name: g[1].trim(), words: [] }; groups.push(cur); continue }
        const m = line.match(/^(.*?)\s+(#[0-9a-fA-F]{6})$/)
        if (!cur) { cur = { name: 'Words', words: [] }; groups.push(cur) }
        cur.words.push({ word: m ? m[1].trim() : line, color: m ? m[2].toLowerCase() : null })
      }
      return { ok: true, groups }
    },

    async generate (opts) {
      const jobId = 'job-' + (++jobSeq)
      runJob(jobId, opts)
      return { jobId }
    },

    async cancelJob (jobId) { cancelled = jobId; return { ok: true } },

    // The sentence library, in memory. Enough behaviour to exercise the
    // whole tab: adding splits on sentence ends, statuses vary.
    async sentencesList () {
      await wait(100)
      return { sentences: JSON.parse(JSON.stringify(mockSentences)) }
    },
    async sentencesAdd (text) {
      await wait(150)
      const lines = String(text || '').trim().split(/(?<=[.!?])\s+/).filter(Boolean)
      if (!lines.length) return { ok: false, error: 'That did not contain a sentence to add.' }
      for (const t of lines) {
        const key = t.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
        if (!mockSentences.some((s) => s.key === key)) {
          const n = t.split(/\s+/).length
          mockSentences.push({
            key,
            text: t,
            kind: n > 1 ? 'sentence' : t.replace(/[^\w]/g, '').length > 1 ? 'word' : 'letter',
            words: n,
            missing: t.split(/\s+/).slice(0, 2).map((w) => w.replace(/[^\w]/g, '')),
            lineRecorded: false,
            ready: false
          })
        }
      }
      return { ok: true, sentences: JSON.parse(JSON.stringify(mockSentences)) }
    },
    async sentencesRemove (key) {
      await wait(100)
      const i = mockSentences.findIndex((s) => s.key === key)
      if (i >= 0) mockSentences.splice(i, 1)
      return { sentences: JSON.parse(JSON.stringify(mockSentences)) }
    },
    async sentencesClips (key) {
      await wait(80)
      const s = mockSentences.find((x) => x.key === key)
      const words = s ? s.text.replace(/[.!?]/g, '').split(/\s+/) : []
      const clips = words.map((w) => ({
        key: w.toLowerCase(),
        kind: 'word',
        display: w,
        path: (s.missing || []).includes(w.replace(/[^\w]/g, '')) ? null : '/mock/' + w + '.wav',
        seconds: 0.4,
        silent: false
      }))
      if (s && s.kind === 'sentence') {
        clips.push({ key: key, kind: 'sentence', display: s.text,
          path: s.lineRecorded ? '/mock/' + key + '.wav' : null, seconds: 2.1, silent: false })
      }
      return { clips }
    },
    async sentencesEstimate (opts) {
      await wait(60)
      const n = (opts && opts.sentences && opts.sentences.length) || 0
      return { seconds: n * 95 }
    },
    // The sight-word list: words read whole, never sounded out.
    async sightWordsLoad () {
      await wait(80)
      return { text: state.sightWordsText || '', words: mockSightWords() }
    },
    async sightWordsSave (text) {
      await wait(120)
      state.sightWordsText = String(text || '')
        .split(/\r?\n/).filter((l) => !l.trim().startsWith('#')).join('\n').trim()
      return { ok: true, text: state.sightWordsText, words: mockSightWords() }
    },

    async packsList () {
      await wait(80)
      return { packs: JSON.parse(JSON.stringify(mockPacks)) }
    },
    async packsAdd (id) {
      await wait(150)
      const p = mockPacks.find((x) => x.id === id)
      if (p) p.added = p.count
      return {
        sentences: JSON.parse(JSON.stringify(mockSentences)),
        packs: JSON.parse(JSON.stringify(mockPacks))
      }
    },

    async saveSettings (obj) {
      await wait(80)
      Object.assign(state.settings, obj)
      if (obj.outputDir) state.outputDir = obj.outputDir
      return { ok: true }
    },

    async installCloning () {
      const total = 40
      for (let done = 0; done <= total; done++) {
        await wait(90)
        fire('install', {
          done,
          total,
          message: done < total ? 'Downloading (' + (done * 75) + ' MB of 3 GB)' : 'Finishing off'
        })
      }
      state.capabilities.cloning = true
      state.levels.forEach((l) => { l.available = true; delete l.reason })
      return { ok: true }
    },

    openPath (p) { console.log('[mock] openPath', p); window.alert('This would open:\n\n' + p) },

    onProgress (cb) { listeners.progress.push(cb) },
    onDone (cb) { listeners.done.push(cb) },
    onError (cb) { listeners.error.push(cb) },
    onInstallProgress (cb) { listeners.install.push(cb) }
  }

  window.__soundoutMock = true
})()
