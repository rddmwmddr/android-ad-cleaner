"""upload_baidu.sh 的辅助：读写 index.html 里的发布信息（REL）。
  baidu_rows.py <版本> <安装说明输出路径>   打印「id<TAB>网盘文件夹<TAB>文件名」，并按下载页文字写安装说明
  baidu_rows.py --write                     从标准输入读「id<TAB>链接<TAB>提取码」（id=all 是全部版本的总链接），写回 index.html
  baidu_rows.py --legacy <版本> <输出目录> <SHA256SUMS.txt>
                                            给网盘旧目录 /去广告/ 生成「先看我-选哪个文件夹.txt」和各平台的安装说明、校验值
"""
import os
import re
import sys

PAGE = "index.html"
ITEM = re.compile(r'\{ id: "([\w-]+)", folder: "([^"]+)", baidu: \{[^}]*\}, title: "([^"]+)", sub: "([^"]+)", '
                  r'file: "([^"]+)"[^\n]*\n\s*note: "([^"]+)"')


# 下载页的 id → 安装说明的种类。没登记的 id 在上传之前就报错，不要等安装包传完才崩
KINDS = {"mac-arm64": "mac", "mac-intel": "mac", "win-setup": "win-setup", "win-zip": "win-zip", "android": "android"}


def kind_of(key):
    if key not in KINDS:
        sys.exit(f"index.html 里的 id「{key}」没有登记：在 baidu_rows.py 的 KINDS、SETUP、CHECK 里补上（手机版的 id 是 android）")
    return KINDS[key]


