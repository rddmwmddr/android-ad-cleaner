# V2303A 本机例外函数（catalog，沿用 #1263 的页面树）：全局搜索的多页循环是过程段。
# 由 catalog.loader 装进执行作用域（preamble 已注入 maybe / SkipStep / time）。


import recipe_nav as nav
def step_global_search(p, rt):
    # 每个子页都先重新 p.setting("全局搜索") 回到主页再钻，保证每段起点干净。
    for name, switches in (
        ("首页展示内容", ["搜索框推荐词", "推荐卡片"]),
        ("推荐热搜榜单", ["热门搜索"]),        # Android 17 上无此入口（#220），找不到即跳过
        ("个性化内容", ["广告个性化"]),          # 历史记录、应用建议保留
    ):
        # 放在 try 外面：搜不到要记成整段未完成，不能被下面「单页跳过」的 except 吞掉（#819）
        if not p.setting("全局搜索"):
            raise RuntimeError("没搜到「全局搜索」")
        try:
            if nav.maybe(p, rt, name, scrolls=2):
                p.off(only=switches, page=f"全局搜索·{name}"); p.back()
        except Exception as e:
            print(f"  · {name} 跳过：{e}")
