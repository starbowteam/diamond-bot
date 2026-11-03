#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Точка входа для AI Manager (третий процесс)."""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from modules.ai_manager import run_ai_manager

if __name__ == "__main__":
    run_ai_manager()
