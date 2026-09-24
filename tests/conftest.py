"""Every test runs against a throwaway data/profile/.env, never your real ones."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="radar-test-"))
os.environ.update(RADAR_DATA_DIR=str(_tmp / "data"), RADAR_PROFILE_DIR=str(_tmp / "profile"),
                  RADAR_LOG_DIR=str(_tmp / "logs"), RADAR_ENV_FILE=str(_tmp / ".env"))
for k in list(os.environ):
    if k.startswith(("X_", "AI_")) or k in ("MY_HANDLE", "POST_CHANNEL", "CONTENT_LANG"):
        del os.environ[k]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import config  # noqa: E402
import store  # noqa: E402


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    """A clean database and .env for every test."""
    if store.DB_PATH.exists():
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(store.DB_PATH) + suffix)
            if p.exists():
                p.unlink()
    if config.ENV_FILE.exists():
        config.ENV_FILE.unlink()
    store.init()
    yield
