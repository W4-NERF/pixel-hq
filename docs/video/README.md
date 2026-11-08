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

### Highlight GIF for the README

```bash
# four beats (office · live · answer & unblock · triage) → 22 s, 800 px, 10 fps, 96 colours ≈ 7 MB
ffmpeg -ss 0.5 -to 6.0 -i pixel-hq-demo.mp4 -an seg0.mp4   # repeat for 13.8–18.2, 25.8–33.8, 42.0–46.3
printf "file 'seg%d.mp4'\n" 0 1 2 3 > list.txt && ffmpeg -f concat -safe 0 -i list.txt -c copy cut.mp4
ffmpeg -i cut.mp4 -vf "setpts=PTS/1.15,fps=10,scale=800:-1:flags=lanczos,palettegen=max_colors=96:stats_mode=diff" pal.png
ffmpeg -i cut.mp4 -i pal.png -lavfi "setpts=PTS/1.15,fps=10,scale=800:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" -loop 0 ../demo.gif
```
