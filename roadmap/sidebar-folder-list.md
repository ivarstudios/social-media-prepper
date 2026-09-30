# Sidebar folder list broken by the Settings folders list

Found on 30 Sep 2026.

## What happens

- After a scan, the sidebar's folder list turns into a tall block: the selected folder's highlight fills most of the
  sidebar's height but only part of its width.
- Opening **Settings** writes the tools, models and data folders into the sidebar, replacing the folder list, and the
  dialog's own **Folders** list stays empty.

## Why

The install-locations change added `<dl class="folders" id="folderList">` to the Settings dialog in `smp/static/index.html`. The sidebar
already has `<ul id="folderList" class="folders">`.

- The new rule `.folders { display: grid; grid-template-columns: max-content 1fr; ... }` in `app.css` also matches the
  sidebar list, which becomes a two-column grid that stretches its rows.
- `$("#folderList")` in the Settings button's handler in `app.js` finds the sidebar list, because it comes first in
  the page.

## Fix (done)

The dialog's list gets names of its own: `<dl class="locations" id="locationList">`, `.locations` in `app.css` and
`$("#locationList")` in the Settings handler. The sidebar keeps `#folderList` and `.folders`.

Checked in Chrome on 30 Sep 2026: after a scan the sidebar list is a normal list (the selected folder's highlight spans
the full width, one row high), and opening Settings lists tools, models and data under Folders without changing the
sidebar.

## Also seen in the same session

With the local model `qwen3-vl:30b-a3b-instruct-q4_K_M`, on 10 photos:

- **Keyword loop.** Once, the model repeated `"ice"` in the keyword list for thousands of lines until the answer was
  cut off, so that image failed with "unreadable answer". Ollama's `repeat_penalty` or a cap on the answer length
  (`num_predict`) would stop it.
- **Needless warnings.** Two harmless photos got a content warning ("This image contains no people or animals.",
  "natural landscapes ... suitable for general audiences"). Gone: SMP no longer asks for content warnings or the
  minors flag, and removes the Flags that earlier versions wrote.