def rows(ver, guide):
    html = open(PAGE, encoding="utf-8").read()
    items = [i for i in ITEM.findall(html) if ver in i[4]]
    for item in items:
        kind_of(item[0])
    lines = [f"肉呆去广告 v{ver}", "", "选哪个文件："]
    lines += [f"· {title}（{sub}）：{folder}/{file}。{note}" for _, folder, title, sub, file, note in items]
    lines += ["", "不知道 Mac 是哪种芯片：左上角苹果图标 → 关于本机，「芯片」写 Apple M 开头的选 Apple 芯片。",
              f"SHA256SUMS.txt 是 {len(items)} 个文件的 SHA256 校验值。",
              "用法、常见问题、反馈：https://github.com/rddmwmddr/android-ad-cleaner"]
    with open(guide, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    for item in items:
        print("\t".join((item[0], item[1], item[4])))


def write(stream):
    html = open(PAGE, encoding="utf-8").read()
    for line in stream:
        key, url, code = line.rstrip("\n").split("\t")
        value = 'baidu: { url: "%s", code: "%s" }' % (url, code)
        if key == "all":
            html, n = re.subn(r"(\n  )baidu: \{[^}]*\}(,)", lambda m: m.group(1) + value + m.group(2), html, count=1)
        else:
            html, n = re.subn(r'(\{ id: "%s", folder: "[^"]+", )baidu: \{[^}]*\}' % re.escape(key),
                              lambda m: m.group(1) + value, html)
        if n != 1:
            sys.exit(f"index.html 里没找到 {key}")
        print(f"{key:10} {url}  提取码 {code}")
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(html)


INTRO = ("关掉国产安卓手机系统里的广告、热搜、资讯推荐和营销推送。\n"
         "不 root，不刷机，系统更新不受影响，每一项能还原。不需要 Python，也不需要 AI 工具。\n")
SETUP = {
    "mac": ["双击 {file}，把「肉呆去广告」拖进「应用程序」文件夹。",
            "在「应用程序」里双击打开。安装包有苹果公证。"],
    "win-setup": ["双击 {file}，按提示安装。",
                  "弹出「Windows 已保护你的电脑」：点「更多信息」→「仍要运行」（安装程序没有代码签名）。",
                  "提示缺少 WebView2：到微软官网安装「WebView2 Evergreen Bootstrapper」，然后打开本程序。",
                  "启动失败提示里的文字已经复制到剪贴板，可直接粘贴到反馈里，不用手抄。"],
    "win-zip": ["先对下载的 zip 点右键 →「属性」→ 勾选「解除锁定」→ 确定，再解压，双击里面的 AndroidAdCleaner.exe。",
                "弹出「Windows 已保护你的电脑」：点「更多信息」→「仍要运行」。",
                "提示「程序文件被 Windows 标记成「来自网络」」：按第一条重新解除锁定再解压。",
                "提示缺少 WebView2：到微软官网安装「WebView2 Evergreen Bootstrapper」，然后打开本程序。",
                "启动失败提示里的文字已经复制到剪贴板，可直接粘贴到反馈里，不用手抄。"],
    "android": ["把 {file} 传到手机上，点开安装（安卓 11 及以上）。",
                "弹风险提示：vivo 先勾选「已了解应用的风险检测结果」，再点「继续安装」；小米、OPPO 点「继续安装」或「仍然安装」。"],
}
USAGE = ("使用\n----\n1. 手机打开开发者模式和 USB 调试（客户端里有图文教程）。\n"
         "2. 用数据线连电脑，手机上点「允许 USB 调试」。荣耀、华为另开「仅充电模式下允许 ADB 调试」；"
         "小米、Redmi 另开「USB 调试（安全设置）」；三星在 Windows 上装三星 USB 驱动。\n"
         "3. 客户端里：连接手机 → 检测 → 选择要关的 → 执行 → 完成。\n"
         "4. 做完后关闭开发者模式，客户端完成页有按钮。\n\n"
         "第一次打开时，电脑上没有 adb 的话，客户端会提示从 Google 官网下载（约 10 MB）。\n\n")
USAGE_ANDROID = ("使用\n----\n不用连电脑。第一次打开按页面做 3 个设置，之后点「一键去广告」。\n"
                 "图文和视频教程：https://ahuamiao.com/sites/other/android-tutorial.html\n\n")
CHECK = {"mac": "shasum -a 256 文件名（终端）", "win-setup": "Get-FileHash 文件名（PowerShell）", "win-zip": "Get-FileHash 文件名（PowerShell）",
         "android": "在电脑上算：shasum -a 256 文件名（Mac 终端）或 Get-FileHash 文件名（PowerShell）"}


def legacy(ver, out, sums_path):
    html = open(PAGE, encoding="utf-8").read()
    items = [i for i in ITEM.findall(html) if ver in i[4]]
    sums = dict(reversed(line.split(None, 1)) for line in open(sums_path, encoding="utf-8").read().split("\n") if line.strip())
    # `sha256sum -b` 写成「hash *文件名」，星号是格式的一部分，不算文件名
    sums = {name.strip().lstrip("*"): digest for name, digest in sums.items()}
    folders = [f"{folder:<18}{title}（{sub}）" for _, folder, title, sub, _, _ in items]
    with open(os.path.join(out, "先看我-选哪个文件夹.txt"), "w", encoding="utf-8") as f:
        f.write(f"肉呆去广告 {ver}\n{INTRO}\n选哪个文件夹\n------------\n" + "\n".join(folders) +
                "\n\n不知道 Mac 是哪种芯片：点屏幕左上角的苹果图标 → 关于本机，\n"
                "「芯片」一栏写 Apple M 开头的选 Mac-Apple芯片，写 Intel 的选 Mac-Intel芯片。\n\n"
                "每个文件夹里有安装包和这个版本的安装说明。旧版本在官网和 GitHub 的「全部版本」里。\n")
    for key, folder, title, sub, file, note in items:
        kind = kind_of(key)
        digest = sums.get(file)
        if not digest:
            sys.exit(f"SHA256SUMS.txt 里没有 {file}，先补上再生成安装说明")
        os.makedirs(os.path.join(out, folder), exist_ok=True)
        steps = "\n".join(f"{n}. {line.format(file=file)}" for n, line in enumerate(SETUP[kind], 1))
        with open(os.path.join(out, folder, "安装说明.txt"), "w", encoding="utf-8") as f:
            f.write(f"肉呆去广告 {ver}\n{INTRO}\n适用：{title}（{sub}）。\n\n安装\n----\n{steps}\n\n"
                    + (USAGE_ANDROID if kind == "android" else USAGE) +
                    "更多\n----\n官网：https://ahuamiao.com/sites/other/android-ad-removal-intro.html\n"
                    "源代码：https://github.com/rddmwmddr/android-ad-cleaner\n"
                    + ("遇到问题：App 右上角「⋯」→「反馈问题」\n\n" if kind == "android"
                       else "遇到问题：客户端左下角「反馈问题」或「上报错误日志」\n\n") +
                    f"校验\n----\nSHA-256：{digest}\n验证方法：{CHECK[kind]}\n")
        with open(os.path.join(out, folder, "SHA256校验.txt"), "w", encoding="utf-8") as f:
            f.write(f"{digest}  {file}\n")
        print("\t".join((key, folder, file)))


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        write(sys.stdin)
    elif sys.argv[1:2] == ["--legacy"]:
        legacy(*sys.argv[2:5])
    else:
        rows(sys.argv[1], sys.argv[2])
