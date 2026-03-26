#!/usr/bin/env python3
"""
Runner script for OKX Regime-Aware Trading System
"""
import os
import sys

# Add the project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from regime_trader.main import main

if __name__ == "__main__":
    main()
