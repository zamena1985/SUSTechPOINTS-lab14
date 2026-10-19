# -*- coding: utf-8 -*-
"""
Дистрибутивы Python в рабочем окружении venv проекта: какие нужны только TensorFlow,
какие составляют облегчённый набор, и копирование их файлов по RECORD.
Используется сборкой портативной версии (make_portable.py) и дополнения (make_tf_addon.py).
"""
import importlib.metadata as md
import pathlib, re, shutil

# корни облегчённого набора: всё, что нужно серверу и инструментам без нейросети
LITE_ROOTS = {"cherrypy", "cheroot", "jinja2", "filterpy", "markdown"}
TF_ROOTS = {"tensorflow"}
SKIP = {"pip", "setuptools", "wheel"}          # во встроенный Python pip ставится отдельно (get-pip)


def _norm(name: str) -> str:
    return name.lower().replace("_", "-")


class VenvDists:
    def __init__(self, venv: pathlib.Path):
        self.sp = (venv / "Lib" / "site-packages").resolve()
        self.dists = {_norm(d.metadata["Name"]): d for d in md.distributions(path=[str(self.sp)])}

    def _deps(self, name: str):
        d = self.dists.get(name); out = set()
        for r in (d.requires or []) if d else []:
            if "extra ==" in r: continue                       # необязательные дополнения не берём
            m = re.match(r"\s*([A-Za-z0-9_.\-]+)", r)
            n = _norm(m.group(1)) if m else None
            if n in self.dists: out.add(n)
        return out

    def closure(self, roots):
        seen, stack = set(), list(roots)
        while stack:
            n = stack.pop()
            if n in seen or n not in self.dists: continue
            seen.add(n); stack.extend(self._deps(n))
        return seen

    def all_names(self):
        return set(self.dists) - SKIP

    def tf_only_names(self):
        return (self.closure(TF_ROOTS) - self.closure(LITE_ROOTS)) - SKIP

    def lite_names(self):
        return self.all_names() - self.tf_only_names()

    def files(self, names):
        """Файлы дистрибутивов (пути относительно site-packages), только внутри site-packages."""
        out = []
        for n in sorted(names):
            for f in (self.dists[n].files or []):
                p = (self.sp / f).resolve()
                if self.sp not in p.parents or not p.is_file(): continue   # скрипты из Scripts/ и т.п. не нужны
                if "__pycache__" in p.parts: continue
                out.append(p.relative_to(self.sp))
        return out

    def copy(self, names, dst_sp: pathlib.Path):
        n = size = 0
        for rel in self.files(names):
            src = self.sp / rel; dst = dst_sp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst); n += 1; size += src.stat().st_size
        return n, size


if __name__ == "__main__":
    root = pathlib.Path(__file__).resolve().parent.parent
    vd = VenvDists(root / "venv")
    def mb(names): return sum((vd.sp / f).stat().st_size for f in vd.files(names)) // 1048576
    print("всего:", len(vd.all_names()), "дистрибутивов,", mb(vd.all_names()), "МБ")
    print("облегчённый набор:", len(vd.lite_names()), "дистрибутивов,", mb(vd.lite_names()), "МБ")
    print("только TensorFlow:", len(vd.tf_only_names()), "дистрибутивов,", mb(vd.tf_only_names()), "МБ")
    print("TF-only:", ", ".join(sorted(vd.tf_only_names())))
