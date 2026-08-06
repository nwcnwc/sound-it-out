"""Fetch human-recorded IPA phoneme clips from Wikimedia Commons.

These are CC BY-SA recordings by phoneticians. Attribution is recorded in
assets/commons/manifest.json and MUST be shipped with any build that uses them.
Commons throttles aggressively, so this is slow and resumable - rerun it until
it reports all clips present.
"""

import json
import pathlib
import subprocess
import time
import urllib.parse
import urllib.request

# IPA symbol -> Commons file title (standard articulatory naming)
FILES = {
    "s": "Voiceless_alveolar_sibilant.ogg",
    "f": "Voiceless_labiodental_fricative.ogg",
    "ʃ": "Voiceless_palato-alveolar_sibilant.ogg",
    "m": "Bilabial_nasal.ogg",
    "n": "Alveolar_nasal.ogg",
    "l": "Alveolar_lateral_approximant.ogg",
    "r": "Alveolar_approximant.ogg",
    "p": "Voiceless_bilabial_plosive.ogg",
    "t": "Voiceless_alveolar_plosive.ogg",
    "k": "Voiceless_velar_plosive.ogg",
    "b": "Voiced_bilabial_plosive.ogg",
    "d": "Voiced_alveolar_plosive.ogg",
    "g": "Voiced_velar_plosive.ogg",
    "v": "Voiced_labiodental_fricative.ogg",
    "z": "Voiced_alveolar_sibilant.ogg",
    "æ": "Near-open_front_unrounded_vowel.ogg",
    "ɪ": "Near-close_near-front_unrounded_vowel.ogg",
    "ɛ": "Open-mid_front_unrounded_vowel.ogg",
}

UA = {"User-Agent": "SoundItOut/0.1 (educational use; github.com/nwcnwc)"}
OUT = pathlib.Path(__file__).resolve().parent.parent / "assets" / "commons"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mf = OUT / "manifest.json"
    manifest = json.loads(mf.read_text()) if mf.exists() else {}
    norm = {v.replace("_", " "): k for k, v in FILES.items()}

    url = (
        "https://commons.wikimedia.org/w/api.php?action=query&format=json"
        "&prop=imageinfo&iiprop=url|user|extmetadata&titles="
        + urllib.parse.quote("|".join("File:" + v for v in FILES.values()))
    )
    pages = json.load(
        urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)
    )["query"]["pages"]

    for p in pages.values():
        if "imageinfo" not in p:
            continue
        ii = p["imageinfo"][0]
        title = p["title"].replace("File:", "")
        ipa = norm[title]
        if (OUT / f"{ipa}.wav").exists():
            continue
        data = None
        for attempt in range(5):
            try:
                data = urllib.request.urlopen(
                    urllib.request.Request(ii["url"], headers=UA), timeout=90
                ).read()
                break
            except Exception as e:
                print(f"  retry /{ipa}/ ({e.__class__.__name__})", flush=True)
                time.sleep(10 * (attempt + 1))
        if not data:
            print(f"  FAILED /{ipa}/", flush=True)
            continue
        (OUT / title).write_bytes(data)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(OUT / title),
             "-ar", "24000", "-ac", "1", str(OUT / f"{ipa}.wav")],
            check=True,
        )
        manifest[ipa] = {
            "file": title,
            "url": ii["url"],
            "author": ii.get("user", "?"),
            "license": ii.get("extmetadata", {})
            .get("LicenseShortName", {})
            .get("value", "?"),
        }
        mf.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
        print(f"  /{ipa}/ {manifest[ipa]['license']} by {manifest[ipa]['author']}", flush=True)
        time.sleep(6)

    have = sorted(x.stem for x in OUT.glob("*.wav"))
    missing = [k for k in FILES if k not in have]
    print(f"\nhave {len(have)}/{len(FILES)}")
    if missing:
        print("missing:", " ".join(missing), "- rerun to resume")


if __name__ == "__main__":
    main()
