"""Data Vault 2.0 modelling platform — auditable enterprise data vault.

Pure-stdlib core (hashing, hubs/links/satellites, PIT/bridge, marts);
FastAPI is an optional thin service layer on top of the same engine.
"""

from datavault.config import Settings, load_default_model
from datavault.store import VaultStore
from datavault.loader import VaultLoader

__all__ = ["Settings", "VaultStore", "VaultLoader", "load_default_model"]
__version__ = "1.0.0"
