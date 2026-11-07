"""把 index.html 的图片内嵌成单文件，方便拿到别处托管。
用法：gui/.venv/bin/python gui/standalone.py 输出.html"""
import base64, io, os, re, sys
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
s = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
cache = {}
def uri(path):
    if path not in cache:
        im, buf = Image.open(os.path.join(ROOT, path)), io.BytesIO()
        if im.width <= 256:          # 图标类小图原样留 PNG：拉成 1200 宽的 JPEG 只会更糊、更大（#669）
            im.save(buf, "PNG", optimize=True); mime = "image/png"
        else:
            im = im.convert("RGB").resize((1200, int(im.height * 1200 / im.width)), Image.LANCZOS)
            im.save(buf, "JPEG", quality=86, optimize=True, progressive=True); mime = "image/jpeg"
        cache[path] = f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()
    return cache[path]
s = re.sub(r'((?:src|href)=")((?:images|gui)/[^"]+\.png)(")', lambda m: m.group(1) + uri(m.group(2)) + m.group(3), s)
open(sys.argv[1], "w", encoding="utf-8").write(s)
print(f"内嵌 {len(cache)} 张图，{os.path.getsize(sys.argv[1]) // 1024} KB → {sys.argv[1]}")
