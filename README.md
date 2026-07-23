# Guhan Billing — Windows + Android conversion

## What's in this folder

| File | Purpose |
|---|---|
| `billing_core.py` | All the business logic from your original app (GST math, invoice numbering, PDF generation, Excel generation, JSON persistence) — extracted so it has zero dependency on Tkinter. Tested and confirmed to produce identical PDF/Excel output to the original. |
| `cloud_sync.py` | A small Firebase-based client that keeps invoice/proforma/quotation numbers in sync across devices when online, and falls back to local numbering when offline. Full setup steps are in the file's docstring. |
| `main.py` | The new Kivy UI — runs unchanged on both Windows and Android. Covers the full flow: pick document type → fill company/buyer → add items → generate PDF/Excel with synced numbering. |
| `buildozer.spec` | Android build configuration, with build instructions in the comments. |

## Why this architecture

Your original app is Tkinter, which **cannot run on Android at all** — it's not a
conversion, the UI layer has to be rebuilt in a toolkit Android supports. Kivy was the
option you picked because it's the closest match to what you already have: same language,
same business logic reused untouched, and it packages to *both* a Windows `.exe`
(PyInstaller) and an Android `.apk` (Buildozer) from one codebase.

## Staged roadmap

**Stage 1 — Core extraction (done, this delivery)**
`billing_core.py` pulled out of your Tkinter file with no logic changes, verified against
the original by generating a sample invoice and diffing behaviour. This is the foundation
everything else builds on.

**Stage 2 — Working Kivy app (done, this delivery, as a starter)**
`main.py` gives you one working screen covering the core flow end to end. Test it now:
```
pip install kivy
python main.py
```
Left as next steps for you (or me, next time) to extend:
- A dropdown to reuse a previously saved company/buyer profile (the data's already being
  saved via `bc.upsert_profile`, just needs a picker widget wired to it).
- Logo upload and the PDF watermark.
- Reopening/editing a previously generated invoice from `invoices.json`.

**Stage 3 — Online sync (done, this delivery, needs your Firebase project)**
Follow the setup steps at the top of `cloud_sync.py` (~5 minutes, free, no credit card),
then paste your database URL into `FIREBASE_DB_URL` near the top of `main.py`. Read the
"HOW THE SYNC WORKS" section in that file too — it's an honest best-effort sync (last
value wins), not a bank-grade distributed lock, which is the right trade-off for a small
business syncing a laptop and a phone.

**Stage 4 — Windows packaging**
Once you're happy with the desktop-tested app:
```
pip install pyinstaller
pyinstaller --onefile --windowed --name "GuhanBilling" main.py
```
The `.exe` lands in `dist/`. (Same folder-next-to-the-exe data storage as your original
app — no storage picker needed on Windows, that's an Android-only prompt.)

**Stage 5 — Android packaging**
Buildozer only runs on Linux/macOS — on Windows you'll need WSL2 or a Linux VM. Full
step-by-step is in the comments at the bottom of `buildozer.spec`. Budget real time for
this stage: the first build downloads the Android SDK/NDK (30–60+ minutes) and it's common
to hit one or two dependency snags on the first attempt with a new Python package.

## Two honest caveats worth knowing now

1. **I can't compile or test the APK for you.** My working environment has no Android
   SDK/NDK/JDK and no network access to Google's Maven repositories, so I can't run
   `buildozer android debug` here. Everything above is built and syntax/logic-verified on
   my end; the actual on-device Android build and testing has to happen on your machine.

2. **Android's "external storage" got more locked-down starting Android 11** (scoped
   storage). The app in `main.py` requests the classic storage permissions, which reliably
   covers Android up to 10 and the app's own external folder on newer versions. If your
   target phones are Android 11+ and you want the files visible directly in the shared
   Downloads folder (not just an app-specific external folder), that needs Android's
   Storage Access Framework (a native "choose a folder" dialog) instead — that's a
   reasonable Stage 6 addition once you've confirmed which Android versions you're
   actually targeting.

## Suggested next step

Run `python main.py` on your desktop first (fastest feedback loop), confirm the PDF/Excel
output still looks right for a few test invoices, set up the free Firebase project, then
move to packaging. Happy to pick up any of Stage 2's leftover items (profile picker, logo
upload, invoice editing) or help debug the Buildozer build in a follow-up.
