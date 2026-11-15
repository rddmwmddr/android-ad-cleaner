# 一加 16（PYB110，ColorOS 17）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 九段全是数据，这里只剩家族库要读的模块级常量。

BUILD = "PYB110_17.0.0"

# 全局搜索的设置页 scheme 与页面标题：家族库打开设置页 / 认页时按这些名字从执行作用域取。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 设置页上的标题；搜索首页也有「搜索范围」这类文字，所以还要看前台 Activity（SearchSettingActivity）。
SEARCH_TITLES = {"搜索范围", "首页卡片管理", "功能管理", "账号与隐私"}
