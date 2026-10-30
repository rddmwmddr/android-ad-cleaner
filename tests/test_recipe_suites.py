"""将机型自带的离线测试接入现有 unittest 入口，不导入或执行配方本身。"""
import importlib.util
from pathlib import Path
import sys


def load_tests(loader, tests, pattern):
    recipes = Path(__file__).resolve().parents[1] / "recipes"
    for path in sorted(recipes.glob("*/tests/test_*.py")):
        name = "recipe_test_" + "_".join(path.relative_to(recipes).with_suffix("").parts)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        tests.addTests(loader.loadTestsFromModule(module))
    return tests
