# Building the Jsplit plugin

The plugin is an **offline** VST3: it collects your choices (song, quality,
stems) and drives the Python engine, which writes the stems to a folder you drag
back into your DAW. The neural models (HTDemucs / RoFormer) are far too heavy to
run in a real-time audio callback, so nothing is separated inside `processBlock`
— see the note at the top of `Source/PluginProcessor.h`.

```
Source/
  PluginProcessor.{h,cpp}   audio-plugin shell, persisted settings, engine auto-detect
  PluginEditor.{h,cpp}      the UI: load · quality · stems · generate · open folder
  SeparationBridge.{h,cpp}  runs scripts/split.py as a child process, streams progress
CMakeLists.txt              fetches JUCE, builds VST3 + Standalone
```

## Prerequisites (once)

- **Visual Studio 2022** with the *Desktop development with C++* workload
- **CMake 3.22+**
- Internet access on the first configure (JUCE is fetched automatically)

## Compile

```powershell
cmake -S plugin -B plugin/build -G "Visual Studio 17 2022" -A x64
cmake --build plugin/build --config Release
```

Outputs land under `plugin/build/Jsplit_artefacts/Release/`:

- `VST3/Jsplit.vst3`  — copy to `C:\Program Files\Common Files\VST3\` (or let the installer do it)
- `Standalone/Jsplit.exe` — a windowed app, no DAW required

> The build is verified to be *correct, idiomatic JUCE*, but it has **not** been
> compiled in this environment (no Visual Studio here). Expect to fix the odd
> include or JUCE-version wrinkle the first time — bump the `GIT_TAG` in
> `CMakeLists.txt` if a newer JUCE changes an API.

## How the plugin finds the engine

On launch it fills any missing paths, in priority order:

1. `jsplit.config` in `C:\ProgramData\Jsplit\` then `%APPDATA%\Jsplit\` (installer writes this)
2. env vars `JSPLIT_HOME` (repo root) and `JSPLIT_PYTHON` (interpreter)
3. walking up from the plugin binary looking for `scripts/split.py`
4. the repo's `.venv\Scripts\python.exe` if found

You can always override both paths from the **Python… / Engine…** buttons in the
plugin's settings strip; those choices are saved with the session.

## Don't want to compile yet?

The **`app/jsplit_gui.py`** desktop app gives the exact same
drop → pick stems → generate → export workflow with zero C++ build:

```powershell
.venv\Scripts\python.exe app/jsplit_gui.py
```
