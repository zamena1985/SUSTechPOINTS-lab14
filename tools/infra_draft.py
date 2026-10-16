"""
Черновые коробки Infrastructure и Pipes для объектов, на которых коробок ещё нет.

Находит скопления точек выше земли, не попавшие ни в одну коробку, и обводит
каждое минимальной по площади коробкой. Длинные объекты режутся на секции
(как стены и заборы у куратора). Узкие высокие объекты (столбы - класс Pipes)

Это ЧЕРНОВИК: каждую коробку нужно проверить глазами - удалить лишнее
(кочки, мусор, чужие классы), подогнать края, объединить или разделить.

Запуск из корня проекта:
  venv\\Scripts\\python tools\\infra_draft.py --frames 64 --dry-run
  venv\\Scripts\\python tools\\infra_draft.py --frames 64
Перед записью копия label/ сохраняется в backup/.
"""
import argparse
import datetime
import glob
import json
import math
import os
import shutil
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(__file__))
from infra_check import ground_height, overlap_share  # noqa: E402
from infra_transfer import CLASS, load_labels, load_points, parse_range, points_in_box  # noqa: E402

MIN_HAG = 0.5          # м, точки ниже считаем землёй, кочками, колеями
MAX_RANGE = 90.0       # м
CELL = 0.4             # м, клетка для поиска скоплений
MIN_PTS = 60
MIN_HEIGHT = 0.8       # м, ниже - не объект по ТЗ (неровности, насыпи)
MIN_EXTENT = 0.8       # м
POLE_EXTENT = 1.0      # уже и выше POLE_HEIGHT - столб: класс Pipes (набор 2 ТЗ)
POLE_HEIGHT = 1.5
HOLLOW_OCC = 0.30      # заполненность прямоугольника точками ниже - "пустая" коробка, режем
HOLLOW_MIN_WIDTH = 4.0 # м, уже этого не режем (стена, забор и так плотные)
HOLLOW_MIN_PART = 2.0  # м, минимальный кусок после разреза
SPLIT_LEN = 12.0       # длиннее - режем на секции
SECTION = 10.0         # примерная длина секции
PAD = 0.05             # м, запас со всех сторон
VERT_CELL = 0.5        # м, клетка для оценки "вертикальности"
VERT_RANGE = 0.6       # м, разброс высоты в клетке, чтобы клетка считалась вертикальной
FLAT_VERT = 0.05       # доля вертикальных клеток ниже - плоское (подъём земли) ...
FLAT_HAG = 1.2         # ... если ещё и медианная высота над землёй ниже этой
NEAR_DIST = 5.0        # м, плоское скопление рядом с готовой инфраструктурой ...
NEAR_VERT = 0.35       # ... с вертикальностью ниже этой - её продолжение (площадка, бордюр)


def verticality(q):
    """Доля клеток 0.5x0.5 м, где точки стоят друг над другом (стена, стойка, штабель)."""
    ij = np.floor(q[:, :2] / VERT_CELL).astype(np.int64)
    key = ij[:, 0] * 1_000_003 + ij[:, 1]
    order = np.argsort(key, kind="stable")
    k, z = key[order], q[order, 2]
    starts = np.r_[0, np.nonzero(np.diff(k))[0] + 1]
    zmax = np.maximum.reduceat(z, starts)
    zmin = np.minimum.reduceat(z, starts)
    return float(((zmax - zmin) >= VERT_RANGE).mean())


def fit_yaw(xy):
    """Угол, при котором точки прижимаются к сторонам коробки (L-shape fitting):
    у Г-образных объектов (стеллаж + стойки) коробка ложится по длинной стороне,
    а не по диагонали, как у прямоугольника минимальной площади."""
    sample = xy if len(xy) <= 4000 else xy[np.random.default_rng(0).choice(len(xy), 4000, replace=False)]
    best = None
    for deg in range(0, 90):
        a = math.radians(deg)
        c1 = sample @ np.array([math.cos(a), math.sin(a)])
        c2 = sample @ np.array([-math.sin(a), math.cos(a)])
        d1 = np.minimum(c1 - c1.min(), c1.max() - c1)
        d2 = np.minimum(c2 - c2.min(), c2.max() - c2)
        score = (1.0 / np.maximum(np.minimum(d1, d2), 0.05)).sum()
        if best is None or score > best[0]:
            best = (score, a)
    return best[1]


