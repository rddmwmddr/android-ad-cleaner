# V2417A 本机例外函数（catalog，#1263）：close_named_vivo 的回读走这里的 verify，段末打印走 tail。
# 由 catalog.loader 装进执行作用域（preamble 已注入 require / rt / read_switches 等）。


def tail(p, rt):
    print(f"\n回读确认 {rt.verified} 项关闭；未完成 {len(rt.failed_steps)} 段", flush=True)
