import subprocess
import sys
from pathlib import Path


def test_main_entrypoint_uses_new_publisher_cli():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "微信公众号文章发布器" in result.stdout
    assert "publish" in result.stdout
    assert "--browser" not in result.stdout
