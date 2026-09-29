# IVAR SMP icon

![IVAR SMP icon](png/smp-icon-256.png)

## What it shows

- **A photo**: a sun and an angular mountain, echoing the mountain in the IVAR Studios logo.
- **Two caption lines under it**, a full line and a shorter one: the text SMP writes for a photo.
- **The IVAR hexagon** around it, with the same proportions, frame weight and ink as IVAR Studios' other tools.

Black and white on purpose, like the others: it works as a favicon and on light and dark taskbars.

## Files

| File | Use |
|---|---|
| `smp-icon.svg` | The master drawing. Edit this one; everything else is built from it. |
| `png/smp-icon-<size>.png` | Square, transparent around the hexagon: 16 to 1024 px. |
| `smp-icon.ico` | Windows icon (16 to 256 px), used by the installer's desktop and Start menu shortcuts. |

`build_icon.py` renders the SVG with Microsoft Edge (headless) and writes all of these, plus the copies the app
serves from `smp/static/` (SVG, ICO, 32 and 256 px PNGs):

```
.venv\Scripts\python docs\icon\build_icon.py
```

## Drawing

In the SVG's units, `viewBox="0 0 173.2 200"`:

| Part | Specification |
|---|---|
| Hexagon | The same as in IVAR Studios' other tool icons: regular, pointed top and bottom, circumradius 100, frame 14.1 thick. |
| Colours | Ink `#333333`, white `#ffffff` inside the hexagon and for cut-outs. Nothing else. |
| Photo | 84 × 56 (3:2), corner radius 3, frame 6 thick, with a sun and an angular mountain. |
| Caption lines | 7 thick with round ends; the first as wide as the photo, the second 54 wide, left-aligned; 10 below the photo and 7 apart. |
| Position | Photo and caption lines centred together, as one block, in the middle of the hexagon. |

Keep the hexagon exactly as it is and the icon in two colours; only the drawing inside changes between IVAR tools.
