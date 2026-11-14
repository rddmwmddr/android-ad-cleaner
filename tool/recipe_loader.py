"""机型脚本的唯一装载器（ADR-0038）：`fast.execute` 的 run 分支、`adapt.check_draft`、
`tests/fixtures.load_recipe` 都走这里。

唯一的数据形态是 catalog（`.toml` 或目录），装载本身在 `tool/catalog/loader.py`；这里只按同一处入口
转发，不再有 `.py` 脚本分支，也不再建执行作用域（注入面已拆除，#1268）。
"""
from pathlib import Path


def load(path, p, only=(), clock=None, namespace=None):
    """装载一份数据（不执行任何段）。`only` 为空表示「全部段」。"""
    if Path(path).suffix == ".py":
        raise ValueError(f"{path}：机型脚本已改成 catalog 数据（.toml），不再装载 .py 脚本")
    import catalog
    return catalog.load(path, p, only=only, clock=clock, namespace=namespace)


def run(path, p, only=(), clock=None, namespace=None):
    """装载并跑完一份数据，返回装载对象（`fast.execute` 的 run 分支与 `adapt` 自检共用）。"""
    recipe = load(path, p, only=only, clock=clock, namespace=namespace)
    recipe.run()
    return recipe
