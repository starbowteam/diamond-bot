# -*- coding: utf-8 -*-
"""
Состояние экранов витрины. Discord не хранит «где я сейчас в меню»,
поэтому держим сами — по ID сообщения (у одного юзера может быть
несколько витрин в разных каналах).
"""
from typing import Optional

_SCREENS: dict[int, dict] = {}


def get(message_id: int) -> Optional[dict]:
    return _SCREENS.get(message_id)


def set_(message_id: int, **kwargs) -> dict:
    cur = _SCREENS.setdefault(message_id, {})
    cur.update(kwargs)
    return cur


def clear(message_id: int):
    _SCREENS.pop(message_id, None)


def cleanup_old(max_size: int = 200):
    if len(_SCREENS) > max_size:
        for k in list(_SCREENS.keys())[:len(_SCREENS) - max_size]:
            _SCREENS.pop(k, None)
