"""Load scanner/.env into the process without importing the retired main module."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from .. import config as scanner_config

# Same order as scanner.main.ENV_PATHS: repo-root .env first, then scanner/.env.
ENV_PATHS = (scanner_config.ROOT_DIR.parent / ".env", scanner_config.ROOT_DIR / ".env")


def load_project_env() -> None:
    """Same precedence as scanner.main: real environment wins, then scanner/.env, then repo .env."""
    for path in ENV_PATHS:
        if not Path(path).exists():
            continue
        for key, value in dotenv_values(path).items():
            if value is None or not str(value).strip():
                continue
            if os.getenv(key, "").strip():
                continue
            os.environ[key] = str(value).strip()
