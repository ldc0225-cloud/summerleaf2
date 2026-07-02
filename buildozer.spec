[app]
title = Summerleaf2
package.name = summerleaf2
package.domain = org.test
source.dir = .
source.include_exts = py,png,jpg,jpeg,ttf,otf,ttc,wav,mp3,json
version = 0.1
requirements = python3==3.10.12,hostpython3==3.10.12,pygame,sdl2_image,sdl2_mixer,sdl2_ttf
orientation = landscape
osx.kivy_version = 2.1.0
fullscreen = 1
android.archs = armeabi-v7a, arm64-v8a
android.allow_backup = True
android.ndk = 25b
# Android RAM/캐시 튜닝: data.py 의 ANDROID_RAM_PROFILE_* (기본 3GB). 빌드 전 수정 후 재빌드.

[buildozer]
log_level = 2
warn_on_root = 1
