"""adapt.py 三条子命令的对拍用例：同一份用例既生成基线，也比对新实现。

`gen` 不碰手机，每条分支都能在子进程里跑到；`check` / `explore` 只有 `Phone` 之前的参数校验
能进对拍，需要手机的档位（锁屏、报告结论）在 tests/test_adapt_assistant.py 里进程内断言。

用例里的路径一律相对，子进程的工作目录就是临时目录，输出里不会留下绝对路径。
`expect` 是守卫断言：这些子串必须出现在输出里，证明这条用例真的走到了目标分支，
而不是两边都停在同一个错误上。
"""

TSV = """包名\t页面\t开关\t状态\t像广告\t人工勾选
# 在末列写「关」挑出要关的开关
com.heytap.market\t设置 > 隐私\t个性化推荐\t开\t★\t关
com.heytap.market\t设置 > 隐私\t应用安全\t开\t\t
com.heytap.market\t设置 > 服务管理\t活动弹窗\t开\t★\t关
com.heytap.market\t设置\t限制广告跟踪\t开\t★\t关
"""

HEADER_ONLY_TSV = "包名\t页面\t开关\t状态\t像广告\t人工勾选\n"
UNPICKED_TSV = "com.a\t设置\t个性化推荐\t开\t★\t\n"


def case(name, argv, seed=None, expect=()):
    return {"name": name, "argv": list(argv), "seed": seed or {}, "expect": list(expect)}


CASES = [
    # ---------- gen：生成草稿（不碰手机） ----------
    case("gen-成功", ["gen", "探路-PJA110.tsv"], {"探路-PJA110.tsv": TSV},
         expect=["草稿已生成：草稿-PJA110.py", "BUILD 为空", "均为待验证"]),
    case("gen-型号认不出", ["gen", "探路.tsv"], {"探路.tsv": TSV},
         expect=["草稿已生成：草稿.py", "没能从文件名认出型号"]),
    case("gen-勾选清单", ["gen", "空白.tsv", "--pick", "清单.txt", "--model", "PLP120", "--build", "PLP120_16.0.9"],
         {"空白.tsv": UNPICKED_TSV, "清单.txt": "# 人工确认\n个性化推荐\n"},
         expect=["草稿已生成：草稿-PLP120.py"]),
    case("gen-选项缺值", ["gen", "探路.tsv", "-o"], {"探路.tsv": TSV},
         expect=["选项 -o 后面要跟值"]),
    case("gen-不认识的选项", ["gen", "--bogus"], expect=["不认识的选项 --bogus"]),
    case("gen-两个TSV", ["gen", "a.tsv", "b.tsv"], {"a.tsv": TSV, "b.tsv": TSV},
         expect=["只收一个探路 TSV 文件"]),
    case("gen-没有给TSV", ["gen"], expect=["用法：run.py adapt gen"]),
    case("gen-找不到TSV", ["gen", "无.tsv"], expect=["找不到 无.tsv"]),
    case("gen-没有数据行", ["gen", "空.tsv"], {"空.tsv": HEADER_ONLY_TSV}, expect=["里没有数据行"]),
    case("gen-没有勾选", ["gen", "未勾选.tsv"], {"未勾选.tsv": UNPICKED_TSV},
         expect=["没有勾选任何开关"]),
    case("gen-找不到勾选清单", ["gen", "探路.tsv", "--pick", "无.txt"], {"探路.tsv": TSV},
         expect=["找不到勾选清单 无.txt"]),
    case("gen-写不出", ["gen", "探路.tsv", "-o", "无此目录/草稿.py"], {"探路.tsv": TSV},
         expect=["写不出 无此目录/草稿.py"]),
    # ---------- check：Phone 之前的参数校验 ----------
    case("check-缺参数", ["check"], expect=["用法：run.py adapt check -s"]),
    case("check-参数顺序错", ["check", "S", "草稿.py"], expect=["用法：run.py adapt check -s"]),
    case("check-找不到草稿", ["check", "-s", "S", "无.py"], expect=["找不到 无.py"]),
    # ---------- explore：Phone 之前的参数校验 ----------
    case("explore-缺序列号", ["explore"], expect=["用法：run.py adapt explore -s"]),
    case("explore-只给-s", ["explore", "-s"], expect=["用法：run.py adapt explore -s"]),
    case("explore-参数顺序错", ["explore", "S", "com.a"], expect=["用法：run.py adapt explore -s"]),
    # ---------- 参数分派 ----------
    case("未知子命令", ["bogus"], expect=["adapt 后面跟 survey / explore / gen / check"]),
]
