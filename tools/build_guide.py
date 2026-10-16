# -*- coding: utf-8 -*-
"""
Сборка гайда README.md в PDF (doc/guide_ru.pdf).

Markdown -> HTML со стилями в духе гайда куратора (белый фон, Arial, голубой акцент)
-> печать в PDF движком Chrome. Ничего, кроме Chrome и пакета markdown, не нужно.

Запуск из корня проекта:
    venv\\Scripts\\python tools\\build_guide.py
"""
import os, re, sys, subprocess, shutil, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "README.md"
HTML = ROOT / "_guide_build.html"
PDF = ROOT / "doc" / "guide_ru.pdf"

try:
    import markdown
except ImportError:
    sys.exit("нужен пакет markdown: venv\\Scripts\\pip install markdown")

CHROME = next((p for p in [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    shutil.which("chrome") or "", shutil.which("msedge") or ""] if p and os.path.exists(p)), None)
if not CHROME:
    sys.exit("не найден Chrome или Edge для печати в PDF")

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
html { font-family: Arial, Helvetica, sans-serif; font-size: 11.5pt; color: #000; background: #fff; }
body { max-width: 100%; margin: 0; line-height: 1.45; }
h1 { font-size: 26pt; font-weight: bold; margin: 0 0 10pt 0; }
h2 { font-size: 19pt; font-weight: bold; color: #009bdd; margin: 22pt 0 10pt 0; page-break-after: avoid; }
h3 { font-size: 14pt; font-weight: bold; margin: 16pt 0 6pt 0; page-break-after: avoid; }
p, li { font-size: 11.5pt; }
strong { font-weight: bold; }
a { color: #009bdd; text-decoration: none; }
img { max-width: 100%; height: auto; display: block; margin: 8pt 0 10pt 0; border: 1px solid #d0d0d0; page-break-inside: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0 12pt 0; font-size: 10.5pt; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
th { background: #009bdd; color: #fff; text-align: left; padding: 5pt 7pt; font-weight: bold; }
td { border-bottom: 1px solid #d9d9d9; padding: 5pt 7pt; vertical-align: top; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 10pt; background: #f1f6f9; padding: 1pt 4pt; border-radius: 3px; }
pre { background: #f1f6f9; border-left: 4px solid #009bdd; padding: 8pt 10pt; font-size: 10pt; overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
hr { border: none; border-top: 1px solid #d9d9d9; margin: 14pt 0; }
ol, ul { padding-left: 22pt; }
li { margin: 2pt 0; }
.toc ol { columns: 2; }
"""

md = SRC.read_text(encoding="utf-8")
# ссылка на сам PDF в PDF не нужна
md = re.sub(r"^Этот же гайд в PDF:.*$", "", md, flags=re.M)
body = markdown.markdown(md, extensions=["tables", "fenced_code", "toc"], output_format="html5")
# пути к картинкам: README лежит в корне, HTML собираем там же, поэтому пути совпадают
html = f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>Гайд SUSTechPOINTS</title><style>{CSS}</style></head><body>{body}</body></html>"
HTML.write_text(html, encoding="utf-8")

PDF.parent.mkdir(parents=True, exist_ok=True)
cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
       "--virtual-time-budget=5000", f"--print-to-pdf={PDF}", HTML.resolve().as_uri()]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
HTML.unlink(missing_ok=True)
if not PDF.exists() or PDF.stat().st_size < 10_000:
    sys.exit("PDF не собрался:\n" + (r.stderr or r.stdout)[-800:])
print(f"готово: {PDF.relative_to(ROOT)}  ({PDF.stat().st_size // 1024} КБ)")
