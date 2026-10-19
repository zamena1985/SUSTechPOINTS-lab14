# -*- coding: utf-8 -*-
"""
Сборка дополнения dist/SUSTechPOINTS-tensorflow.zip: TensorFlow и пакеты, нужные только ему,
из рабочего окружения venv проекта (те же версии, что в полной сборке).
Студент распаковывает архив поверх папки SUSTechPOINTS облегчённой версии; при следующем
запуске программа использует нейросеть авто-поворота.

Запуск из корня проекта:
    venv\\Scripts\\python tools\\make_tf_addon.py
"""
import sys, zipfile, pathlib, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from venv_dists import VenvDists   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "SUSTechPOINTS-tensorflow.zip"


def log(msg): print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    vd = VenvDists(ROOT / "venv")
    names = vd.tf_only_names()
    if "tensorflow" not in names: sys.exit("в venv нет tensorflow")
    files = vd.files(names)
    log(f"дистрибутивов: {len(names)}, файлов: {len(files)}")
    OUT.parent.mkdir(exist_ok=True)
    if OUT.exists(): OUT.unlink()
    size = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in files:
            src = vd.sp / rel
            z.write(src, "SUSTechPOINTS/python/Lib/site-packages/" + rel.as_posix()); size += src.stat().st_size
    log(f"архив: {OUT.relative_to(ROOT)}, распаковано {size // 1048576} МБ, сжато {OUT.stat().st_size // 1048576} МБ")
    print("пакеты:", ", ".join(sorted(names)))


if __name__ == "__main__":
    main()
