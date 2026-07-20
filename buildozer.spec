[app]
title = Summerleaf2
package.name = summerleaf2
package.domain = org.test
source.dir = .
source.include_exts = py,png,jpg,jpeg,ttf,otf,ttc,wav,mp3,json
# APK에 빌드용 레시피 폴더가 들어가지 않게 제외
source.exclude_dirs = p4a-recipes,.git,__pycache__,bin,.buildozer
version = 0.1
# Mode7(3d_rotate)은 pygame.surfarray+numpy 가 있으면 PC와 동일 품질.
# p4a 기본 numpy(v2.3/meson)는 Python>=3.11 이라 실패 → p4a-recipes/numpy (1.22.3 setuptools) 사용.
requirements = python3==3.10.12,hostpython3==3.10.12,pygame,sdl2_image,sdl2_mixer,sdl2_ttf,numpy
# 로컬 레시피: meson 없는 구식 CompiledComponents numpy (Python 3.10.12 + pygame 호환)
p4a.local_recipes = ./p4a-recipes
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
