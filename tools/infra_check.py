"""
Проверка разметки наборов 2-4 ТЗ (Infrastructure, Pipes; Dust - только формат) по облакам точек.

Отчёт делится на два уровня:
  ОШИБКИ   - точно неправильно: коробка в пустоте, под землёй, неверный класс,
             повтор ID, две коробки друг на друге (вставили дважды);
  ПРОВЕРИТЬ - подсказки, решать глазами: лишняя пустота у стороны, объект
             вылезает за сторону, скопления точек без коробок, скачки размера
             и угла у одного ID между соседними кадрами.
Пороги подобраны по кадрам куратора: на его разметке ошибок нет,
подсказок - единицы.

Запуск из корня проекта:
  venv\\Scripts\\python tools\\infra_check.py --scene data/practice_car2 --frames 64
  venv\\Scripts\\python tools\\infra_check.py --frames 64-83
  venv\\Scripts\\python tools\\infra_check.py --frames 64 --box 885     # подробно об одной коробке
"""
import argparse
import glob
import math
import os
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(__file__))
from infra_transfer import CLASS, TASK_CLASSES, load_labels, load_points, parse_range, points_in_box  # noqa: E402

ALLOWED = {"Pedestrian", "Car", "Truck", "Trailer", "Pipes", "Dust", "Infrastructure", "ego_truck", "ego_trailer"}

ABOVE_GROUND = 0.25     # м, точки ниже (земля + 25 см) не считаются объектом
GROUND_CELL = 2.0       # м, клетка карты высоты земли
EMPTY_PTS = 10          # точек объекта внутри коробки - меньше значит пусто
EMPTY_PTS_SMALL = 3     # то же для коробок площадью меньше 1 м² (столбы, тонкие линии)
TILT_MAX = 20           # градусов, наклон коробки Infrastructure по x/y больше - ошибка
BELOW_GROUND = 0.5      # м, насколько низ коробки может уходить под землю
DUP_OVERLAP = 0.6       # доля объёма меньшей коробки внутри другой - дубль
BAND = 0.5              # м, полоса за стороной коробки
SLACK_ABS = 0.4         # м, допустимая пустота с одной стороны
SLACK_REL = 0.15        # или такая доля от размера коробки
OVER_ABS = 300          # точек за боковой стороной ...
OVER_REL = 0.30         # ... и такая доля от точек внутри - объект обрезан
CLUSTER_CELL = 0.5      # м, клетка поиска скоплений без коробок
CLUSTER_MIN_PTS = 300
CLUSTER_SIZE = (2.0, 30.0)  # м, меньше - мелочь, больше - это земля/фон
CLUSTER_MIN_HEIGHT = 1.5    # м
CLUSTER_RANGE = 40.0    # м, дальше пропуски не ищем
CLUSTER_TOP = 3
SIZE_JUMP = 0.25        # относительное изменение размера между соседними кадрами
YAW_JUMP = 5.0          # градусов
MAX_GAP = 5.0           # с, соседние кадры одной серии

SIDES = [("спереди", 0, +1), ("сзади", 0, -1), ("слева", 1, +1), ("справа", 1, -1), ("сверху", 2, +1)]
AXIS_NAME = {"x": "длина", "y": "ширина", "z": "высота"}


def local_coords(pts, b):
    p, yaw = b["psr"]["position"], b["psr"]["rotation"]["z"]
    c, s = math.cos(yaw), math.sin(yaw)
    d = pts - np.array([p["x"], p["y"], p["z"]])
    return np.stack([d[:, 0] * c + d[:, 1] * s, -d[:, 0] * s + d[:, 1] * c, d[:, 2]], axis=1)


def ground_height(pts):
    """Высота земли под каждой точкой: минимум z в клетке 2x2 м (земля бывает неровной)."""
    lo = pts[:, :2].min(0)
    ij = np.floor((pts[:, :2] - lo) / GROUND_CELL).astype(int)
    grid = np.full(ij.max(0) + 1, np.inf)
    np.minimum.at(grid, (ij[:, 0], ij[:, 1]), pts[:, 2])
    # в клетках без земли (стена, крыша) берём минимум по соседям
    grid = np.minimum(grid, ndimage.minimum_filter(grid, size=5))
    return grid[ij[:, 0], ij[:, 1]]


