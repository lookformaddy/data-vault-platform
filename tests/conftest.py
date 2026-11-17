import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from datavault.config import Settings, load_default_model
from datavault.demo_data import seed_all
from datavault.loader import VaultLoader
from datavault.store import VaultStore


@pytest.fixture()
def settings():
    return Settings()


@pytest.fixture()
def model():
    return load_default_model()


@pytest.fixture()
def store(model, settings):
    return VaultStore(model, settings.hash_salt)


@pytest.fixture()
def loader(store, model, settings):
    return VaultLoader(store, model, settings)


@pytest.fixture()
def seed():
    return seed_all()


@pytest.fixture()
def loaded(loader, seed):
    for entity, records in seed.items():
        loader.load_full(entity, records, "test-batch", "2026-01-05T09:00:00Z")
    return loader.store
