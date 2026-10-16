"""
Перенос коробок наборов 2-4 ТЗ (Pipes, Dust, Infrastructure) из размеченных
кадров в неразмеченные.

Эти объекты неподвижны, меняется только положение машины. Скрипт совмещает
облако точек целевого кадра с облаком размеченного (образцового) кадра,
находит сдвиг и поворот машины между ними и пересчитывает коробки.

Совмещение: поиск по сетке углов + корреляция карт "вид сверху" (грубо),
затем ICP по точкам (точно). Земля, своя машина и подвижные объекты
перед совмещением удаляются.

Образец ищется только в той же серии кадров (разрыв не больше MAX_GAP секунд):
между сериями машина уезжает далеко и совмещение ненадёжно. Поэтому первый
кадр серии размечается вручную, остальные кадры серии - этим скриптом.

Запуск из корня проекта:
  venv\\Scripts\\python tools\\infra_transfer.py --dry-run          # только отчёт
  venv\\Scripts\\python tools\\infra_transfer.py                    # записать
  venv\\Scripts\\python tools\\infra_transfer.py --frames 65-66     # только часть кадров

Номера кадров - порядковые номера в списке программы (с 1).
Перед записью копия label/ сохраняется в backup/.
Коробки с ID, которые в кадре уже есть, не трогаются.
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
from scipy.spatial import cKDTree

CLASS = "Infrastructure"
TASK_CLASSES = ["Infrastructure", "Pipes", "Dust"]   # наборы 2-4 ТЗ - то, что переносим
STATIC_CLASSES = {"Infrastructure", "Pipes"}  # неподвижные объекты, их точки помогают совмещению

GRID = 0.25            # м, клетка карты "вид сверху" для грубого поиска
Z_MIN, Z_MAX = 0.4, 8.0  # отсекаем землю и всё, что выше
VOXEL = 0.3            # м, прореживание точек для ICP
INLIER = 0.35          # м, точка считается совпавшей, если ближе
MIN_FITNESS = 0.6      # ниже - совмещение ненадёжно, кадр пропускаем
GOOD_FITNESS = 0.8     # выше - совмещение точно удалось
MAX_GAP = 5.0          # с, образец берётся только из той же серии кадров
MIN_PTS_ABS = 15       # меньше точек в коробке - объект не виден
MIN_PTS_SMALL = 6      # то же для коробок площадью меньше 1 м² (тонкие линии, стойки)
LONG_WALL = 20.0       # м, коробки длиннее - стены вдоль дороги, их точки убираем из совмещения
WALL_MARGIN = 2.5      # м, полоса вокруг стены, которую убираем
LM_CELL = 0.4          # м, клетка поиска ориентиров
LM_MIN_PTS = 12
LM_MIN_EXT, LM_MAX_EXT = 0.3, 3.0   # м, размер ориентира в плане
LM_MIN_HEIGHT = 0.5    # м
LM_MATCH = 0.5         # м, ориентир считается совпавшим, если ближе
LM_SEARCH = 8.0        # м, в каком диапазоне сдвига вдоль дороги искать по ориентирам
LM_MIN_SHARE = 0.5     # меньше этой доли ориентиров совпало - совмещение ненадёжно
LOCAL_MARGIN = 2.0     # м, точки в этой полосе вокруг коробок уточняют совмещение
LOCAL_FITNESS = 0.5    # ниже - уточнение не принимаем
LOCAL_MAX_SHIFT = 3.0  # м, уточнение сдвинуло больше - что-то не так, не принимаем
SNAP_SIZE = 3.0        # м, коробки уже этого (столбы, стойки) после переноса "прилипают" к точкам
SNAP_MARGIN = 0.3      # м, в каком радиусе вокруг коробки искать точки объекта
MIN_PTS_REL = 0.05     # или меньше этой доли от точек в образце (ракурс и пыль сильно меняют число точек)


# ---------- чтение данных ----------

def load_points(path):
    return np.fromfile(path, dtype=np.float32).reshape(-1, 4)[:, :3].astype(np.float64)


def load_labels(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def box_yaw(b):
    return b["psr"]["rotation"]["z"]


def points_in_box(pts, b, margin=0.0):
    p = b["psr"]["position"]
    s = b["psr"]["scale"]
    yaw = box_yaw(b)
    c, sn = math.cos(yaw), math.sin(yaw)
    d = pts - np.array([p["x"], p["y"], p["z"]])
    lx = d[:, 0] * c + d[:, 1] * sn
    ly = -d[:, 0] * sn + d[:, 1] * c
    return ((np.abs(lx) <= s["x"] / 2 + margin) &
            (np.abs(ly) <= s["y"] / 2 + margin) &
            (np.abs(d[:, 2]) <= s["z"] / 2 + margin))


def static_points(pts, labels):
    """Точки без земли и без подвижных объектов (своя машина, грузовики, люди...)."""
    keep = (pts[:, 2] > Z_MIN) & (pts[:, 2] < Z_MAX)
    for b in labels:
        if b["obj_type"] not in STATIC_CLASSES:
            keep &= ~points_in_box(pts, b, margin=0.5)
    return pts[keep]


def voxel_down(pts, size):
    keys = np.floor(pts / size).astype(np.int64)
    _, idx = np.unique(keys, axis=0, return_index=True)
    return pts[idx]


# ---------- совмещение ----------

def rot2(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s], [s, c]])


def bev(xy, origin, shape):
    ij = np.floor((xy - origin) / GRID).astype(np.int64)
    ok = (ij[:, 0] >= 0) & (ij[:, 0] < shape[0]) & (ij[:, 1] >= 0) & (ij[:, 1] < shape[1])
    img = np.zeros(shape, dtype=np.float32)
    np.add.at(img, (ij[ok, 0], ij[ok, 1]), 1.0)
    return np.minimum(img, 3.0)


def coarse_align(src_xy, tgt_xy, yaw_range=math.radians(60), yaw_step=math.radians(1.0)):
    """Перебор углов + FFT-корреляция карт вид сверху. Возвращает (yaw, t)."""
    lo = np.minimum(src_xy.min(0), tgt_xy.min(0)) - 40
    hi = np.maximum(src_xy.max(0), tgt_xy.max(0)) + 40
    shape = tuple(int(v) for v in np.ceil((hi - lo) / GRID))
    shape = (int(2 ** math.ceil(math.log2(shape[0]))), int(2 ** math.ceil(math.log2(shape[1]))))
    T = np.fft.rfft2(bev(tgt_xy, lo, shape))
    best = (-1, 0.0, np.zeros(2))
    for yaw in np.arange(-yaw_range, yaw_range + 1e-9, yaw_step):
        S = np.fft.rfft2(bev(src_xy @ rot2(yaw).T, lo, shape))
        corr = np.fft.irfft2(T * np.conj(S), s=shape)
        k = np.argmax(corr)
        if corr.flat[k] > best[0]:
            i, j = np.unravel_index(k, shape)
            if i > shape[0] // 2: i -= shape[0]
            if j > shape[1] // 2: j -= shape[1]
            best = (corr.flat[k], yaw, np.array([i, j]) * GRID)
    return best[1], best[2]


def icp_2d(src, tgt, yaw, t, iters=40):
    """ICP по x,y (поворот вокруг вертикали + сдвиг), затем сдвиг по z."""
    tree = cKDTree(tgt[:, :2])
    R = rot2(yaw)
    for it in range(iters):
        moved = src[:, :2] @ R.T + t
        thr = max(INLIER, 2.0 * (0.8 ** it))
        d, idx = tree.query(moved, distance_upper_bound=thr)
        m = np.isfinite(d)
        if m.sum() < 30:
            break
        a, b = src[m, :2], tgt[idx[m], :2]
        ca, cb = a.mean(0), b.mean(0)
        U, _, Vt = np.linalg.svd((a - ca).T @ (b - cb))
        Rn = (U @ Vt).T
        if np.linalg.det(Rn) < 0:
            Vt[1] *= -1
            Rn = (U @ Vt).T
        R, t = Rn, cb - ca @ Rn.T
    moved = src[:, :2] @ R.T + t
    d, idx = tree.query(moved, distance_upper_bound=INLIER)
    m = np.isfinite(d)
    fitness = float(m.mean())
    tz = float(np.median(tgt[idx[m], 2] - src[m, 2])) if m.sum() else 0.0
    rmse = float(np.sqrt(np.mean(d[m] ** 2))) if m.sum() else float("inf")
    return math.atan2(R[1, 0], R[0, 0]), t, tz, fitness, rmse


def landmarks(pts):
    """Центры мелких одиночных объектов (знаки, столбы, стойки, углы): по ним сдвиг
    вдоль дороги определяется однозначно, в отличие от стены и периодичных стеллажей."""
    if len(pts) == 0:
        return np.zeros((0, 2))
    lo = pts[:, :2].min(0)
    ij = np.floor((pts[:, :2] - lo) / LM_CELL).astype(np.int64)
    occ = np.zeros(ij.max(0) + 1, dtype=np.int32)
    np.add.at(occ, (ij[:, 0], ij[:, 1]), 1)
    lab, n = ndimage.label(occ > 0, structure=np.ones((3, 3)))
    pl = lab[ij[:, 0], ij[:, 1]]
    out = []
    for k in range(1, n + 1):
        sel = pl == k
        if sel.sum() < LM_MIN_PTS:
            continue
        q = pts[sel]
        ext = q[:, :2].max(0) - q[:, :2].min(0)
        if LM_MIN_EXT <= ext.max() <= LM_MAX_EXT and q[:, 2].max() - q[:, 2].min() >= LM_MIN_HEIGHT:
            out.append(q[:, :2].mean(0))
    return np.array(out) if out else np.zeros((0, 2))


def lm_score(src_lm, tgt_lm, yaw, t):
    """Сколько ориентиров образца после переноса совпали с ориентирами цели (< LM_MATCH м)."""
    if len(src_lm) == 0 or len(tgt_lm) == 0:
        return 0, float("inf")
    moved = src_lm @ rot2(yaw).T + t
    d, _ = cKDTree(tgt_lm).query(moved)
    ok = d < LM_MATCH
    return int(ok.sum()), (float(np.median(d[ok])) if ok.any() else float("inf"))


def ground_level(pts_all):
    """Высота земли вокруг машины (кольцо 6-15 м): лидар закреплён на машине,
    поэтому между кадрами она почти не меняется и даёт надёжный сдвиг по z."""
    r = np.hypot(pts_all[:, 0], pts_all[:, 1])
    ring = pts_all[(r > 6) & (r < 15)]
    return float(np.percentile(ring[:, 2], 10)) if len(ring) > 100 else 0.0


def ground_plane(pts_all):
    """Плоскость земли z = a*x + b*y + c по нижним точкам в клетках 4 м (5-70 м от машины).
    Машина качается (торможение, неровности): наклон лидара между кадрами отличается
    на 1-3°, и на 60 м это 1-3 м по высоте - коробки надо переносить с поправкой."""
    r = np.hypot(pts_all[:, 0], pts_all[:, 1])
    q = pts_all[(r > 5) & (r < 70)]
    ij = np.floor(q[:, :2] / 4).astype(np.int64)
    key = ij[:, 0] * 100003 + ij[:, 1]
    order = np.argsort(key, kind="stable")
    k, z = key[order], q[order, 2]
    starts = np.r_[0, np.nonzero(np.diff(k))[0] + 1]
    zmin = np.minimum.reduceat(z, starts)
    xs, ys = q[order, 0][starts], q[order, 1][starts]
    A = np.c_[xs, ys, np.ones_like(xs)]
    return np.linalg.lstsq(A, zmin, rcond=None)[0]


def plane_z(plane, x, y):
    return float(plane[0] * x + plane[1] * y + plane[2])


def register(src_pts, tgt_pts, boxes=None, long_boxes=(), tz_fixed=None):
    """Возвращает (yaw, t, tz, fitness, rmse, (совпавших ориентиров, всего ориентиров, разброс)).
    tz_fixed - сдвиг по высоте, посчитанный по земле; оценка по совпавшим точкам ненадёжна
    (вертикальные стены и пыль дают случайные пары по z)."""
    src = voxel_down(src_pts, VOXEL)
    tgt = voxel_down(tgt_pts, VOXEL)
    # длинные стены вдоль дороги: по ним хорошо виден поворот и расстояние до стены,
    # но сдвиг ВДОЛЬ стены по ним не определить, а точек в них больше всего - убираем
    for b in long_boxes:
        src = src[~points_in_box(src, b, margin=WALL_MARGIN)]
        tgt = tgt[~points_in_box(tgt, b, margin=WALL_MARGIN)]
    src_lm, tgt_lm = landmarks(src), landmarks(tgt)

    cands = [icp_2d(src, tgt, 0.0, np.zeros(2))]
    yaw0, t0 = coarse_align(src[:, :2], tgt[:, :2])
    cands.append(icp_2d(src, tgt, yaw0, t0))
    # кандидат по ориентирам: перебор сдвигов, при котором совпадает больше всего ориентиров
    if len(src_lm) >= 2 and len(tgt_lm) >= 2:
        yaw_lm = cands[0][0]
        best = None
        for dx in np.arange(-LM_SEARCH, LM_SEARCH + 1e-9, 0.25):
            for dy in np.arange(-LM_SEARCH / 3, LM_SEARCH / 3 + 1e-9, 0.25):
                k, med = lm_score(src_lm, tgt_lm, yaw_lm, np.array([dx, dy]))
                if best is None or (k, -med) > (best[0], -best[1]):
                    best = (k, med, np.array([dx, dy]))
        if best and best[0] >= 2:
            cands.append(icp_2d(src, tgt, yaw_lm, best[2]))

    def rank(c):
        k, med = lm_score(src_lm, tgt_lm, c[0], c[1])
        return (k, round(c[3], 2), -med)
    res = max(cands, key=rank)

    # уточнение по точкам вокруг переносимых коробок
    if boxes and res[3] >= MIN_FITNESS:
        yaw, t, tz, fit, rmse = res
        near_src = np.zeros(len(src), dtype=bool)
        near_tgt = np.zeros(len(tgt), dtype=bool)
        for b in boxes:
            near_src |= points_in_box(src, b, margin=LOCAL_MARGIN)
            near_tgt |= points_in_box(tgt, transform_box(b, yaw, t, tz), margin=2 * LOCAL_MARGIN)
        if near_src.sum() >= 200 and near_tgt.sum() >= 200:
            loc = icp_2d(src[near_src], tgt[near_tgt], yaw, t)
            if loc[3] >= LOCAL_FITNESS and np.linalg.norm(loc[1] - t) <= LOCAL_MAX_SHIFT \
                    and rank(loc)[0] >= rank(res)[0]:
                res = (loc[0], loc[1], loc[2], fit, rmse)
    k, med = lm_score(src_lm, tgt_lm, res[0], res[1])
    if tz_fixed is not None:
        res = (res[0], res[1], float(np.clip(tz_fixed, -0.5, 0.5)), res[3], res[4])
    return (*res, (k, len(src_lm), med))


# ---------- перенос коробок ----------

def transform_box(b, yaw, t, tz):
    nb = json.loads(json.dumps(b))
    p = nb["psr"]["position"]
    xy = rot2(yaw) @ np.array([p["x"], p["y"]]) + t
    p["x"], p["y"], p["z"] = float(xy[0]), float(xy[1]), float(p["z"] + tz)
    r = nb["psr"]["rotation"]
    r["z"] = math.atan2(math.sin(r["z"] + yaw), math.cos(r["z"] + yaw))
    return nb


def snap_small_box(pts, b):
    """Маленькую коробку (столб, стойка) сдвигает к центру точек рядом с ней.
    Ошибка совмещения 10-20 см для стены ничто, а столб шириной 0.5 м она выводит из коробки."""
    s = b["psr"]["scale"]
    if max(s["x"], s["y"]) > SNAP_SIZE:
        return b
    for _ in range(3):
        m = points_in_box(pts, b, margin=SNAP_MARGIN)
        if m.sum() < 5:
            return b
        c = pts[m, :2].mean(0)
        p = b["psr"]["position"]
        if math.hypot(c[0] - p["x"], c[1] - p["y"]) < 0.02:
            break
        p["x"], p["y"] = float(c[0]), float(c[1])
    return b


def parse_range(s, n):
    out = set()
    for part in s.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return sorted(i for i in out if 1 <= i <= n)


def main():
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default="data/car2_15july_SUS_angle_64-83")
    ap.add_argument("--frames", default="64-83", help="кадры для разметки")
    ap.add_argument("--ref", type=int, help="взять коробки именно из этого кадра (иначе - ближайший размеченный из той же серии)")
    ap.add_argument("--candidates", type=int, default=2, help="сколько ближайших образцов пробовать")
    ap.add_argument("--classes", default=",".join(TASK_CLASSES),
                    help="какие классы переносить, через запятую (по умолчанию наборы 2-4 ТЗ)")
    ap.add_argument("--side", choices=["left", "right", "both"], default="both",
                    help="переносить только коробки с одной стороны от машины образца (left = y > 0)")
    ap.add_argument("--dry-run", action="store_true", help="ничего не записывать, только отчёт")
    args = ap.parse_args()

    frames = sorted(os.path.splitext(os.path.basename(f))[0]
                    for f in glob.glob(os.path.join(args.scene, "lidar", "*.bin")))
    n = len(frames)
    stamp = lambda name: float(name.split("__")[-1])
    lidar = lambda name: os.path.join(args.scene, "lidar", name + ".bin")
    label = lambda name: os.path.join(args.scene, "label", name + ".json")

    targets = parse_range(args.frames, n)
    classes = {c.strip() for c in args.classes.split(",") if c.strip()}
    side_ok = {"both": lambda b: True,
               "left": lambda b: b["psr"]["position"]["y"] > 0,
               "right": lambda b: b["psr"]["position"]["y"] < 0}[args.side]
    if args.ref:
        refs = [frames[args.ref - 1]]
    else:
        # образец - любой кадр, где нужные классы уже размечены (куратором или вами)
        refs = [f for f in frames if any(b["obj_type"] in classes for b in load_labels(label(f)))]

    if not args.dry_run:
        dst = os.path.join("backup", "label_before_transfer_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.copytree(os.path.join(args.scene, "label"), dst)
        print("Копия разметки:", dst)

    cache = {}
    def static(name):
        if name not in cache:
            cache[name] = static_points(load_points(lidar(name)), load_labels(label(name)))
        return cache[name]

    for num in targets:
        name = frames[num - 1]
        tgt_labels = load_labels(label(name))
        tgt_all = load_points(lidar(name))
        tgt_static = static(name)

        # ближайшие по времени образцы из той же серии
        cands = [r for r in refs if r != name and (args.ref or abs(stamp(r) - stamp(name)) <= MAX_GAP)]
        cands = sorted(cands, key=lambda r: abs(stamp(r) - stamp(name)))[:args.candidates]
        if not cands:
            if any(b["obj_type"] in classes for b in tgt_labels):
                print(f"#{num}: уже размечен, образцов в серии нет - пропущен")
                continue
            print(f"#{num}: в этой серии нет размеченного кадра -> разметьте его вручную, потом запустите снова")
            continue
        best = None
        for r in cands:
            ref_all = load_labels(label(r))
            ref_boxes = [b for b in ref_all if b["obj_type"] in classes and side_ok(b)]
            long_boxes = [b for b in ref_all if b["obj_type"] in TASK_CLASSES and b["psr"]["scale"]["x"] > LONG_WALL]
            tz_ground = ground_level(tgt_all) - ground_level(load_points(lidar(r)))
            yaw, t, tz, fit, rmse, lm = register(static(r), tgt_static, ref_boxes, long_boxes, tz_ground)
            if best is None or (lm[0], fit) > (best[6][0], best[5]):
                best = (r, yaw, t, tz, rmse, fit, lm)
        ref, yaw, t, tz, rmse, fit, (lm_ok, lm_n, lm_med) = best
        ref_num = frames.index(ref) + 1
        lm_txt = (f"ориентиры {lm_ok}/{lm_n} (разброс {lm_med:.2f} м)" if lm_ok else f"ориентиры 0/{lm_n}")
        head = (f"#{num}: образец #{ref_num}, сдвиг {np.linalg.norm(t):.1f} м, "
                f"поворот {math.degrees(yaw):+.1f}°, совпадение {fit:.0%}, ошибка {rmse:.2f} м, {lm_txt}")
        # низкое совпадение точек при хорошо сошедшихся ориентирах - это пыль и рассеянные
        # точки в кадре, а не ошибка совмещения
        lm_good = lm_ok >= 4 and lm_med <= 0.25
        if (fit < MIN_FITNESS and not (lm_good and fit >= 0.4)) or (lm_n >= 4 and lm_ok == 0):
            print(head + "  -> НЕНАДЁЖНО, кадр пропущен, размечайте вручную")
            continue
        if lm_n >= 4 and lm_ok < LM_MIN_SHARE * lm_n:
            head += "\n      внимание: совпало мало ориентиров - проверьте сдвиг вдоль дороги глазами"

        ref_pts = load_points(lidar(ref))
        plane_ref, plane_tgt = ground_plane(ref_pts), ground_plane(tgt_all)
        existing_ids = {b["obj_id"] for b in tgt_labels}
        added, hidden, kept = [], 0, 0
        by_class = {}
        for b in load_labels(label(ref)):
            if b["obj_type"] not in classes or not side_ok(b):
                continue
            if b["obj_id"] in existing_ids:
                kept += 1          # уже есть в кадре (поставлен вручную) - не трогаем
                continue
            nb = transform_box(b, yaw, t, 0.0)
            # высота: земля под коробкой в новом кадре минус земля под ней в образце
            po, pn = b["psr"]["position"], nb["psr"]["position"]
            pn["z"] = po["z"] + plane_z(plane_tgt, pn["x"], pn["y"]) - plane_z(plane_ref, po["x"], po["y"])
            nb = snap_small_box(tgt_all, nb)
            n_ref = int(points_in_box(ref_pts, b).sum())
            n_tgt = int(points_in_box(tgt_all, nb).sum())
            area = b["psr"]["scale"]["x"] * b["psr"]["scale"]["y"]
            min_abs = MIN_PTS_ABS if area >= 1.0 else MIN_PTS_SMALL   # тонкие линии, стойки: точек мало всегда
            if n_tgt < max(min_abs, MIN_PTS_REL * n_ref):
                hidden += 1        # объект не виден в этом кадре
                continue
            added.append(nb)
            by_class[nb["obj_type"]] = by_class.get(nb["obj_type"], 0) + 1
        detail = ", ".join(f"{c} {k}" for c, k in sorted(by_class.items()))
        print(head + f"\n      добавлено {len(added)}" + (f" ({detail})" if detail else "")
              + f", не видно {hidden}, уже было {kept}")
        if "Dust" in by_class:
            print("      внимание: Dust перенесён как есть - облако пыли меняет форму, проверьте глазами")

        if not args.dry_run and added:
            with open(label(name), "w", encoding="utf-8") as f:
                json.dump(tgt_labels + added, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
