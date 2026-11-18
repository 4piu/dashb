import tomllib
import unittest
from pathlib import Path

from dashb import __version__


class VersionTests(unittest.TestCase):
    def test_package_version_matches_pyproject(self):
        # The release workflow tags from pyproject.toml; the server reports
        # dashb.__version__. Keep them from drifting apart.
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
        self.assertEqual(__version__, project["version"])


if __name__ == "__main__":
    unittest.main()
