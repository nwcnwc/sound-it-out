# Shipping updates

## The short version

The user's work is never at risk. Everything they create lives outside the app:

| What | Where (macOS) |
|---|---|
| Word lists | `~/Library/Application Support/Sound It Out/wordlists/` |
| The recordings | `~/Library/Application Support/Sound It Out/assets/voice/` |
| Settings | `~/Library/Application Support/Sound It Out/settings.json` |
| Finished videos | `~/Sound It Out/` |

The application bundle contains only code and models. Replacing it cannot touch
any of the above. That is what `gen/paths.py` exists for — it splits read-only
`RESOURCES` from writable per-user `DATA` — and it is the reason upgrading is
safe rather than merely usually-safe.

## How the app updates itself

On launch, four seconds in, the app quietly asks GitHub for the latest release.
If there is a newer one it tells the UI; it never blocks startup, never
interrupts a job, and if the machine is offline it says nothing at all.

When the user accepts, the installer is downloaded with a progress bar and the byte
count is verified — a truncated installer that still launches is a far worse
outcome than a failed download.

Then it differs by platform, and it is worth understanding why.

| Platform | What happens |
|---|---|
| Windows | The NSIS installer runs and replaces the app. Fully automatic. |
| Linux | The AppImage is downloaded and revealed. |
| **macOS** | The `.dmg` is downloaded and revealed. **They drag it into Applications.** |

## Why macOS is not fully automatic

This is a real limitation, not an oversight.

Electron's usual updater (`electron-updater`) goes through Squirrel.Mac on
macOS, and Squirrel **refuses to install an update onto an app without a valid
Apple code signature**. This project is deliberately unsigned, to avoid $99/yr
for a family tool.

So on macOS, `electron-updater` would download the whole update and then fail
at the final step — the worst possible place to fail. Rather than pretend, the
app downloads the `.dmg`, opens the folder, and tells them plainly: drag it
across, replacing the old one, and everything you have made is kept.

That is one drag, a few times a year.

**If you later want it fully automatic on macOS**, the requirement is an Apple
Developer account ($99/yr) plus notarisation in CI. At that point switching to
`electron-updater` becomes worthwhile. Not before.

## Releases must be public

`app/updater.js` reads from **`nwcnwc/sound-it-out-releases`**, not the source
repo.

The source repo is private, and a private repo's release assets require
authentication to download. Shipping a GitHub token inside the app would be
insecure and, since anyone with the app has the token, pointless.

So: keep the source private, publish the built installers to a small public
repo. Create it once:

```bash
gh repo create nwcnwc/sound-it-out-releases --public \
  --description "Installers for Sound It Out"
```

Override for testing with `SIO_RELEASES_REPO=owner/repo`.

## Cutting a release

1. Bump `version` in `package.json`. The app compares this against the release
   tag, so it must go up or the update will not be offered.
2. Tag and push — the CI workflow builds on `v*` tags:
   ```bash
   git tag v0.2.0 && git push origin v0.2.0
   ```
3. Download the four installers from the workflow run's artifacts.
4. Publish them to the public releases repo:
   ```bash
   gh release create v0.2.0 --repo nwcnwc/sound-it-out-releases \
     --title "v0.2.0" --notes "What changed" ./dist/installers/*
   ```

The release notes are shown to the user verbatim, so write them for the reader — "the sounds
are clearer now", not "fix schwa detection threshold".

Asset names must keep their platform extensions (`.dmg`, `.exe`, `.AppImage`),
since that is how the app picks the right one. Both macOS builds are published;
`arm64` and `x64`/`intel` in the filename select between them.

## What is deliberately not done

- **No silent background updates.** The user is told, and chooses. A reading routine
  that changes under a child without warning is worse than one that is a version
  behind.
- **No forced updates.** The app works indefinitely without ever updating.
- **No telemetry.** The only network request the app ever makes is this version
  check, and it sends nothing but a User-Agent.
