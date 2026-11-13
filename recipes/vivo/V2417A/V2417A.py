# V2417A 本机例外函数（catalog，#1263）：close_named_vivo 的回读走这里的 verify，段末打印走 tail。
# 由 catalog.loader 装进执行作用域（preamble 已注入 require / rt / read_switches 等）。

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import require, rt

def title_key(title):
    # vivo 将说明拼在点号后；「，开启/，关闭」状态尾缀已由引擎在标题产出处剥掉（#565）。
    return title.split(".", 1)[0].strip()


def verify(before, current, names, page):
    require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
    require(all(current.get(name) == state for name, state in before.items() if name not in names),
            f"{page}：其他开关状态变化，请核对")
    rt.confirm(len(names))
    print(f"  ✓ {page}：回读确认 {len(names)} 项关闭，其他开关未变", flush=True)


def tail():
    print(f"\n回读确认 {rt.verified} 项关闭；未完成 {len(rt.failed_steps)} 段", flush=True)
