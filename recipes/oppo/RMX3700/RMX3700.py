# realme GT Neo5 SE（RMX3700，ColorOS 16）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 六段全是数据（#1368 把软件商店那棵四层嵌套的条件树也搬了进来），这里只剩型号守卫、收尾打印与
# 家族库要读的模块级常量。

BUILD = "RMX3700_16.0.5.1300"
# 家族库按这些常量选走法（沿用 #1245），缺省档见 recipe_lib/oppo.py。
WAIT_PAGE_TIMEOUT = 8

# 全局搜索的设置页 SearchSettingActivity 没有导出：am start -n 直接被系统拒绝
# （SecurityException: not exported，和 ColorOS 17 的 PKT110 一样），只能用它自己的 scheme 打开。
# 前置条件：com.heytap.quicksearchbox 不能被挂起——它一挂，这个 scheme 落到系统的
# SuspendedAppActivity「应用已被暂停」页，全局搜索整个不可用，本段也做不了。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"


def guard(p, rt):
    model = p.shell("getprop ro.product.model").strip()
    build = p.shell("getprop ro.build.display.id").strip()
    if model != "RMX3700" or not build.startswith(BUILD):
        rt.skip("型号或系统版本不同，跳过；请重新核对页面")


def tail(p, rt):
    print("\n== 结果", flush=True)
    for name, state in rt.results:
        print(f"  {name}: {state}")