def box_corners_2d(b):
    p, s, yaw = b["psr"]["position"], b["psr"]["scale"], b["psr"]["rotation"]["z"]
    c, sn = math.cos(yaw), math.sin(yaw)
    out = []
    for dx, dy in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
        x, y = dx * s["x"] / 2, dy * s["y"] / 2
        out.append((p["x"] + x * c - y * sn, p["y"] + x * sn + y * c))
    return np.array(out)


def overlap_share(a, b, n=12):
    """Какая доля объёма меньшей коробки лежит внутри другой (оценка по сетке точек)."""
    small, big = (a, b) if np.prod(list(a["psr"]["scale"].values())) <= np.prod(list(b["psr"]["scale"].values())) else (b, a)
    s, p, yaw = small["psr"]["scale"], small["psr"]["position"], small["psr"]["rotation"]["z"]
    g = (np.arange(n) + 0.5) / n - 0.5
    gx, gy, gz = np.meshgrid(g * s["x"], g * s["y"], g * s["z"], indexing="ij")
    c, sn = math.cos(yaw), math.sin(yaw)
    pts = np.stack([p["x"] + gx * c - gy * sn, p["y"] + gx * sn + gy * c, p["z"] + gz], -1).reshape(-1, 3)
    return float(points_in_box(pts, big).mean())


def check_box(pts, b, others, hag, bounds):
    """Возвращает (ошибки, подсказки, подробности)."""
    errors, hints, info = [], [], {}
    s = b["psr"]["scale"]
    p = b["psr"]["position"]
    size = np.array([s["x"], s["y"], s["z"]])
    half = size / 2
    l = local_coords(pts, b)
    obj = hag > ABOVE_GROUND
    inside = np.all(np.abs(l) <= half, axis=1)
    n_in = int((inside & obj).sum())
    info["n_in"] = n_in

    # низ коробки: под землёй, только если он ниже всех точек вокруг (вдали точек мало,
    # карта высоты земли там неточна, поэтому берём самые нижние точки рядом с коробкой)
    # две оценки земли: самые нижние точки рядом и карта высоты земли (по соседним клеткам -
    # она работает, когда земля под объектом закрыта, например столб за штабелем)
    near = np.all(np.abs(l[:, :2]) <= half[:2] + 3.0, axis=1)
    bottom = p["z"] - half[2]
    if near.sum() > 20:
        lowest = float(np.percentile(pts[near, 2], 0.5))
        grid_ground = float(np.median(pts[near, 2] - hag[near]))
        ground = min(lowest, grid_ground)
        info["bottom_vs_ground"] = bottom - ground
        if bottom < ground - BELOW_GROUND:
            errors.append(f"низ коробки на {ground - bottom:.2f} м ниже земли - поднимите низ")

    # пустоту считаем по всем точкам: низкие плоские объекты лежат у самой земли
    if inside.sum() < (EMPTY_PTS if size[0] * size[1] >= 1.0 else EMPTY_PTS_SMALL):
        errors.append("внутри почти нет точек - коробка стоит в пустоте (сдвиньте на объект или удалите)")
        return errors, hints, info
    if n_in < EMPTY_PTS:
        return errors, hints, info   # объект ниже 25 см над землёй - стороны не проверяем

    # пустота у сторон: от стороны до крайних точек объекта (1/99 перцентиль - против выбросов)
    li = l[inside & obj]
    lo = np.percentile(li, 1, axis=0)
    hi = np.percentile(li, 99, axis=0)
    slack = {name: (half[ax] - hi[ax] if sign > 0 else lo[ax] + half[ax]) for name, ax, sign in SIDES}
    info["slack"] = slack

    # вылезание: точки объекта в полосе за стороной, не принадлежащие другим коробкам
    free = obj & ~inside
    for o in others:
        free &= ~points_in_box(pts, o, margin=0.3)
    over = {}
    for name, ax, sign in SIDES:
        band = free & (sign * l[:, ax] > half[ax]) & (sign * l[:, ax] <= half[ax] + BAND)
        for a in range(3):
            if a != ax:
                band &= np.abs(l[:, a]) <= half[a] + (0.0 if a == 2 else 0.2)
        over[name] = int(band.sum())
    info["over"] = over

    yaw = b["psr"]["rotation"]["z"]
    axes = [np.array([math.cos(yaw), math.sin(yaw)]), np.array([-math.sin(yaw), math.cos(yaw)])]
    center = np.array([p["x"], p["y"]])
    for name, ax, sign in SIDES:
        if ax < 2 and over[name] > max(OVER_ABS, OVER_REL * n_in):
            hints.append(f"за стороной {name} ещё {over[name]} точек - объект обрезан? растяните {name}")
            continue
        if ax < 2:
            face = center + sign * half[ax] * axes[ax]
            if np.any(face < bounds[0] + 1) or np.any(face > bounds[1] - 1):
                continue   # сторона за краем облака, лидар там не видит - не проверяем
        if slack[name] > max(SLACK_ABS, SLACK_REL * size[ax]):
            hints.append(f"пустота {name} {slack[name]:.2f} м - можно поджать сторону")
    return errors, hints, info


