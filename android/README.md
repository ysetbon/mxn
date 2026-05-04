# MxN CAD Generator — Android

Kivy port of the desktop PyQt5 app under `../src`. Phase 1 of the port.

## What works in Phase 1

- Pick `M`, `N`, variant (LH / RH), Stretch on/off
- Generate the OpenStrandStudio JSON for that pattern
- Preview the JSON head in a scrollable read-only field

## What's not in Phase 1 yet

- Image rendering (the QPainter renderer in `src/mxn_emoji_renderer.py` will be ported to Pillow in Phase 2; identical algorithms, Pillow drawing primitives in place of QPainter)
- Color pickers, endpoint emoji controls
- JSON / PNG export to device storage
- Continuation, parallel alignment, Full Auto batch
- `openstrandstudio` canvas integration (sibling repo dependency)

## Layout

```
android/
├── buildozer.spec         # APK build config
├── main.py                # Kivy entry point
├── sync_generators.sh     # copies src/mxn_*.py -> mxn_app/core/generators/
├── mxn_app/
│   ├── app.py             # Kivy App class
│   ├── screens/home.py    # HomeScreen UI
│   └── core/
│       ├── generator.py   # variant-routing wrapper
│       └── generators/    # vendored copies of src/mxn_lh.py etc.
```

The four generator modules under `mxn_app/core/generators/` are byte-identical
copies of `src/mxn_lh.py`, `src/mxn_rh.py`, `src/mxn_lh_strech.py`, and
`src/mxn_rh_stretch.py`. They are pure Python (json/os/sys/random/colorsys
only), so they vendor cleanly. After editing any of those files in `src/`, run
`./sync_generators.sh` to refresh the copies here.

## Run on desktop (development)

```sh
cd android
pip install kivy pillow
python3 main.py
```

The same code is what gets bundled into the APK, so anything that works on
desktop should behave the same on Android (modulo screen size).

## Build the APK

You need Buildozer (Python tool) and its system dependencies (Java JDK,
Android SDK/NDK auto-downloaded by buildozer on first run).

```sh
pip install buildozer cython
cd android
buildozer android debug
```

The output `.apk` lands in `android/bin/`. Install on a connected device with:

```sh
buildozer android debug deploy run
```

First build downloads ~2 GB of Android SDK/NDK and takes 20–40 minutes.
Subsequent builds are ~1–3 minutes.

### Buildozer requirements (Linux)

```sh
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
    autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
    libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev
```

(See https://buildozer.readthedocs.io/ for the canonical list.)

## Roadmap

| Phase | Scope |
|-------|-------|
| 1 ✅ | Skeleton + generator wired to a minimal UI (this) |
| 2 | Port `mxn_emoji_renderer.py` (QPainter → Pillow) and show preview image |
| 3 | Color pickers + endpoint emoji controls |
| 4 | JSON / PNG export via Android storage |
| 5 | Continuation, parallel alignment, Full Auto batch |
| 6 | Polish, settings persistence, signed release build |
