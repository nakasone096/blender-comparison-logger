# -*- coding: utf-8 -*-
"""確認テスト（両群共通）の課題定義・判定・シーン初期化。
判定ロジックはこのファイルだけに置き、アドオン群・動画群で同一の基準を使う。"""
import math
import bpy
import bmesh
from mathutils import Euler

# 課題の順序は両教材の学習順（基本操作→ビュー→編集モード→マテリアル）に合わせている
# 出題範囲は「両教材が実演している操作」だけ（ループカットは動画では実演されないので出さない）
TASKS = [
    {"key": "practice", "title": "練習",
     "text": "立方体を選択してください", "limit_s": 120},
    {"key": "move", "title": "課題1",
     "text": "立方体を、X方向に-2、Z方向に+1.5だけ動かしてください", "limit_s": 180},
    {"key": "rot_scale", "title": "課題2",
     "text": "立方体の高さ（Z方向）だけを3倍に伸ばし、Z軸を中心に45°回してください", "limit_s": 180},
    {"key": "view", "title": "課題3",
     "text": "3Dビューの視点を、回す・横にずらす・拡大縮小する、をすべて行ってください", "limit_s": 180},
    {"key": "pillar", "title": "課題4",
     "text": "立方体の上面から、高さ2の出っ張りを上方向に作ってください", "limit_s": 180},
    {"key": "swap", "title": "課題5",
     "text": "立方体を削除して、代わりに球を1つ追加してください", "limit_s": 180},
    {"key": "round", "title": "課題6",
     "text": "立方体のすべての角（辺）を、2分割以上のなめらかな丸みにしてください", "limit_s": 180},
    {"key": "combo", "title": "総合課題",
     "text": "立方体を2倍の大きさにし、上面から上に出っ張りを作り、"
             "すべての角（辺）を2分割以上のなめらかな丸みにし、赤い色（粗さ0.2以下）を付けてください", "limit_s": 300},
]

TOL_POS = 0.15
TOL_ANGLE_DEG = 5.0
TOL_SCALE = 0.15
ROUND_MIN_VERTS = 32       # 全辺ベベル 2分割 = 32頂点（1分割は24）
COMBO_ROUND_MIN_VERTS = 40  # 出っ張り(12頂点)の全辺ベベル: 1分割は40未満、2分割は40以上（要・実測）
SPHERE_MIN_VERTS = 30       # 球（UV球482／ICO球42）と立方体(8)を区別する
SPHERE_MIN_Z_LEVELS = 5      # 高さ方向の段数（円柱・円錐・トーラスとの区別）
SPHERE_RADIUS_CV = 0.08     # 中心からの距離のばらつき（球はほぼ0、立方体は約0.27）
ROUGHNESS_MAX = 0.2


def wrap_text(text, width=17):
    return [text[i:i + width] for i in range(0, len(text), width)]


# ---------- 幾何ヘルパー ----------

def mesh_coords(obj):
    if obj is None or obj.type != 'MESH':
        return []
    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(obj.data)
        return [tuple(v.co) for v in bm.verts]
    return [tuple(v.co) for v in obj.data.vertices]


def bbox(coords):
    if not coords:
        return None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    zs = [c[2] for c in coords]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def distinct_count(coords, nd=3):
    return len({(round(x, nd), round(y, nd), round(z, nd)) for x, y, z in coords})


def _close(a, b, tol):
    return abs(a - b) <= tol


def _bbox_is_unit_cube(coords, tol=0.05):
    bb = bbox(coords)
    if not bb:
        return False
    (x0, y0, z0), (x1, y1, z1) = bb
    return all(_close(v, e, tol) for v, e in
               ((x0, -1), (y0, -1), (z0, -1), (x1, 1), (y1, 1), (z1, 1)))


def _quat_angle(q1, q2):
    dot = abs(sum(a * b for a, b in zip(q1, q2)))
    return 2.0 * math.acos(min(1.0, dot))


def get_bsdf(material):
    if not material or not material.use_nodes:
        return None
    for node in material.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    return None


def _material_red_and_smooth(obj):
    try:
        mat = obj.active_material
        bsdf = get_bsdf(mat)
        if not bsdf:
            return False
        r, g, b, _a = bsdf.inputs['Base Color'].default_value
        rough = bsdf.inputs['Roughness'].default_value
        return r > 0.4 and g < 0.25 and b < 0.25 and rough <= ROUGHNESS_MAX
    except Exception:
        return False


# ---------- 課題ごとの判定（戻り値: (合格か, 内訳dictまたはNone)） ----------

def judge_practice(selected_any):
    return bool(selected_any), None


def judge_move(obj):
    if obj is None:
        return False, None
    x, y, z = obj.location
    return (_close(x, -2, TOL_POS) and _close(y, 0, TOL_POS) and _close(z, 1.5, TOL_POS)), None


def judge_rot_scale(obj):
    if obj is None:
        return False, None
    sx, sy, sz = obj.scale
    rx, ry, rz = (math.degrees(a) for a in obj.rotation_euler)
    ok = (_close(sx, 1, TOL_SCALE) and _close(sy, 1, TOL_SCALE) and _close(sz, 3, TOL_SCALE)
          and _close(rz, 45, TOL_ANGLE_DEG) and abs(rx) <= 3 and abs(ry) <= 3)
    return ok, None


def judge_view(base, now):
    if not base or not now:
        return False, None
    sub = {
        "rotate": _quat_angle(base["rot"], now["rot"]) > 0.1,
        "pan": math.dist(base["loc"], now["loc"]) > 0.1,
        "zoom": abs(base["dist"] - now["dist"]) > 0.5,
    }
    return all(sub.values()), sub


