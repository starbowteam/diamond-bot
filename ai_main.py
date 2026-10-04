#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Точка входа для Diamond AI (отдельный процесс)."""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from modules.ai import run_ai

if __name__ == "__main__":
    run_ai()
