import sys
from pathlib import Path


def pytest_configure(config):
    root = Path(__file__).parent
    backend_dir = root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