def judge_pillar(obj):
    coords = mesh_coords(obj)
    if len(coords) < 12 or distinct_count(coords) < 12:
        return False, None
    (x0, y0, z0), (x1, y1, z1) = bbox(coords)
    ring = sum(1 for c in coords if _close(c[2], 1.0, 0.1))
    ok = (_close(z0, -1, 0.1) and _close(z1, 3, 0.25)
          and _close(x0, -1, 0.1) and _close(x1, 1, 0.1)
          and _close(y0, -1, 0.1) and _close(y1, 1, 0.1) and ring >= 4)
    return ok, None


def _is_sphere(obj):
    coords = mesh_coords(obj)
    if distinct_count(coords) < SPHERE_MIN_VERTS:
        return False
    if len({round(c[2], 2) for c in coords}) < SPHERE_MIN_Z_LEVELS:   # 円柱は2段しかない
        return False
    (x0, y0, z0), (x1, y1, z1) = bbox(coords)
    cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
    radii = [math.dist(c, (cx, cy, cz)) for c in coords]
    mean = sum(radii) / len(radii)
    if mean <= 1e-6:
        return False
    var = sum((r - mean) ** 2 for r in radii) / len(radii)
    return math.sqrt(var) / mean < SPHERE_RADIUS_CV


def judge_swap():
    """立方体が無くなり、メッシュが球1つだけになっていれば合格。"""
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    cube_removed = not any(distinct_count(mesh_coords(o)) <= 8 for o in meshes)
    sphere_added = any(_is_sphere(o) for o in meshes)
    sub = {"cube_removed": cube_removed, "sphere_added": sphere_added}
    return (cube_removed and sphere_added and len(meshes) == 1), sub


def _has_bevel_modifier(obj):
    return any(m.type == 'BEVEL' and m.segments >= 2 and m.width >= 0.01 for m in obj.modifiers)


def judge_round(obj):
    if obj is None or obj.type != 'MESH':
        return False, None
    if _has_bevel_modifier(obj):
        return True, None
    coords = mesh_coords(obj)
    ok = distinct_count(coords) >= ROUND_MIN_VERTS and _bbox_is_unit_cube(coords)
    return ok, None


def judge_combo(obj):
    if obj is None or obj.type != 'MESH':
        return False, {"scaled": False, "pillar": False, "round": False, "material": False}
    coords = mesh_coords(obj)
    bb = bbox(coords)
    if not bb:
        return False, {"scaled": False, "pillar": False, "round": False, "material": False}
    (x0, y0, z0), (x1, y1, z1) = bb
    sx, sy, sz = (abs(v) for v in obj.scale)
    dims_x, dims_y, dims_z = (x1 - x0) * sx, (y1 - y0) * sy, (z1 - z0) * sz
    z_levels = len({round(c[2], 2) for c in coords})
    sub = {
        "scaled": _close(dims_x, 4, 0.3) and _close(dims_y, 4, 0.3),
        "pillar": len(coords) >= 12 and (dims_z - dims_x) >= 0.4 and z_levels >= 3,
        "round": _has_bevel_modifier(obj) or distinct_count(coords) >= COMBO_ROUND_MIN_VERTS,
        "material": _material_red_and_smooth(obj),
    }
    return all(sub.values()), sub


def judge(key, obj, selected_any, view_base, view_now):
    if key == "practice":
        return judge_practice(selected_any)
    if key == "move":
        return judge_move(obj)
    if key == "rot_scale":
        return judge_rot_scale(obj)
    if key == "view":
        return judge_view(view_base, view_now)
    if key == "pillar":
        return judge_pillar(obj)
    if key == "swap":
        return judge_swap()
    if key == "round":
        return judge_round(obj)
    if key == "combo":
        return judge_combo(obj)
    return False, None


# ---------- シーン・ビューの初期化 ----------

def find_target(context):
    obj = context.view_layer.objects.active
    if obj is not None and obj.type == 'MESH':
        return obj
    for o in context.scene.objects:
        if o.type == 'MESH':
            return o
    return None


def reset_scene(context, select_cube=True):
    """全オブジェクトを消して、2×2×2の立方体だけを新しく置く（データAPIのみ使用）。"""
    try:
        if context.mode != 'OBJECT' and context.view_layer.objects.active is not None:
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials):
        for b in list(block):
            if b.users == 0:
                block.remove(b)
    mesh = bpy.data.meshes.new("Cube")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("Cube", mesh)
    context.scene.collection.objects.link(obj)
    context.view_layer.update()
    vl = context.view_layer
    for o in vl.objects:
        o.select_set(False)
    if select_cube:
        vl.objects.active = obj
        obj.select_set(True)
    else:
        vl.objects.active = None
    try:
        bpy.ops.ed.undo_push(message="test setup")
    except Exception:
        pass
    return obj


def reset_view(space):
    if not space or not space.region_3d:
        return
    r3d = space.region_3d
    r3d.view_perspective = 'PERSP'
    r3d.view_location = (0.0, 0.0, 0.0)
    r3d.view_distance = 15.0
    r3d.view_rotation = Euler((math.radians(63.6), 0.0, math.radians(46.7)), 'XYZ').to_quaternion()


def view_state(space):
    if not space or not space.region_3d:
        return None
    r3d = space.region_3d
    return {"loc": tuple(r3d.view_location), "rot": tuple(r3d.view_rotation), "dist": r3d.view_distance}
