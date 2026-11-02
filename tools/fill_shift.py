# -*- coding: utf-8 -*-
"""Заполняет соседние кадры серии по размеченному кадру жёстким сдвигом.

Для кадров одной серии с малым разрывом (0.1-1 с) совмещение облаков даёт один сдвиг
и поворот на весь кадр; коробки неподвижных объектов (Infrastructure, Pipes) переносятся
этим сдвигом без уточнения по каждой коробке (уточнение в плотном дворе тянет коробки на
соседние кучи). Пыль (Dust) едет вместе с машиной: копируется как есть, относительно машины.
Коробка не копируется, если в целевом кадре внутри неё почти нет точек.

  python tools/fill_shift.py --ref 81 --targets 82,83            # записать
  python tools/fill_shift.py --ref 81 --targets 82,83 --dry-run  # только отчёт

Номера кадров - порядковые в отсортированном списке label/ (1..83). Коробки, уже имеющиеся
в целевом кадре (набор 1 куратора и всё с тем же ID), не трогаются. Перед записью копия
целевого файла кладётся в backup/.
"""
import argparse, json, math, os, shutil, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import infra_transfer as it  # noqa: E402

MOVING = {"Truck", "Trailer", "Car", "Pedestrian", "ego_truck", "ego_trailer"}
DUST_MIN_PTS = 15      # меньше точек - пыли уже нет
DUST_MIN_REL = 0.05    # или меньше этой доли от точек в образце (пыль быстро рассеивается)


def frame_names(scene):
    d = os.path.join(scene, "label")
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))


def exclude_moving(pts, labels):
    # без земли, без подвижных объектов и без пыли (static_points убирает всё, что не Infrastructure/Pipes)
    pts = it.static_points(pts, labels)
    keep = np.ones(len(pts), dtype=bool)
    for b in labels:
        if b.get("obj_type") in MOVING:
            keep &= ~it.points_in_box(pts, b, margin=0.5)
    # зона самой машины (кабина + прицеп), на случай если набора 1 нет
    keep &= ~((pts[:, 0] > -14) & (pts[:, 0] < 4) & (np.abs(pts[:, 1]) < 2.0))
    return pts[keep]


