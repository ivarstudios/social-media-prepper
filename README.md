<p align="center"><img src="docs/icon/png/smp-icon-256.png" width="128" alt="IVAR SMP icon"></p>

# IVAR SMP (Social Media Prepper)

*Made by [IVAR Studios](https://ivar.studio). Beta: download it, try it, and
[open an issue](https://github.com/ivarstudios/social-media-prepper/issues) when something breaks.*

Point it at a folder of finished images (exports, phone pictures, screenshots), add a `brief.md` that says what
the set is about, and a vision model writes title, caption, alt text, keywords and more **into the image files**.
You see every change before anything is written, and every write can be undone.

It only tags. It never rates, culls or recognises faces, and it only touches JPG, PNG, TIFF, HEIC and WebP
files: finished derivatives that can be exported again. RAW files, PSDs and videos are skipped.

## Install

**Windows 10/11:** download this repository (green *Code* button → *Download ZIP*, or `git clone`), unzip it
somewhere permanent, and double-click **`start.bat`**. The first start runs the installer, no admin rights needed
(except once, for the firewall rule that lets other computers open SMP: see *From another computer*).
It asks where three things go. Press Enter to keep the suggested folder, and everything stays inside the app folder:

| Folder | What | Suggested |
|---|---|---|
| Programs | Python (through `uv`), ExifTool and Ollama, each a pinned version (ExifTool and Ollama are checked against their known checksums); about 2 GB | `tools\` in the app folder |
| Models | the vision model, 6 to 36 GB | `data\ollama-models\` in the app folder |
| Data | settings, answer cache, thumbnails, place names, undo record | `data\` in the app folder |

Then it installs everything and adds a desktop and Start menu shortcut, **IVAR SMP**. To move a folder later, run
`install.bat` again and type the new one: it moves what's there. Without questions:
`install.bat -Yes -ModelsDir E:\IVAR-SMP\models` (also `-ToolsDir` and `-DataDir`). Versions before 0.1.2 kept the
data in `%LOCALAPPDATA%\IVAR-SMP`; the next `install.bat` or `update.bat` moves it into the app folder.

**Uninstall:** double-click **`uninstall.bat`**. It lists what it will remove, with sizes, and asks first. It
removes the programs, models and data (wherever you put them), the Python environment and the shortcuts, then
deletes the app folder too; a git clone keeps its code. It only removes SMP's own files: a folder you chose that
also holds other files keeps them.

Without an NVIDIA GPU with 8 GB or more, it asks whether to skip Ollama and use the Claude API instead.
`install.bat -ClaudeOnly` does that directly. `update.bat` pulls the latest version (for a git clone) and repairs
the install.

**macOS / Linux:** run `./start.sh` (on a Mac, double-click `start.command`). It installs Python through `uv`,
and ExifTool and Ollama through Homebrew on a Mac. On Linux, or on a Mac without Homebrew, it prints the one
command to run for anything it can't install itself. *The Mac and Linux installers haven't been tested on a real
machine yet.*

**First start:** the **Setup** panel opens and walks you through the last step:

- **Local model** (default): SMP picks the Qwen3-VL model that fits your GPU and downloads it, with progress,
  when you press *Download model*:

  | GPU memory | Model | Download |
  |---|---|---|
  | 40 GB+ | `qwen3-vl:32b-instruct-q8_0` | ~36 GB |
  | 22 GB+ | `qwen3-vl:30b-a3b-instruct-q4_K_M` | ~19 GB |
  | 14 GB+ | `qwen3-vl:8b-instruct-q8_0` | ~10 GB |
  | less | `qwen3-vl:8b-instruct-q4_K_M` | ~6 GB |

  Nothing leaves your computer. On Apple Silicon, about two thirds of the unified memory counts as GPU memory.
- **Claude API**: paste an API key from console.anthropic.com. Better-written text, but every image is uploaded
  to Anthropic and billed to that account.

## Use

1. **Scan** a folder (with or without subfolders). The left column lists every folder and whether it has a brief.
2. **Brief**: write a few sentences about the set and fill in credits. *Draft from photos* suggests a text
   from sample images. Saving writes `brief.md` into that folder.
3. **Generate** for one folder or all of them. *Review & write* opens and each image's title, caption,
   alt text and keywords appear as the model writes them, so you can proofread and write the first images while
   the rest are still being described.
4. **Review & write**: every image with its fields, as the file holds them and as they'd change. Untick
   suggestions you don't want, edit any text, and write one image with its own button (orange: unsaved changes,
   green: written) or everything with *Write all*. Written images stay here, so you can come back and fix a
   detail. *Undo* puts the old values back.

### From another computer

While SMP runs on one computer, any other computer on the same network can use it in a browser, with everything
the app does: scanning, briefs, generating and writing. The console window and *Setup* show the address, such as
`http://192.168.1.20:8765/`. Paths are the ones on the computer SMP runs on (*Choose folder* then browses its
folders in the page, mapped network drives included), and the vision model runs there too. Everyone shares one
session: the folder scanned and the job running are the same in every browser, so take turns.

**There's no login.** Anyone who can open the address can use the app as you do: browse this computer's folders,
see the images, write into them and run the vision model (the Claude API too, if a key is saved). Only the
computer SMP runs on can download models, save the Claude key or change the programs, models and network
settings under *Advanced*. This is on by default, so keep it on only on a network where you trust everyone (a
studio or home network) and turn it off anywhere else.

Open SMP by this computer's address or its name. SMP turns away any other name, and changes sent from any page
but its own, so a website you visit can't reach it through your browser.

On Windows this needs a firewall rule, which the installer adds (Windows asks for admin rights once; `-NoNetwork`
skips it). It lets other computers in on private and domain networks only, never on a public one: if SMP can't be
reached, check that Windows calls the network *Private*. On a Mac or Linux, SMP listens on the network too, and
whatever firewall the computer has decides who gets in. To keep SMP to this computer, set *Other computers on
the network* in Settings to *Can't* and start SMP again.

## brief.md

```markdown
---
set: Alps 2024
language: en          # en or sv: the language captions, alt text and keywords are written in
creator: Your Name
credit: Your Name / Studio Name
copyright: © Your Name
usage: Editorial use only
place: Zermatt
country: Switzerland
no_geotag: true       # remove GPS from the files (wolf dens, camera traps, undisclosed caves)
sensitive: true
---

A week of hiking in the Swiss Alps with friends, July 2024: mountain huts, glacier crossings and early
starts below the Matterhorn.
```

A brief applies to all subfolders. A `brief.md` in a subfolder adds to it, and its fields win. Everything is
optional; without any brief, the model describes only what it sees. Defaults for creator, credit and copyright
go in **Settings**.

## What it writes

Only what matters when preparing images for social media:

| Field | Why | Where in the file | Source |
|---|---|---|---|
| Caption | the starting point for post copy | XMP `dc:description` (+ EXIF/IPTC copies if present) | model: what's visible + brief context |
| Alt text | pasted into Instagram and LinkedIn | IPTC `AltTextAccessibility` | model: only what's visible |
| Title | a short name to find it by | XMP `dc:title` (+ IPTC Object Name if present) | model |
| Keywords | search, and the starting point for hashtags | XMP `dc:subject` (+ IPTC Keywords if present) | model; your own keywords are kept |
| Place, city, region, country | location tag and captions | IPTC location fields | brief, else GPS looked up offline (GeoNames) |
| Creator, credit, copyright, usage terms | credit lines; restricted sets | XMP/IPTC rights fields | brief (or Settings), never the model |
| People visible | *Only with people* in Review & write: check the images where a name could be wrong | `XMP-smp:PeopleCount` | model: how many people it clearly sees; you can correct it |

*Remove GPS* in a brief strips the position from the files (wolf dens, camera traps, undisclosed caves). Fields
that earlier versions wrote and SMP no longer uses (flags, focal point, crops, season and so on) show up in the preview as
*remove*, but only where SMP wrote them.

Rules the model follows: the caption starts with the story from the brief (the event, the place, why it matters)
and the alt text sticks to what is visible. It names people, their roles and relationships only as the brief gives
them, never guesses names, relationships, ethnicity, religion or health, takes place names and story only from the
brief and file facts, and writes no em dashes.

## Your text is safe

SMP records a fingerprint of every field it writes (`XMP-smp:Fingerprints`). Text that doesn't match is
yours: it's kept, and it's given to the model as facts to build on. Editing an SMP text (in the preview,
Lightroom or anywhere else) makes it yours. Tick *Replace text a person wrote* to overwrite anyway.
Existing credits are only changed with *Replace existing credits with the brief's*. Location fields already in
a file are never changed.

## Where things live

By default, all of it is in the app folder:

- **The app folder:** the app, `.venv\` (its Python environment) and, if you chose folders elsewhere,
  `locations.json`, which records them.
- **Programs** (`tools\`): uv, Python, ExifTool, Ollama, uv's package cache.
- **Models** (`data\ollama-models\`): the downloaded vision models.
- **Data** (`data\`): settings, the answer cache, thumbnails, place names and the undo record.

*Settings → Folders* in the app and `python -m smp doctor` show where each one is. Nothing else is written outside
these, apart from the shortcuts and the small key file Ollama keeps in `%USERPROFILE%\.ollama`. On a Mac or Linux,
ExifTool and Ollama come from Homebrew or the system and stay where those put them; there's no uninstaller yet, so
delete the app folder (and any folder you chose elsewhere).

Answers are cached per image, brief and model, so re-running costs nothing and editing a brief redoes only that
folder.

## Development

Run the installer once; it creates `.venv`. On a Mac or Linux, use `.venv/bin/python` instead.

```
.venv\Scripts\python -m pytest            # tests (ExifTool needed; no GPU or API key)
.venv\Scripts\python -m smp doctor        # what this computer has
.venv\Scripts\python docs\icon\build_icon.py   # rebuild the icon files after editing docs\icon\smp-icon.svg
```

Ideas that aren't built yet are in [`roadmap/`](roadmap/).

## Built on

- [ExifTool](https://exiftool.org) by Phil Harvey reads and writes the metadata.
- [Ollama](https://ollama.com) runs the local [Qwen3-VL](https://github.com/QwenLM/Qwen3-VL) models; the
  [Claude API](https://www.anthropic.com/api) is the other option.
- Place names come from [GeoNames](https://www.geonames.org), licensed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- [uv](https://github.com/astral-sh/uv) installs Python and the app's packages.
