"""Shared config loader for parameters.yaml."""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "parameters.yaml"


def load_parameters() -> dict:
    """Load strategy parameters from config/parameters.yaml."""
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Could not load {_CONFIG_PATH}: {e}")
    return {}
