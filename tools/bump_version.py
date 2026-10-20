# -*- coding: utf-8 -*-
"""
Ставит новую версию (?v=ГГГГММДДЧЧММ) в адресах скриптов интерфейса, чтобы браузер не брал
старые файлы из кеша. Запускается через bump_version.bat после правки любого файла в public/js.
"""
import re, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
V = datetime.datetime.now().strftime("%Y%m%d%H%M")
FILES = {
    "index.html": r"(/static/js/main\.js)\?v=\d+",
    "public/js/main.js": r"(\./editor\.js)\?v=\d+",
    "public/js/save.js": r"(\./editor\.js)\?v=\d+",
    "public/js/editor.js": r"(\./(?:view|box_editor|box_op|floatlabel)\.js)\?v=\d+",
    "public/js/box_editor.js": r"(\./(?:side_view_op|ml)\.js)\?v=\d+",
    "public/js/box_op.js": r"(\./ml\.js)\?v=\d+",
    "public/js/view.js": r"(\./lib/OrbitControls\.js)\?v=\d+",
}
total = 0
for rel, pattern in FILES.items():
    p = ROOT / rel
    text = p.read_text(encoding="utf-8")
    text, n = re.subn(pattern, r"\1?v=" + V, text)
    total += n
    p.write_text(text, encoding="utf-8")
print("версия", V, "замен", total)
