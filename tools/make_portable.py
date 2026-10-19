# -*- coding: utf-8 -*-
"""
Сборка портативной версии.

По умолчанию - облегчённая (без TensorFlow): dist/SUSTechPOINTS-portable.zip, папка dist/portable-lite/.
Поворот новой коробки в ней считается по геометрии точек (algos/pre_annotate.py). Нейросеть можно
добавить потом: install_tensorflow.bat или архив-дополнение SUSTechPOINTS-tensorflow.zip
(собирается tools/make_tf_addon.py из разницы полной и облегчённой сборок).

--full  - полная версия с TensorFlow: dist/SUSTechPOINTS-portable-full.zip, папка dist/portable/.

Внутри архива папка SUSTechPOINTS: программа, встроенный Python 3.10 (embeddable с python.org),
пакеты точных версий (tools/portable_constraints.txt), модель нейросети, пример сцены.
Студент распаковывает архив и запускает start.bat: ничего устанавливать не нужно.

Запуск из корня проекта (нужен интернет при первой сборке):
    venv\\Scripts\\python tools\\make_portable.py [--full] [--reuse-python] [--no-zip]
    --reuse-python   не пересобирать папку python, если она уже есть (быстро после правок кода)
    --no-zip         собрать папку, архив не делать (для проверки)
"""
import sys, shutil, subprocess, zipfile, pathlib, urllib.request, urllib.error, time, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_update import program_files, tracked_files, read_for_package   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
CACHE = DIST / "cache"

FULL = "--full" in sys.argv
REUSE_PY = "--reuse-python" in sys.argv
NO_ZIP = "--no-zip" in sys.argv

STAGE = DIST / ("portable" if FULL else "portable-lite") / "SUSTechPOINTS"
OUT = DIST / ("SUSTechPOINTS-portable-full.zip" if FULL else "SUSTechPOINTS-portable.zip")

PY_VER = "3.10.11"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"
GETPIP_URLS = ["https://bootstrap.pypa.io/pip/3.10/get-pip.py", "https://bootstrap.pypa.io/pip/get-pip.py"]


def log(msg): print(time.strftime("%H:%M:%S"), msg, flush=True)


