# Jsplit installer

This folder turns a compiled plugin + the Python engine into **one shareable
`JsplitSetup.exe`**. The person you share it with just runs it — it drops the
plugin and engine into the right places and configures itself.

## What the end user gets

Running `JsplitSetup.exe` (admin prompt, once):

| Thing | Goes to | Why |
|-------|---------|-----|
| `Jsplit.vst3` | `C:\Program Files\Common Files\VST3\` | every DAW scans this automatically |
| engine code   | `C:\ProgramData\Jsplit\engine\` | machine-wide, all users |
| portable Python | `C:\ProgramData\Jsplit\python\` | no system Python needed |
| `jsplit.config` | `C:\ProgramData\Jsplit\` | tells the plugin where python + engine are |

Then the installer sets up the Python dependencies (a few minutes). After that,
the plugin shows up in the DAW's VST3 list and Just Works — no paths to set.

> **Model weights** (HTDemucs / RoFormer, a few hundred MB) still download the
> **first time** a user actually separates a song. That step needs internet once;
> after that it's fully local. Everything else is bundled.

## Building the installer (maintainer)

Prereqs, installed once on the build machine:

- Visual Studio 2022 (Desktop C++) · CMake 3.22+ · [Inno Setup 6](https://jrsoftware.org/isdl.php)

Then from the repo root:

```powershell
# fully self-contained installer (bundles wheels; large, but needs no internet on install):
powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1

# smaller installer that pip-installs deps from the internet at install time:
powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1 -Offline:$false
```

The script:

1. builds `Jsplit.vst3` with CMake,
2. downloads a relocatable CPython (`python-build-standalone`),
3. stages the VST3 + engine + python (+ wheels if offline) into `installer\staging\`,
4. compiles `jsplit.iss` → **`dist\JsplitSetup.exe`**.

Share that one file.

## Notes & honest caveats

- **Size.** The offline installer is large (torch + demucs wheels are ~0.5–1 GB).
  Use `-Offline:$false` for a small installer if your users have internet.
- **`PyTag` / `PyVersion`** in `build_installer.ps1` point at a specific
  python-build-standalone release; bump them if that URL 404s.
- **Not code-signed.** Windows SmartScreen will warn ("unknown publisher") until
  you sign `JsplitSetup.exe` with a code-signing certificate.
- **Licensing.** The RoFormer "Kim" vocal checkpoint used by the `max` tier may
  be **non-commercial** — verify before distributing a paid product.
- This kit is **Windows-first**. macOS would need an AU/VST3 build + a `.pkg`
  (pkgbuild/productbuild) and notarization; not included yet.
- The installer script is written correctly but **could not be compiled or run
  in the dev environment** — expect minor first-run fixes.
