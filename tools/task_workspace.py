#!/usr/bin/env python3
"""开发态兼容入口；实现统一位于可随运行包分发的模块中。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoresearch_flow.task_workspace import main


if __name__ == "__main__":
    raise SystemExit(main())
