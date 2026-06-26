"""
minigames._paths — 미니게임 에셋·프로젝트 루트 경로 (공통).

[배치 규칙]
  코드:  minigames/<game_id>.py
  에셋:  assets/minigames/<game_id>/…
  공용:  assets/minigames/_shared/…
"""

from __future__ import annotations

import os

# summerleaf2/ (main.py 와 같은 레벨)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def minigame_asset(game_id: str, *parts: str) -> str:
    """assets/minigames/<game_id>/ 아래 파일 절대 경로."""
    gid = (game_id or "").strip()
    return os.path.join(PROJECT_ROOT, "assets", "minigames", gid, *parts)


def minigame_shared_asset(*parts: str) -> str:
    """assets/minigames/_shared/ 아래 공통 에셋 경로."""
    return os.path.join(PROJECT_ROOT, "assets", "minigames", "_shared", *parts)
