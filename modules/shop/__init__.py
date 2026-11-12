# -*- coding: utf-8 -*-
"""DC-Shop 2.0 — Pillow-витрина с навигацией через Discord-компоненты."""
from modules.shop.handlers import open_shop, handle_shop_modal
from modules.shop.views import ShopUniversalView

__all__ = [
    "open_shop", "handle_shop_modal",
    "ShopUniversalView",
]