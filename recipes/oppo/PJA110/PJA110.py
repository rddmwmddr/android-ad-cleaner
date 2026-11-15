# 一加 Ace 2 Pro（PJA110，ColorOS 14）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 四段都已是数据，这里只剩收尾钩子。


def tail(p, rt):
    print(f"\n已回读确认 {rt.verified} 项；未完成步骤 {len(rt.failed_steps)} 个", flush=True)