def uncovered_clusters(pts, boxes, hag):
    m = (hag > 0.5) & (np.hypot(pts[:, 0], pts[:, 1]) < CLUSTER_RANGE)
    for b in boxes:
        m &= ~points_in_box(pts, b, margin=0.3)
    p, h = pts[m], hag[m]
    if len(p) == 0:
        return []
    lo = p[:, :2].min(0)
    ij = np.floor((p[:, :2] - lo) / CLUSTER_CELL).astype(int)
    occ = np.zeros(ij.max(0) + 1, dtype=np.int32)
    np.add.at(occ, (ij[:, 0], ij[:, 1]), 1)
    lab, n = ndimage.label(occ >= 2, structure=np.ones((3, 3)))
    pl = lab[ij[:, 0], ij[:, 1]]
    out = []
    for k in range(1, n + 1):
        sel = pl == k
        if sel.sum() < CLUSTER_MIN_PTS:
            continue
        q = p[sel]
        ext = q[:, :2].max(0) - q[:, :2].min(0)
        height = float(h[sel].max())
        if not (CLUSTER_SIZE[0] <= ext.max() <= CLUSTER_SIZE[1]) or height < CLUSTER_MIN_HEIGHT:
            continue
        c = (q[:, :2].max(0) + q[:, :2].min(0)) / 2
        out.append((int(sel.sum()), c, ext, height))
    return sorted(out, key=lambda x: -x[0])[:CLUSTER_TOP]


def yaw_diff(a, b):
    d = (a - b) % math.pi   # коробка, развёрнутая на 180°, - та же коробка
    return math.degrees(min(d, math.pi - d))


