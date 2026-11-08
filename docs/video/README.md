# Demo video

The demo video is rendered from the **standalone demo page** (`pixelhq/render.py --demo`, synthetic data
only — never the real app) frame by frame in headless Chromium and piped into ffmpeg. A virtual clock
drives timers and CSS animations, so a re-render gives identical frames at any frame rate.

- `film.js` — the director: storyboard (beats), camera moves, cursor, typing, captions, ffmpeg pipe.
  `HOST_TEXT` at the top mirrors the wording the real plugin host returns.
- `stage.js` — injected into the page: a stand-in for the desktop host (answers actions/triage/reload),
  the virtual clock, overlay (captions, cursor, end card).

```bash
cd docs/video
npm install && npx playwright install chromium
npm run page                 # build dist/pixel-hq.html with demo data
npm run draft                # 30 fps, first 15 s — quick check
FFMPEG=/path/to/ffmpeg npm run render        # 1920×1080, 60 fps, silent AAC track, ~57 s
FFMPEG=/path/to/ffmpeg npm run render:4x5    # 1080×1350 feed cut
```

A 60 fps render takes about 5 minutes. The script refuses to run on a page without `"demo": true`.
The rendered files are not committed; the current cut is attached to the GitHub release.
