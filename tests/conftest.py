import pytest

from dexweb.features.library.worm_worker import get_worm_worker, reset_worm_worker


@pytest.fixture(autouse=True)
def isolate_worm_worker():
    worker = None
    try:
        worker = get_worm_worker()
        worker.drain(timeout=5)
    except Exception:
        pass
    reset_worm_worker()
    yield
    try:
        worker = get_worm_worker()
        worker.drain(timeout=5)
    except Exception:
        pass
    reset_worm_worker()
