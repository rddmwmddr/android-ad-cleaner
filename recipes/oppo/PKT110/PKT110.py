# OPPO Find X8s（PKT110，ColorOS 17）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 全部段都是数据；这里只剩模块级常量与收尾打印。

BUILD = "PKT110_17.0.0.102(CN01)"


def tail(p, rt):
    print(f"\n已回读确认 {rt.verified} 项；未完成步骤 {len(rt.failed_steps)} 个", flush=True)
