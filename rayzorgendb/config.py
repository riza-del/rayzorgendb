"""
RayzorgenDB Configuration
"""

import os


class Config:
    """Global configuration for RayzorgenDB."""

    DATA_DIR = os.environ.get(
        "RAYZORGEN_DATA_DIR", "./rayzorgen_data"
    )

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 100000

    HTTP_HOST = "0.0.0.0"
    HTTP_PORT = int(os.environ.get("RAYZORGEN_PORT", "9000"))

    ENCRYPTION_PASSWORD = os.environ.get(
        "RAYZORGEN_ENCRYPTION_KEY", ""
    )
    ENCRYPTION_ENABLED = False
    AUTOSAVE_EVERY = 50
    LOCK_TIMEOUT = 30

    # Mode: full | large | safe
    MODE = "full"

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def apply_large_mode(self):
        """RAM optimized for large datasets."""
        self.MODE = "large"
        self.AUTOSAVE_EVERY = 10000

    def apply_safe_mode(self):
        """Conservative mode."""
        self.MODE = "safe"
        self.AUTOSAVE_EVERY = 20

    def apply_fast_mode(self):
        """Full features, best speed."""
        self.MODE = "full"
        self.AUTOSAVE_EVERY = 500

    def apply_auto_mode(self):
        """Auto-detect best mode based on RAM."""
        from rayzorgendb.stability import auto_choose_mode
        self.MODE = auto_choose_mode()
        if self.MODE == "large":
            self.AUTOSAVE_EVERY = 10000
        else:
            self.AUTOSAVE_EVERY = 500
        return self.MODE

    def is_large(self) -> bool:
        return getattr(self, "MODE", "full") == "large"

    def clone(self) -> "Config":
        new = Config()
        new.DATA_DIR = self.DATA_DIR
        new.DEFAULT_LIMIT = self.DEFAULT_LIMIT
        new.MAX_LIMIT = self.MAX_LIMIT
        new.HTTP_HOST = self.HTTP_HOST
        new.HTTP_PORT = self.HTTP_PORT
        new.AUTOSAVE_EVERY = self.AUTOSAVE_EVERY
        new.ENCRYPTION_PASSWORD = self.ENCRYPTION_PASSWORD
        new.ENCRYPTION_ENABLED = self.ENCRYPTION_ENABLED
        new.LOCK_TIMEOUT = self.LOCK_TIMEOUT
        new.MODE = getattr(self, "MODE", "full")
        return new


DEFAULT_CONFIG = Config()
