@echo off
rem После правки любого файла в public\js запустите этот файл: он ставит новую версию в адресах скриптов,
rem иначе браузер возьмёт старые файлы из кеша. Потом в браузере - обычный F5.
cd /d "%~dp0"
venv\Scripts\python -c "import re,datetime;V=datetime.datetime.now().strftime('%%Y%%m%%d%%H%%M');fs={'index.html':r'(/static/js/main\.js)\?v=\d+','public/js/main.js':r'(\./editor\.js)\?v=\d+','public/js/save.js':r'(\./editor\.js)\?v=\d+','public/js/editor.js':r'(\./(?:view|box_editor|box_op|floatlabel)\.js)\?v=\d+','public/js/box_editor.js':r'(\./(?:side_view_op|ml)\.js)\?v=\d+','public/js/box_op.js':r'(\./ml\.js)\?v=\d+','public/js/view.js':r'(\./lib/OrbitControls\.js)\?v=\d+'};[open(f,'w',encoding='utf-8').write(re.sub(p,r'\1?v='+V,open(f,encoding='utf-8').read())) for f,p in fs.items()];print('версия',V)"
pause
