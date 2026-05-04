[app]

title = MxN CAD Generator
package.name = mxncad
package.domain = org.mxn

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,txt
source.include_patterns = mxn_app/**, assets/**
source.exclude_dirs = tests, bin, .buildozer

version = 0.1.0

requirements = python3,kivy==2.3.0,pillow

orientation = portrait
fullscreen = 0

android.api = 33
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True

# Permissions kept minimal for Phase 1; storage perms will come with the export feature.
android.permissions =

# Asset compression: large emoji bundles do not compress well; let APK ship them raw.
android.no_compress = png,jpg,jpeg

[buildozer]
log_level = 2
warn_on_root = 1
