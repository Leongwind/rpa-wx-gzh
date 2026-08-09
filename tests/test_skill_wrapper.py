import importlib.util
from pathlib import Path


def test_installed_skill_wrapper_discovers_current_checkout():
    path = Path(__file__).parents[1] / "skills/wechat-mp-publisher/scripts/publish.py"
    spec = importlib.util.spec_from_file_location("skill_publish_wrapper", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.find_repo_root(Path(__file__).parents[1]) == Path(__file__).parents[1]