def min_area_rect(xy, yaw=None):
    """(центр, длина, ширина, угол) прямоугольника вокруг точек; угол - заданный или подобранный."""
    if len(xy) < 3:
        c = xy.mean(0)
        return c, 0.1, 0.1, yaw or 0.0
    a = fit_yaw(xy) if yaw is None else yaw
    c, s = math.cos(a), math.sin(a)
    r = xy @ np.array([[c, -s], [s, c]])
    lo, hi = r.min(0), r.max(0)
    size = hi - lo
    mid = (lo + hi) / 2
    center = np.array([mid[0] * c - mid[1] * s, mid[0] * s + mid[1] * c])
    if size[1] > size[0]:           # длина - по длинной стороне
        size = size[::-1]
        a += math.pi / 2
    a = math.atan2(math.sin(a), math.cos(a))
    return center, float(size[0]), float(size[1]), a


def make_box(obj_id, pts, ground, yaw=None):
    center, length, width, yaw = min_area_rect(pts[:, :2], yaw)
    bottom = float(np.percentile(ground, 2))
    top = float(np.percentile(pts[:, 2], 99.5))
    return {
        "obj_id": str(obj_id),
        "obj_type": CLASS,
        "psr": {
            "position": {"x": float(center[0]), "y": float(center[1]), "z": (bottom + top) / 2},
            "scale": {"x": length + 2 * PAD, "y": width + 2 * PAD, "z": top - bottom},
            "rotation": {"x": 0, "y": 0, "z": yaw},
        },
    }


