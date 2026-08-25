import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_link_visits_can_be_loaded_as_a_direct_script(tmp_path):
    """Direct entrypoints must establish the project import path themselves."""
    script = PROJECT_ROOT / "src" / "etl" / "link_visits.py"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import runpy; runpy.run_path({str(script)!r})",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
