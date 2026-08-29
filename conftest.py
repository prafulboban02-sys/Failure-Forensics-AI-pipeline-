"""
Ensures `from src...` imports resolve correctly regardless of how pytest
is invoked. (Belt-and-braces alongside running `python -m pytest`, which
already adds the current directory to sys.path.)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
