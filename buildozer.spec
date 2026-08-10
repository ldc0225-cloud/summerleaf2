[app]
title = Summerleaf2
package.name = summerleaf2
package.domain = org.test
source.dir = .
source.include_exts = py,png,jpg,jpeg,ttf,otf,ttc,wav,mp3,json
# APK에 빌드용 레시피 폴더가 들어가지 않게 제외
source.exclude_dirs = p4a-recipes,.git,__pycache__,bin,.buildozer
version = 0.1
# Mode7(3d_rotate): Android는 numpy 없이 Surface get_at 폴백으로 동작.
# numpy 패키징은 p4a(Python 3.10.12)에서 반복 실패 → 성공 빌드(#40) 구성으로 복귀.
# PC/고품질 Mode7용 로컬 레시피는 p4a-recipes/ 에 남겨 두고, 빌드 requirements 에서는 제외.
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
