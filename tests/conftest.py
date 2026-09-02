import sys
from pathlib import Path

# Belt-and-suspenders alongside pytest.ini's `pythonpath = app`, for pytest
# versions/setups where the ini option isn't picked up.
APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