def download(url: str, dest: pathlib.Path) -> bool:
    """Скачивание через curl (есть в Windows 10+), запасной путь - urllib."""
    if dest.exists(): return True
    log(f"скачиваю {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    if shutil.which("curl"):
        r = subprocess.run(["curl", "-L", "--fail", "--silent", "--show-error", "--retry", "3", "-o", str(tmp), url], capture_output=True, text=True)
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(dest); return True
        if "404" in (r.stderr or ""): log("  нет (404)"); tmp.unlink(missing_ok=True); return False
        log(f"  curl не справился: {(r.stderr or '').strip()[:120]}; пробую urllib")
    try:
        urllib.request.urlretrieve(url, tmp); tmp.replace(dest); return True
    except urllib.error.HTTPError as e:
        log(f"  нет ({e.code})"); tmp.unlink(missing_ok=True); return False


def run(cmd, **kw):
    r = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", capture_output=True, **kw)
    if r.returncode != 0:
        print(r.stdout[-3000:]); print(r.stderr[-3000:])
        sys.exit(f"команда завершилась с ошибкой: {' '.join(map(str, cmd))}")
    return r


def requirements_file() -> pathlib.Path:
    """Полная сборка - requirement.txt как есть; облегчённая - без tensorflow."""
    src = ROOT / "requirement.txt"
    if FULL: return src
    lines = [l for l in src.read_text(encoding="utf-8").splitlines() if not l.strip().lower().startswith("tensorflow")]
    tmp = pathlib.Path(tempfile.gettempdir()) / "sustech_requirement_lite.txt"
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp


def build_python():
    pydir = STAGE / "python"
    sp = pydir / "Lib" / "site-packages"
    if REUSE_PY and (pydir / "python.exe").exists() and (sp / "cherrypy").exists() and (not FULL or (sp / "tensorflow").exists()):
        log("python: использую уже собранную папку"); return
    if pydir.exists(): shutil.rmtree(pydir)
    CACHE.mkdir(parents=True, exist_ok=True)
    embed = CACHE / EMBED_URL.rsplit("/", 1)[1]
    if not download(EMBED_URL, embed): sys.exit("не удалось скачать embeddable Python")
    log("распаковываю Python")
    with zipfile.ZipFile(embed) as z: z.extractall(pydir)
    # разрешаем site-packages: иначе embeddable Python не видит установленные пакеты
    pth = next(pydir.glob("python*._pth"))
    pth.write_text("python310.zip\n.\nLib\\site-packages\nimport site\n", encoding="ascii")
    getpip = CACHE / "get-pip.py"
    if not any(download(u, getpip) for u in GETPIP_URLS): sys.exit("не удалось скачать get-pip.py")
    py = pydir / "python.exe"
    log("ставлю pip")
    run([py, getpip, "--no-warn-script-location", "-q"])
    log("ставлю пакеты" + (" (TensorFlow ~500 МБ, подождите)" if FULL else " (без TensorFlow)"))
    run([py, "-m", "pip", "install", "-q", "--no-warn-script-location", "--disable-pip-version-check",
         "-r", requirements_file(), "-c", ROOT / "tools" / "portable_constraints.txt"])
    run([py, "-m", "pip", "install", "-q", "--no-warn-script-location", "--disable-pip-version-check", "markdown"])
    for p in pydir.rglob("__pycache__"): shutil.rmtree(p, ignore_errors=True)
    check = "import tensorflow as tf, cherrypy, scipy, numpy; print('tf', tf.__version__, 'numpy', numpy.__version__)" if FULL \
        else "import cherrypy, scipy, numpy; print('numpy', numpy.__version__, 'scipy', scipy.__version__)"
    r = run([py, "-c", check], cwd=STAGE)
    log(f"проверка импорта: {r.stdout.strip()}")


def copy_program():
    log("копирую файлы программы")
    files = program_files(ROOT)
    files += [f for f in tracked_files(ROOT) if f.startswith("data/example/")]
    for rel in files:
        dst = STAGE / rel; dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(read_for_package(ROOT, rel))
    models = list((ROOT / "algos" / "models").glob("*.h5"))
    if not models: sys.exit("нет файла модели algos/models/*.h5")
    for m in models: shutil.copy2(m, STAGE / "algos" / "models" / m.name)
    for p in STAGE.rglob("__pycache__"):
        if "python" not in p.parts: shutil.rmtree(p, ignore_errors=True)
    log(f"  файлов программы: {len(files)}, моделей: {len(models)}")
    # сервер должен подниматься в этой папке: импортируем модуль авто-поворота встроенным Python
    r = run([STAGE / "python" / "python.exe", "-c", "from algos import pre_annotate; print('tf' if pre_annotate.rotation_model is not None else 'geometry')"], cwd=STAGE)
    log(f"  авто-поворот в сборке: {r.stdout.strip().splitlines()[-1]}")


def make_zip():
    if OUT.exists(): OUT.unlink()
    log("упаковываю архив")
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(STAGE.rglob("*")):
            if p.is_file():
                z.write(p, "SUSTechPOINTS/" + p.relative_to(STAGE).as_posix()); n += 1
    log(f"архив: {OUT.relative_to(ROOT)}, файлов {n}, {OUT.stat().st_size // 1048576} МБ")


def main():
    log(("ПОЛНАЯ" if FULL else "ОБЛЕГЧЁННАЯ") + f" сборка -> {STAGE.relative_to(ROOT)}")
    STAGE.mkdir(parents=True, exist_ok=True)
    build_python()
    for child in STAGE.iterdir():            # файлы программы кладём заново при каждой сборке
        if child.name != "python": shutil.rmtree(child) if child.is_dir() else child.unlink()
    copy_program()
    size = sum(p.stat().st_size for p in STAGE.rglob("*") if p.is_file())
    log(f"папка готова: {STAGE.relative_to(ROOT)}, {size // 1048576} МБ")
    if not NO_ZIP: make_zip()


if __name__ == "__main__":
    main()
