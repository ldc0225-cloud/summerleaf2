"""
Android asset-path shim for pygame.

On Android (python-for-android + SDL2), pygame's file loaders
(image.load, font.Font, mixer.music.load, mixer.Sound) go through
SDL_RWFromFile. On Android, SDL treats RELATIVE paths as APK
asset-manager paths, NOT real filesystem paths. The p4a app files live
on the real filesystem (cwd = /data/.../files/app), so relative paths
raise "FileNotFoundError: No file '...' found in working directory".
Absolute paths bypass the asset manager and read the real filesystem.

This module rewrites relative asset paths to absolute ones (based on the
current working directory) before handing them to pygame. On desktop it
is a no-op (relative paths already resolve from cwd), so behaviour there
is unchanged.

Import this module as early as possible (before any asset is loaded).
"""

import os

import pygame


def _to_abs(path):
    try:
        if isinstance(path, os.PathLike):
            path = os.fspath(path)
        if isinstance(path, bytes):
            path = path.decode("utf-8", "ignore")
        if isinstance(path, str) and path and not os.path.isabs(path):
            cand = os.path.join(os.getcwd(), path)
            if os.path.exists(cand):
                return cand
    except Exception:
        pass
    return path


def _wrap(func):
    def wrapper(*args, **kwargs):
        if args:
            args = (_to_abs(args[0]),) + tuple(args[1:])
        return func(*args, **kwargs)

    return wrapper


if not getattr(pygame, "_android_path_shim", False):
    try:
        pygame.image.load = _wrap(pygame.image.load)
    except Exception:
        pass
    try:
        pygame.font.Font = _wrap(pygame.font.Font)
    except Exception:
        pass
    try:
        pygame.mixer.music.load = _wrap(pygame.mixer.music.load)
    except Exception:
        pass
    try:
        pygame.mixer.Sound = _wrap(pygame.mixer.Sound)
    except Exception:
        pass
    pygame._android_path_shim = True