def occupancy(xy, yaw, length, width):
    """Доля клеток 0.5 м внутри прямоугольника, где есть точки: мало - коробка в основном пустая."""
    c, s = math.cos(yaw), math.sin(yaw)
    r = xy @ np.array([[c, -s], [s, c]])
    r -= r.min(0)
    cells = {(int(a // 0.5), int(b // 0.5)) for a, b in r}
    total = max(1.0, math.ceil(length / 0.5) * math.ceil(width / 0.5))
    return len(cells) / total


def split_hollow(pts, ground, depth=0):
    """Г-образный или П-образный стеллаж один прямоугольник описывает с большой пустотой
    внутри - такой режем по самому пустому месту вдоль длинной стороны и повторяем."""
    _, length, width, yaw = min_area_rect(pts[:, :2])
    if depth >= 3 or width < HOLLOW_MIN_WIDTH or occupancy(pts[:, :2], yaw, length, width) >= HOLLOW_OCC:
        return [(pts, ground)]
    c, s = math.cos(yaw), math.sin(yaw)
    along = pts[:, 0] * c + pts[:, 1] * s
    across = -pts[:, 0] * s + pts[:, 1] * c
    best = None
    for axis_vals, size in ((along, length), (across, width)):
        if size < 2 * HOLLOW_MIN_PART:
            continue
        lo, hi = axis_vals.min(), axis_vals.max()
        hist, edges = np.histogram(axis_vals, bins=max(4, int(size / 0.5)), range=(lo, hi))
        inner = slice(int(HOLLOW_MIN_PART / 0.5), max(int(HOLLOW_MIN_PART / 0.5) + 1, len(hist) - int(HOLLOW_MIN_PART / 0.5)))
        if hist[inner].size == 0:
            continue
        i = int(np.argmin(hist[inner])) + inner.start
        score = hist[i] / max(1, hist.max())
        if best is None or score < best[0]:
            best = (score, axis_vals, (edges[i] + edges[i + 1]) / 2)
    if best is None:
        return [(pts, ground)]
    _, axis_vals, cut = best
    m = axis_vals < cut
    if m.sum() < MIN_PTS // 2 or (~m).sum() < MIN_PTS // 2:
        return [(pts, ground)]
    return split_hollow(pts[m], ground[m], depth + 1) + split_hollow(pts[~m], ground[~m], depth + 1)


def split_sections(pts, ground):
    """Режет длинное скопление вдоль главной оси на секции ~SECTION м.
    Все секции получают угол целого объекта - ровный ряд коробок, как у куратора."""
    _, length, _, yaw = min_area_rect(pts[:, :2])
    if length <= SPLIT_LEN:
        return [(pts, ground, yaw)]
    k = math.ceil(length / SECTION)
    along = pts[:, 0] * math.cos(yaw) + pts[:, 1] * math.sin(yaw)
    edges = np.linspace(along.min(), along.max() + 1e-6, k + 1)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (along >= a) & (along < b)
        if m.sum() >= MIN_PTS // 2:
            out.append((pts[m], ground[m], yaw))
    return out


def split_cluster(pts, ground):
    out = []
    for part, pg in split_hollow(pts, ground):
        out += split_sections(part, pg)
    return out


def draft(pts, labels, next_id):
    first_id = next_id
    gh = ground_height(pts)
    hag = pts[:, 2] - gh
    m = (hag > MIN_HAG) & (np.hypot(pts[:, 0], pts[:, 1]) < MAX_RANGE)
    for b in labels:
        m &= ~points_in_box(pts, b, margin=0.3)
    p, g, h = pts[m], gh[m], hag[m]
    near = np.zeros(len(p), dtype=bool)
    for b in labels:
        if b.get("obj_type") == CLASS:
            near |= points_in_box(p, b, margin=NEAR_DIST)
    boxes, poles, skipped = [], [], {"подъём земли": 0, "продолжение готовой разметки": 0}
    if len(p) == 0:
        return boxes, poles, skipped
    lo = p[:, :2].min(0)
    ij = np.floor((p[:, :2] - lo) / CELL).astype(int)
    occ = np.zeros(ij.max(0) + 1, dtype=np.int32)
    np.add.at(occ, (ij[:, 0], ij[:, 1]), 1)
    lab, n = ndimage.label(occ >= 2, structure=np.ones((3, 3)))
    pl = lab[ij[:, 0], ij[:, 1]]
    for k in range(1, n + 1):
        sel = pl == k
        if sel.sum() < MIN_PTS or h[sel].max() < MIN_HEIGHT:
            continue
        q, qg = p[sel], g[sel]
        ext = q[:, :2].max(0) - q[:, :2].min(0)
        if ext.max() < MIN_EXTENT:
            continue
        if ext.max() < POLE_EXTENT and h[sel].max() > POLE_HEIGHT:
            pole = make_box(next_id, q, qg)
            pole["obj_type"] = "Pipes"
            poles.append(pole)
            next_id += 1
            continue
        vert = verticality(q)
        if vert < FLAT_VERT and np.median(h[sel]) < FLAT_HAG:
            skipped["подъём земли"] += 1
            continue
        if vert < NEAR_VERT and near[sel].mean() > 0.5:
            skipped["продолжение готовой разметки"] += 1
            continue
        for sq, sg, yaw in split_cluster(q, qg):
            boxes.append(make_box(next_id, sq, sg, yaw))
            next_id += 1

    # коробка, почти целиком лежащая внутри другой черновой, - лишняя
    keep = []
    for b in sorted(boxes, key=lambda b: -b["psr"]["scale"]["x"] * b["psr"]["scale"]["y"]):
        if not any(overlap_share(b, k) > 0.6 for k in keep):
            keep.append(b)
    skipped["внутри другой коробки"] = len(boxes) - len(keep)
    keep = sorted(keep + poles, key=lambda b: int(b["obj_id"]))
    for i, b in enumerate(keep):          # ID подряд, без дыр
        b["obj_id"] = str(first_id + i)
    return keep, [b for b in keep if b["obj_type"] == "Pipes"], skipped


def main():
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default="data/car2_15july_SUS_angle_64-83")
    ap.add_argument("--frames", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--side", choices=["left", "right", "both"], default="both",
                    help="какую сторону от машины размечать (left = y > 0, right = y < 0)")
    args = ap.parse_args()

    frames = sorted(os.path.splitext(os.path.basename(f))[0]
                    for f in glob.glob(os.path.join(args.scene, "lidar", "*.bin")))
    label = lambda name: os.path.join(args.scene, "label", name + ".json")
    # новые ID - больше всех ID в сцене, чтобы не совпасть с чужими объектами
    ids = [int(b["obj_id"]) for f in frames for b in load_labels(label(f)) if str(b.get("obj_id", "")).isdigit()]
    next_id = max(ids + [0]) + 1

    if not args.dry_run:
        dst = os.path.join("backup", "label_before_draft_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.copytree(os.path.join(args.scene, "label"), dst)
        print("Копия разметки:", dst)

    for num in parse_range(args.frames, len(frames)):
        name = frames[num - 1]
        labels = load_labels(label(name))
        pts = load_points(os.path.join(args.scene, "lidar", name + ".bin"))
        boxes, poles, skipped = draft(pts, labels, next_id)
        if args.side != "both":
            want = (lambda b: b["psr"]["position"]["y"] > 0) if args.side == "left" else (lambda b: b["psr"]["position"]["y"] < 0)
            boxes = [b for b in boxes if want(b)]
            poles = [b for b in poles if want(b)]
        next_id += len(boxes)
        skip_txt = ", ".join(f"{k} {v}" for k, v in skipped.items() if v)
        n_inf = len(boxes) - len(poles)
        print(f"#{num}: черновых коробок {len(boxes)} (Infrastructure {n_inf}, Pipes {len(poles)})"
              + (f", пропущено: {skip_txt}" if skip_txt else ""))
        for b in boxes:
            p, s = b["psr"]["position"], b["psr"]["scale"]
            print(f"   {b['obj_type']} {b['obj_id']}: у ({p['x']:.0f}, {p['y']:.0f}), {s['x']:.1f} x {s['y']:.1f} x {s['z']:.1f} м")
        if not args.dry_run and boxes:
            with open(label(name), "w", encoding="utf-8") as f:
                json.dump(labels + boxes, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
