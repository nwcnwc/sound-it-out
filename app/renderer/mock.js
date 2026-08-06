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
      { id: '1', name: 'Level 1 — Favourite names', description: 'Whole words he already loves, learned by sight. Chase, Marshall, Skye.', available: true },
      { id: '2', name: 'Level 2 — Everyday words', description: 'Family, home and first little phrases. Around fifty words.', available: true },
      { id: '3', name: 'Level 3 — Single sounds', description: 'One letter at a time: s, a, t, p, i, n.', available: true },
      { id: '4', name: 'Level 4 — Two sounds together', description: 'Joining two sounds: sa, at, ip, um.', available: true },
      { id: '5', name: 'Level 5 — Three sounds', description: 'Short words he can sound out: sat, pin, tap.', available: true },
      { id: '6', name: 'Level 6 — sh, ch, th, ck', description: 'Two letters making one sound: ship, chat, duck.', available: false, reason: 'Needs the extra voice download — see Settings' },
      { id: '7', name: 'Level 7 — Trickier clusters', description: 'st, bl, nd, mp: stop, black, hand.', available: false, reason: 'Needs the extra voice download — see Settings' },
      { id: '8', name: 'Level 8 — Whole sentences', description: 'Longer words, then sentences read together.', available: false, reason: 'Needs the extra voice download — see Settings' }
    ],
    themes: [
      { id: 'night', name: 'Night' },
      { id: 'paper', name: 'Book page' },
      { id: 'contrast', name: 'High contrast' }
    ],
    capabilities: { kokoro: true, recordings: true, cloning: false },
    wordlistText: WORDLIST,
    outputDir: '/Users/mum/Movies/Sound It Out',
    settings: { level: '1', theme: 'night', reps: 3, pauseSeconds: 1.5, minutes: 20 }
  }

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
