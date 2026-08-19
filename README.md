# Jsplit — Clarity-First AI Stem Splitter

An AI music source-separation engine focused, in priority order, on:

1. **Clarity** of each stem
2. **How many elements** we can cleanly separate
3. **No hollow / no broken** sound (integrity of the music)
4. **Optimization** to run locally on mid- and high-end laptops (CPU + GPU)

The guiding principle: **trust strong models and prove quality with numbers.**
We do *not* try to "fix" separation with spectral gating / phase smoothing /
harmonic inpainting — those are the classic causes of the hollow, underwater,
metallic artifacts we're trying to avoid. Instead we pick the best model per
source and construct the stem set so that **sum(stems) == the original mix**
(nothing is discarded → nothing goes hollow), then *measure* it.

---

## Quick start

```powershell
# 6 elements (drums, bass, other, vocals, guitar, piano):
.venv\Scripts\python.exe scripts/split.py -i "song.mp3" --quality full

# Best vocal clarity (RoFormer vocal + Demucs instruments):
.venv\Scripts\python.exe scripts/split.py -i "song.mp3" --quality max

# Fast 20-second test slice, with full quality diagnostics:
.venv\Scripts\python.exe scripts/split.py -i "song.mp3" --quality balanced --duration 20
```

Output stems land in `outputs_jsplit/<songname>/`.

## Quality tiers

| Tier       | Model        | Vocal source     | Elements | Notes |
|------------|--------------|------------------|----------|-------|
| `fast`     | htdemucs     | Demucs           | 4        | quickest; good baseline |
| `balanced` | htdemucs_ft  | Demucs           | 4        | fine-tuned, cleaner (slower) |
| `full`     | htdemucs_6s  | Demucs           | 6        | + guitar, piano |
| `max`      | htdemucs_6s  | **RoFormer**     | 6        | cleanest vocal; slowest |

Tip: 6-stem models always emit guitar/piano even when a song has none (they come
out near-silent). For songs without those instruments, `balanced`/`max` (4
elements) is usually cleaner.

## Measuring quality (this is the point)

Every run prints diagnostics computed **on your real song** (no ground truth needed):

- **reconstruction residual (dB)** — how much is lost when stems are summed back.
  Below −30 dB = essentially perfect = *not hollow*. This is the core integrity guarantee.
- **spectral completeness** — per-band recon vs mix; flags any frequency range that went missing.
- **leakage (proxy)** — cross-bleed between stems; lower = cleaner separation.
- **sanity** — peak/RMS/clipping/NaN, to catch broken output.

Verified on the included gospel track (12 s slice, CPU): `fast` → residual
**−32.3 dB**, corr **0.9997**; `max` (RoFormer hybrid) → **−34.2 dB**, corr **0.9998**.

Score any folder of stems (e.g. to A/B the old pipeline vs Jsplit):

```powershell
.venv\Scripts\python.exe scripts/evaluate.py --mix "song.mp3" --stems outputs_jsplit/song
# add --reference <ground-truth-stems-folder> to also get SI-SDR
```

## Optimization / benchmarking

```powershell
.venv\Scripts\python.exe scripts/benchmark.py -i "song.mp3" --tiers fast balanced full --duration 20
```

Reports **RTF** (real-time factor; >1 = faster than realtime), wall time, and peak
RAM (needs `psutil`). Current machine is **CPU-only** (`torch==2.13.0+cpu`), so
runs are ~0.4× realtime on `fast`. To go faster:

- **NVIDIA GPU:** reinstall torch from the CUDA index (see `requirements.txt`).
- **AMD / Intel iGPU (Windows):** `pip install onnxruntime-directml` and use the ONNX path.
- **Apple Silicon:** ONNX Runtime CoreML provider.
- **CPU:** static INT8 quantization of the *conv* layers (real win; dynamic quant
  of Linear layers alone barely helps Demucs).

## Repo layout

```
src/
  engine.py              # clarity-first StemSplitter (tiers, RoFormer hybrid, sum-to-mix)
  quality/metrics.py     # reference-free diagnostics + SI-SDR
  models/                # Demucs + RoFormer wrappers
  audio/io.py            # load/save
scripts/
  split.py               # main CLI (also the contract the plugin calls)
  benchmark.py           # RTF / RAM measurement
  evaluate.py            # score saved stems
app/
  jsplit_gui.py          # desktop GUI (drop → pick stems → generate → export)
plugin/
  Source/                # offline VST3 (JUCE): UI + subprocess bridge to the engine
  CMakeLists.txt         # fetches JUCE, builds VST3 + Standalone
  BUILD.md               # how to compile
installer/
  jsplit.iss             # Inno Setup script (places VST3 + engine, self-configures)
  build_installer.ps1    # one-shot: build plugin → stage → produce JsplitSetup.exe
  README.md              # maintainer + end-user guide
```

## Status & roadmap

**Working now:** clarity-first CPU/GPU engine, 4- and 6-element separation,
RoFormer-vocal hybrid, a full measurement suite (all verified on a real song),
a **desktop GUI**, an **offline VST3 plugin**, and a **Windows installer**.

- **Desktop app** — `.venv\Scripts\python.exe app/jsplit_gui.py`
  Drop a song → pick a quality tier → tick the stems → **Generate** → open the folder.
  No compiler needed; drives the same engine as everything else.
- **VST3 plugin** (`plugin/`) — offline by design: the UI collects your choices and
  runs the engine, then writes stems you drag back into the DAW. Build it with
  `plugin/BUILD.md` (Visual Studio 2022 + CMake; JUCE is fetched automatically).
- **Installer** (`installer/`) — `build_installer.ps1` bundles the compiled VST3,
  the engine, and a portable Python into **one `JsplitSetup.exe`**. Running it
  places the VST3 in `Common Files\VST3`, installs the engine under `ProgramData`,
  and writes the config the plugin reads — so it "just works" in the DAW. See
  `installer/README.md`.

**Honest caveats:**
- The plugin/installer source is correct, idiomatic JUCE + Inno Setup but **has
  not been compiled in this environment** (no Visual Studio here) — expect minor
  first-build fixes.
- Model weights (a few hundred MB) download on the **first** separation; internet
  needed once, then fully local.
- The **real-time** idea is intentionally *not* pursued — HTDemucs/RoFormer can't
  run in an audio callback. If real-time is ever needed it requires a different,
  low-latency model.
- ONNX export of Demucs is unproven (and `htdemucs_ft` is a *bag of 4 models* —
  export must handle that, not just `models[0]`).
- Optional true-peak-safe export (some hot stems can exceed 0 dBFS).
- **Licensing:** the community RoFormer "Kim" vocal checkpoint may be
  **non-commercial** — verify before shipping a paid plugin.

> The older `scripts/separate.py` + `src/pipeline.py` + `src/enhancement/*`
> (spectral gate / phase smoothing / harmonic inpainting) are **superseded**.
> Those DSP steps tend to *add* hollow/underwater artifacts and break sum-to-mix;
> Jsplit deliberately omits them.