def post_offsets(pts, boxes):
    """Для узких коробок (столбы, стойки): смещение центра точек от центра коробки в целевом кадре."""
    out = []
    for b in boxes:
        s = b["psr"]["scale"]
        if max(s["x"], s["y"]) > 1.5 or b["obj_type"] not in it.STATIC_CLASSES:
            continue
        m = it.points_in_box(pts, b, margin=0.15)
        if m.sum() < 8:
            continue
        c = pts[m][:, :2].mean(axis=0)
        out.append((b["obj_id"], float(c[0] - b["psr"]["position"]["x"]), float(c[1] - b["psr"]["position"]["y"]), int(m.sum())))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="data/car2_15july_SUS_angle_64-83")
    ap.add_argument("--ref", type=int, required=True, help="размеченный кадр (порядковый номер)")
    ap.add_argument("--targets", required=True, help="кадры для заполнения, через запятую: 82,83")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    names = frame_names(a.scene)
    ref_name = names[a.ref - 1]
    ref_labels = it.load_labels(os.path.join(a.scene, "label", ref_name + ".json"))
    ref_pts = it.load_points(os.path.join(a.scene, "lidar", ref_name + ".bin"))
    ref_task = [b for b in ref_labels if b.get("obj_type") in it.TASK_CLASSES]
    ref_static = [b for b in ref_task if b["obj_type"] in it.STATIC_CLASSES]
    long_boxes = [b for b in ref_static if max(b["psr"]["scale"]["x"], b["psr"]["scale"]["y"]) > it.LONG_WALL]
    src = exclude_moving(ref_pts, ref_labels)
    src_plane = it.ground_plane(ref_pts)
    print(f"образец {a.ref}: {ref_name}  задачных коробок {len(ref_task)} "
          f"(Infrastructure {sum(b['obj_type']=='Infrastructure' for b in ref_task)}, "
          f"Pipes {sum(b['obj_type']=='Pipes' for b in ref_task)}, Dust {sum(b['obj_type']=='Dust' for b in ref_task)}), "
          f"длинных стен {len(long_boxes)}")

    for ti in [int(x) for x in a.targets.split(",")]:
        tname = names[ti - 1]
        tpath = os.path.join(a.scene, "label", tname + ".json")
        t_labels = it.load_labels(tpath)
        t_pts = it.load_points(os.path.join(a.scene, "lidar", tname + ".bin"))
        tgt = exclude_moving(t_pts, t_labels)
        tgt_plane = it.ground_plane(t_pts)
        tz0 = it.ground_level(t_pts) - it.ground_level(ref_pts)

        yaw, t, tz, fit, rmse, (lm_ok, lm_all, lm_med) = it.register(src, tgt, boxes=None, long_boxes=long_boxes, tz_fixed=tz0)
        print(f"\nкадр {ti}: {tname}")
        print(f"  совмещение: dx {t[0]:+.2f} dy {t[1]:+.2f} м, поворот {math.degrees(yaw):+.2f}°, dz {tz:+.2f}; "
              f"fitness {fit:.2f}, rmse {rmse:.2f} м, ориентиров {lm_ok}/{lm_all} (разброс {lm_med:.2f} м)")
        if fit < it.MIN_FITNESS:
            print("  !! совмещение ненадёжно, кадр пропущен")
            continue

        existing = {str(b.get("obj_id")) for b in t_labels}
        new_boxes, dropped, dust_how = [], [], []
        for b in ref_task:
            if str(b["obj_id"]) in existing:
                continue
            ref_cnt = int(it.points_in_box(ref_pts, b).sum())
            if b["obj_type"] == "Dust":
                # пыль у колёс едет с машиной, пыль поодаль остаётся на месте: смотрим, где точки
                ego = json.loads(json.dumps(b))
                world = it.transform_box(b, yaw, t, 0.0)
                c_ego = int(it.points_in_box(t_pts, ego).sum())
                c_world = int(it.points_in_box(t_pts, world).sum())
                nb, cnt, how = (ego, c_ego, "с машиной") if c_ego >= c_world else (world, c_world, "на месте")
                ok = cnt >= DUST_MIN_PTS and cnt >= DUST_MIN_REL * ref_cnt
                if ok:
                    dust_how.append(f"{b['obj_id']} {how} ({cnt} т.)")
            else:
                nb = it.transform_box(b, yaw, t, 0.0)
                # поправка высоты по наклону земли помогает далёким низким объектам, но тонкую трубу
                # на высоте может увести мимо точек: берём вариант, где точек внутри больше
                zc = json.loads(json.dumps(nb))
                p0, pz = b["psr"]["position"], zc["psr"]["position"]
                pz["z"] += it.plane_z(tgt_plane, pz["x"], pz["y"]) - it.plane_z(src_plane, p0["x"], p0["y"])
                c_plain, c_corr = int(it.points_in_box(t_pts, nb).sum()), int(it.points_in_box(t_pts, zc).sum())
                if c_corr > c_plain:
                    nb, cnt = zc, c_corr
                else:
                    cnt = c_plain
                s = b["psr"]["scale"]
                need = it.MIN_PTS_SMALL if s["x"] * s["y"] < 1.0 else it.MIN_PTS_ABS
                ok = cnt >= need and cnt >= it.MIN_PTS_REL * ref_cnt
            if ok:
                new_boxes.append(nb)
            else:
                dropped.append((b["obj_type"], b["obj_id"], ref_cnt, cnt))

        offs = post_offsets(t_pts, [b for b in new_boxes if b["obj_type"] in it.STATIC_CLASSES])
        if offs:
            dx = np.median([o[1] for o in offs]); dy = np.median([o[2] for o in offs])
            print(f"  проверка по {len(offs)} столбам/стойкам: медианное смещение точек от центра коробки "
                  f"dx {dx:+.2f} dy {dy:+.2f} м" + ("  !! больше 0.3 м - проверьте" if max(abs(dx), abs(dy)) > 0.3 else ""))
        print(f"  переносится {len(new_boxes)} коробок, пропущено {len(dropped)} (нет точек):")
        for d in dropped:
            print(f"    - {d[0]} {d[1]}: точек в образце {d[2]}, в кадре {d[3]}")
        if dust_how:
            print("  пыль: " + "; ".join(dust_how))
        kept = [b for b in t_labels]
        print(f"  в кадре остаются свои {len(kept)} коробок: " + ", ".join(f"{b['obj_type']} {b.get('obj_id')}" for b in kept))

        if a.dry_run:
            continue
        os.makedirs("backup", exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        if os.path.exists(tpath):
            shutil.copy2(tpath, os.path.join("backup", f"label_{tname[-18:]}_before_fill_{stamp}.json"))
        with open(tpath, "w", encoding="utf-8") as f:
            json.dump(kept + new_boxes, f, ensure_ascii=False, indent=2)
        print(f"  записано: {len(kept) + len(new_boxes)} коробок -> {tpath}")


if __name__ == "__main__":
    main()
