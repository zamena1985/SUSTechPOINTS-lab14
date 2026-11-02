"""Объединяет группы коробок одного кадра в одну коробку каждая.

Типичный случай: опора эстакады размечена тремя коробками (две ноги + перекладина),
куратор просит одну коробку на опору.

Пример:
  python tools/merge_boxes.py --frame 75 --groups "1154,1155,1147;1211,1020,1138"
  python tools/merge_boxes.py --frame 75 --groups "..." --dry-run      # только показать

Новая коробка: наименьший прямоугольник, накрывающий все коробки группы, повёрнутый
на yaw первой коробки группы (наклоны x/y обнуляются). Класс берётся от первой коробки,
ID остаётся наименьший в группе (или --keep-first). Перед записью делается копия
файла в backup/.
"""
import argparse, json, math, os, shutil, sys, time

def corners(o):
    p, s, r = o["psr"]["position"], o["psr"]["scale"], o["psr"]["rotation"]
    yaw = r["z"]; c, sn = math.cos(yaw), math.sin(yaw)
    out = []
    for dx in (-0.5, 0.5):
        for dy in (-0.5, 0.5):
            for dz in (-0.5, 0.5):
                lx, ly, lz = dx * s["x"], dy * s["y"], dz * s["z"]
                out.append((p["x"] + lx * c - ly * sn, p["y"] + lx * sn + ly * c, p["z"] + lz))
    return out

def merged_box(group, keep_first):
    first = group[0]
    yaw = first["psr"]["rotation"]["z"]
    c, sn = math.cos(-yaw), math.sin(-yaw)
    pts = [pt for o in group for pt in corners(o)]
    loc = [(x * c - y * sn, x * sn + y * c, z) for x, y, z in pts]
    xs, ys, zs = zip(*loc)
    cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    gx = cx * math.cos(yaw) - cy * math.sin(yaw)
    gy = cx * math.sin(yaw) + cy * math.cos(yaw)
    ids = [str(o.get("obj_id", "")) for o in group]
    if keep_first:
        keep = ids[0]
    else:
        nums = [int(i) for i in ids if i.isdigit()]
        keep = str(min(nums)) if nums else ids[0]
    return {
        "obj_id": keep,
        "obj_type": first["obj_type"],
        "psr": {
            "position": {"x": round(gx, 4), "y": round(gy, 4), "z": round(cz, 4)},
            "scale": {"x": round(max(xs) - min(xs), 4), "y": round(max(ys) - min(ys), 4), "z": round(max(zs) - min(zs), 4)},
            "rotation": {"x": 0, "y": 0, "z": yaw},
        },
    }

def resolve_frame(scene, frame):
    if frame.endswith(".json") or "__" in frame:
        return frame if frame.endswith(".json") else frame + ".json"
    names = sorted(os.listdir(os.path.join(scene, "lidar")))
    return os.path.splitext(names[int(frame) - 1])[0] + ".json"

def fmt(o):
    p, s = o["psr"]["position"], o["psr"]["scale"]
    return f"{o['obj_type']} {o['obj_id']:>5} pos ({p['x']:6.1f},{p['y']:6.1f},{p['z']:5.1f}) size {s['x']:.2f}x{s['y']:.2f}x{s['z']:.2f}"

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default="data/car2_15july_SUS_angle_64-83")
    ap.add_argument("--frame", required=True, help="номер кадра по порядку (как в checker) или имя файла")
    ap.add_argument("--groups", required=True, help='группы ID: "1,2,3;4,5,6"')
    ap.add_argument("--keep-first", action="store_true", help="оставить ID первой коробки группы, а не наименьший")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    fname = resolve_frame(a.scene, a.frame)
    path = os.path.join(a.scene, "label", fname)
    raw = json.load(open(path, encoding="utf-8"))
    objs = raw if isinstance(raw, list) else raw["objs"]
    by_id = {}
    for o in objs:
        by_id.setdefault(str(o.get("obj_id", "")), []).append(o)
    groups = [[i.strip() for i in g.split(",") if i.strip()] for g in a.groups.split(";") if g.strip()]
    used, new_objs, remove = set(), [], set()
    print(f"Кадр {a.frame}: {fname}")
    for g in groups:
        missing = [i for i in g if i not in by_id]
        dup = [i for i in g if len(by_id.get(i, [])) > 1]
        if missing or dup:
            sys.exit(f"ОШИБКА: нет ID {missing}, повторяющиеся ID {dup}")
        if used & set(g):
            sys.exit(f"ОШИБКА: ID {used & set(g)} встречается в двух группах")
        used |= set(g)
        members = [by_id[i][0] for i in g]
        nb = merged_box(members, a.keep_first)
        print("  группа:")
        for m in members:
            print("     - " + fmt(m))
        print("     = " + fmt(nb))
        new_objs.append(nb)
        remove |= {id(m) for m in members}
    if a.dry_run:
        print("dry-run: файл не изменён")
        return
    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs("backup", exist_ok=True)
    bak = os.path.join("backup", f"label{a.frame}_before_merge_{stamp}.json")
    shutil.copy2(path, bak)
    kept = [o for o in objs if id(o) not in remove] + new_objs
    if isinstance(raw, list):
        raw = kept
    else:
        raw["objs"] = kept
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    print(f"Записано: {len(objs)} -> {len(kept)} коробок. Копия до изменения: {bak}")
    print("В программе нажмите F5 на этом кадре, прежде чем что-то править или сохранять.")

if __name__ == "__main__":
    main()