def main():
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default="data/car2_15july_SUS_angle_64-83")
    ap.add_argument("--frames", default="64-83")
    ap.add_argument("--box", help="ID коробки для подробного отчёта")
    args = ap.parse_args()

    frames = sorted(os.path.splitext(os.path.basename(f))[0]
                    for f in glob.glob(os.path.join(args.scene, "lidar", "*.bin")))
    stamp = lambda name: float(name.split("__")[-1])
    label = lambda name: os.path.join(args.scene, "label", name + ".json")
    tot_err = tot_hint = 0

    for num in parse_range(args.frames, len(frames)):
        name = frames[num - 1]
        labels = load_labels(label(name))
        pts = load_points(os.path.join(args.scene, "lidar", name + ".bin"))
        hag = pts[:, 2] - ground_height(pts)
        bounds = (pts[:, :2].min(0), pts[:, :2].max(0))
        errors, hints = [], []

        # формат
        for b in labels:
            missing = [k for k in ("obj_id", "obj_type", "psr") if k not in b]
            if missing:
                errors.append(f"коробка без полей {missing}")
            elif b["obj_type"] not in ALLOWED:
                errors.append(f"{b['obj_type']} {b['obj_id']}: недопустимый класс")
            elif not b["obj_id"]:
                errors.append(f"{b['obj_type']}: коробка без ID")
            elif b["obj_type"] == CLASS:
                # куратор наклоняет коробки автоподгонкой до ~16°, пыль и трубы бывают наклонены сильно;
                # ловим только грубые случаи - стену, завалившуюся на бок
                rx, ry = b["psr"]["rotation"].get("x", 0), b["psr"]["rotation"].get("y", 0)
                if max(abs(math.degrees(rx)), abs(math.degrees(ry))) > TILT_MAX:
                    errors.append(f"{b['obj_type']} {b['obj_id']}: коробка наклонена ({math.degrees(rx):.0f}° / {math.degrees(ry):.0f}°) - "
                                  "в строке сверху первые два угла должны быть 0")
        ids = [b.get("obj_id") for b in labels if b.get("obj_id")]
        for i in sorted({i for i in ids if ids.count(i) > 1}):
            errors.append(f"ID {i} повторяется в кадре несколько раз")

        # проверяем коробки наборов 2-4 ТЗ; Dust - только формат (границы пыли размыты)
        infra = [b for b in labels if b.get("obj_type") in ("Infrastructure", "Pipes")]

        # коробки друг на друге
        for i, a in enumerate(infra):
            ca = box_corners_2d(a)
            for b in infra[i + 1:]:
                cb = box_corners_2d(b)
                if (ca.max(0) < cb.min(0)).any() or (cb.max(0) < ca.min(0)).any():
                    continue
                if overlap_share(a, b) > DUP_OVERLAP:
                    errors.append(f"{a['obj_type']} {a['obj_id']} и {b['obj_id']}: коробки почти совпадают - лишнюю удалите")

        # каждая коробка
        for b in infra:
            others = [o for o in labels if o is not b]
            e, h, info = check_box(pts, b, others, hag, bounds)
            errors += [f"{b['obj_type']} {b['obj_id']}: {x}" for x in e]
            hints += [f"{b['obj_type']} {b['obj_id']}: {x}" for x in h]
            if args.box and b["obj_id"] == args.box:
                s = b["psr"]["scale"]
                print(f"#{num} {b['obj_type']} {b['obj_id']}: размер {s['x']:.2f} x {s['y']:.2f} x {s['z']:.2f} м, "
                      f"точек объекта внутри {info['n_in']}")
                for side in info.get("slack", {}):
                    print(f"    {side:8s} пустота {info['slack'][side]:5.2f} м,  точек за стороной {info['over'][side]}")
                if "bottom_vs_ground" in info:
                    print(f"    низ коробки относительно самых нижних точек рядом: {info['bottom_vs_ground']:+.2f} м")

        # соседние кадры серии: у того же ID похожий размер и угол
        for nb_num in (num - 1, num + 1):
            if not 1 <= nb_num <= len(frames) or abs(stamp(frames[nb_num - 1]) - stamp(name)) > MAX_GAP:
                continue
            nb = {b["obj_id"]: b for b in load_labels(label(frames[nb_num - 1]))}
            for b in infra:
                o = nb.get(b["obj_id"])
                if not o:
                    continue
                for ax, an in AXIS_NAME.items():
                    a, c = b["psr"]["scale"][ax], o["psr"]["scale"][ax]
                    if abs(a - c) > max(0.3, SIZE_JUMP * max(a, c)):
                        hints.append(f"{b['obj_type']} {b['obj_id']}: {an} {a:.1f} м, а в кадре #{nb_num} {c:.1f} м")
                dy = yaw_diff(b["psr"]["rotation"]["z"], o["psr"]["rotation"]["z"])
                if dy > YAW_JUMP:
                    hints.append(f"{b['obj_type']} {b['obj_id']}: угол отличается от кадра #{nb_num} на {dy:.0f}°")

        # скопления точек без коробок
        for n_pts, c, ext, height in uncovered_clusters(pts, labels, hag):
            hints.append(f"без коробки: {n_pts} точек у ({c[0]:.0f}, {c[1]:.0f}), {ext.max():.1f} x {ext.min():.1f} м, "
                         f"высота {height:.1f} м - пропущенный объект?")

        n_cls = {c: sum(b["obj_type"] == c for b in labels) for c in TASK_CLASSES}
        cls_txt = ", ".join(f"{c} {k}" for c, k in n_cls.items())
        print(f"#{num}: {cls_txt} | ошибок {len(errors)}, проверить {len(hints)}")
        for s in errors:
            print("   ОШИБКА   " + s)
        for s in hints:
            print("   проверить " + s)
        tot_err += len(errors)
        tot_hint += len(hints)
    print(f"Итого: ошибок {tot_err}, проверить {tot_hint}")


if __name__ == "__main__":
    main()
