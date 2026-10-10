import os
import sys
import tempfile
from pathlib import Path

# Isolated storage and fake providers BEFORE the app is imported: tests never touch
# real data, the network, or credits.
os.environ["VANI_STORAGE"] = tempfile.mkdtemp(prefix="vani_test_")
os.environ["FAKE_PROVIDERS"] = "1"
os.environ["VANI_DB"] = "sqlite"
os.environ["VANI_AUTH_DISABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
