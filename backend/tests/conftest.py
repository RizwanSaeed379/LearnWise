"""Every test run writes uploads, the vector index and store.json to a throwaway folder."""
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="learnwise-test-")
