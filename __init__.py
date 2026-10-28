# -*- coding: utf-8 -*-
bl_info = {
    "name": "3DCG Learning Logger (Comparison Group)",
    "blender": (4, 2, 0),
    "version": (0, 2, 0),
    "author": "Daichi",
    "description": "Comparison-study tool: silent learning-phase logger (video group) and a "
                    "closed-book test mode shared by both groups. No hints, no chapter UI.",
    "category": "Education",
    "support": "COMMUNITY",
}

import bpy
import bmesh
import math
import time
import json
import os
import csv
import subprocess
import sys
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import (
    IntProperty,
    BoolProperty,
    FloatVectorProperty,
    FloatProperty,
    StringProperty,
    EnumProperty,
)
from . import test_tasks

# =====================================================
# この比較実験で検出する6カテゴリ
# (現行チュートリアル版 Ch1〜Ch6 の操作カテゴリに対応)
# =====================================================

CATEGORY_LABELS = {
    1: "基本操作（移動・回転・拡大縮小）",
    2: "ビュー操作（回転・ズーム）",
    3: "モデリング（編集モード＋ループカット/押し出し）",
    4: "モディファイア追加",
    5: "スカルプト変形",
    6: "マテリアル作成（Roughness調整）",
}

# しきい値（現行チュートリアル版の判定条件に合わせている）
MOVE_THRESHOLD = 0.05
ROTATE_THRESHOLD_RAD = 0.0524  # 約3度
SCALE_THRESHOLD = 0.02
VIEW_LOC_THRESHOLD = 0.1
VIEW_ROT_THRESHOLD = 0.05
VIEW_DIST_THRESHOLD = 0.5
EDGE_COUNT_INCREASE_THRESHOLD = 2
SCULPT_MOVED_VERTS_THRESHOLD = 5
SCULPT_TOTAL_DEFORM_THRESHOLD = 0.05
ROUGHNESS_DONE_THRESHOLD = 0.2


# =====================================================
# LOGGER MANAGER (staticな補助関数群)
# =====================================================

# Blender の FloatProperty は 32bit 浮動小数点のため、UNIX時間（約17億）をそのまま保存すると
# 最大±64秒ずれる。経過時間の計算に使う時刻は、起動時からの相対秒（_rel）で保存する。
_T0 = time.time()


class LoggerManager:
    @staticmethod
    def _now():
        return time.time()

    @staticmethod
    def _rel():
        return time.time() - _T0

    @staticmethod
    def vec_dist(a, b):
        n = min(len(a), len(b))
        return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)))

    @staticmethod
    def default_log_dir() -> str:
        if os.name == "nt":
            return r"C:\temp\comparison_logs\\"
        return os.path.join("~", "comparison_logs") + os.sep

    @staticmethod
    def ensure_dir_exists(path: str) -> str:
        abs_path = bpy.path.abspath(path)
        os.makedirs(abs_path, exist_ok=True)
        return abs_path

    @staticmethod
    def open_folder_in_os(path: str):
        abs_path = LoggerManager.ensure_dir_exists(path)
        if os.name == "nt":
            # os.startfile() はBlender埋め込みPythonから呼ぶとCOM状態の衝突で
            # クラッシュすることがあるため、explorer.exeをプロセス起動する方式にする
            subprocess.Popen(["explorer", abs_path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", abs_path])
        else:
            subprocess.Popen(["xdg-open", abs_path])

    @staticmethod
    def _safe_participant_id(pid: str) -> str:
        pid = (pid or "").strip()
        if not pid:
            return ""
        allowed = []
        for ch in pid:
            if ch.isalnum() or ch in ("-", "_"):
                allowed.append(ch)
            else:
                allowed.append("_")
        return "".join(allowed)

    @staticmethod
    def group_tag(props) -> str:
        return "addon" if props.group == 'ADDON' else "video"

    @staticmethod
    def group_label(props) -> str:
        return "addon" if props.group == 'ADDON' else "video_textbook"

    @staticmethod
    def ensure_participant_log_file(context, kind="learn") -> bool:
        """kind='learn'（学習中ログ）または 'test'（確認テストのログ）。群タグをファイル名に入れる。"""
        props = context.scene.logger_props
        pid = LoggerManager._safe_participant_id(props.participant_id)
        path_attr = "test_log_path" if kind == "test" else "participant_log_path"

        if not pid:
            props.participant_log_error = "参加者IDが未入力です"
            return False

        if not (props.log_dir or "").strip():
            props.log_dir = LoggerManager.default_log_dir()

        try:
            dir_abs = LoggerManager.ensure_dir_exists(props.log_dir)
        except Exception as e:
            props.participant_log_error = f"ログ保存フォルダ作成に失敗: {e}"
            return False

        current = getattr(props, path_attr)
        if current:
            try:
                existing = bpy.path.abspath(current)
                if os.path.isfile(existing):
                    props.participant_log_error = ""
                    return True
            except Exception:
                pass

        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(LoggerManager._now()))
        tag = LoggerManager.group_tag(props)
        name = f"{pid}_{tag}_test_{ts}.jsonl" if kind == "test" else f"{pid}_{tag}_{ts}.jsonl"
        log_path = os.path.join(dir_abs, name)

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "t": LoggerManager._now(),
                    "participant_id": pid,
                    "event": "session_start",
                    "kind": kind,
                    "group": LoggerManager.group_label(props),
                    "blender_version": ".".join(map(str, bpy.app.version)),
                }, ensure_ascii=False) + "\n")

            setattr(props, path_attr, log_path)
            props.participant_log_error = ""
            return True
        except Exception as e:
            props.participant_log_error = f"ログファイル作成に失敗: {type(e).__name__}: {e}"
            return False

    @staticmethod
    def append_event(context, event: dict, kind="learn"):
        props = context.scene.logger_props
        if not props.enable_logging:
            return
        if not LoggerManager.ensure_participant_log_file(context, kind):
            return
        path = props.test_log_path if kind == "test" else props.participant_log_path
        try:
            with open(bpy.path.abspath(path), "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            props.participant_log_error = f"ログ書き込みに失敗: {type(e).__name__}: {e}"

    @staticmethod
    def log_category_detected(context, category: int, extra: dict = None):
        props = context.scene.logger_props
        pid = LoggerManager._safe_participant_id(props.participant_id)
        elapsed = round(LoggerManager._rel() - props.session_start_time, 3) if props.session_start_time > 0 else None
        event = {
            "t": LoggerManager._now(),
            "participant_id": pid,
            "event": "category_detected",
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, ""),
            "elapsed_s": elapsed,
            "undo_count_so_far": int(props.undo_count),
        }
        if extra:
            event.update(extra)
        LoggerManager.append_event(context, event)

    @staticmethod
    def get_view3d_space(context):
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        return space
        return None

    @staticmethod
    def get_active_material(obj):
        if not obj or not obj.material_slots:
            return None
        return obj.active_material

    @staticmethod
    def get_principled_bsdf(material):
        if not material or not material.use_nodes:
            return None
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                return node
        return None

    @staticmethod
    def total_mesh_vert_edge_counts(context):
        """全メッシュオブジェクトの頂点数・辺数の合計。編集モード中はBMeshからライブで取得する。"""
        total_v = 0
        total_e = 0
        active = context.active_object
        in_edit = context.mode == 'EDIT_MESH'
        for obj in bpy.data.objects:
            if obj.type != 'MESH':
                continue
            if in_edit and obj is active:
                try:
                    bm = bmesh.from_edit_mesh(obj.data)
                    total_v += len(bm.verts)
                    total_e += len(bm.edges)
                    continue
                except Exception:
                    pass
            total_v += len(obj.data.vertices)
            total_e += len(obj.data.edges)
        return total_v, total_e

    @staticmethod
    def total_modifier_count():
        return sum(len(obj.modifiers) for obj in bpy.data.objects if obj.type == 'MESH')

    @staticmethod
    def any_material_roughness_done():
        for obj in bpy.data.objects:
            if obj.type != 'MESH':
                continue
            mat = LoggerManager.get_active_material(obj)
            bsdf = LoggerManager.get_principled_bsdf(mat) if mat else None
            if not bsdf:
                continue
            try:
                roughness = bsdf.inputs['Roughness'].default_value
            except Exception:
                continue
            if roughness <= ROUGHNESS_DONE_THRESHOLD:
                return True
        return False


# =====================================================
# PROPERTIES
# =====================================================

class LOGGER_PG_Properties(PropertyGroup):
    participant_id: StringProperty(name="参加者ID", default="")
    log_dir: StringProperty(
        name="ログ保存フォルダ",
        subtype='DIR_PATH',
        default="",
    )
    participant_log_path: StringProperty(default="")
    participant_log_error: StringProperty(default="")

    group: EnumProperty(
        name="群",
        items=[
            ('VIDEO', "動画版", "既存学習方法（動画）群"),
            ('ADDON', "アドオン版", "現行チュートリアルアドオン群"),
        ],
        default='VIDEO',
    )

    # 確認テスト（両群共通）
    test_log_path: StringProperty(default="")
    test_error: StringProperty(default="")
    test_active: BoolProperty(default=False)
    test_state: StringProperty(default="IDLE")      # IDLE / RUN / DONE / END
    test_result: StringProperty(default="")         # completed / timeout / skipped
    test_index: IntProperty(default=0, min=0)
    test_task_start: FloatProperty(default=0.0)
    test_task_elapsed: FloatProperty(default=0.0)
    test_started_at: FloatProperty(default=0.0)
    test_undo_count: IntProperty(default=0, min=0)
    test_reset_count: IntProperty(default=0, min=0)
    test_completed_count: IntProperty(default=0, min=0)
    test_view_base_loc: FloatVectorProperty(size=3)
    test_view_base_rot: FloatVectorProperty(size=4)
    test_view_base_dist: FloatProperty(default=15.0)

    enable_logging: BoolProperty(name="ログ記録を有効化", default=True)
    monitoring_active: BoolProperty(default=False)
    session_started: BoolProperty(default=False)
    session_start_time: FloatProperty(default=0.0)
    undo_count: IntProperty(default=0, min=0)

    # 検出済みフラグ（参加者には表示しない。内部トラッキング専用）
    cat1_move_done: BoolProperty(default=False)
    cat1_rotate_done: BoolProperty(default=False)
    cat1_scale_done: BoolProperty(default=False)
    cat1_logged: BoolProperty(default=False)
    cat2_logged: BoolProperty(default=False)
    edit_mode_seen: BoolProperty(default=False)
    cat3_logged: BoolProperty(default=False)
    cat4_logged: BoolProperty(default=False)
    sculpt_mode_seen: BoolProperty(default=False)
    cat5_logged: BoolProperty(default=False)
    cat6_logged: BoolProperty(default=False)

    # ベースライン（セッション開始時にスナップショット）
    baseline_view_location: FloatVectorProperty(size=3)
    baseline_view_rotation: FloatVectorProperty(size=4)
    baseline_view_distance: FloatProperty(default=0.0)
    baseline_vert_count: IntProperty(default=0)
    baseline_edge_count: IntProperty(default=0)
    baseline_modifier_count: IntProperty(default=0)


# =====================================================
# OPERATORS: フォルダ設定
# =====================================================

class LOGGER_OT_set_default_log_dir(Operator):
    bl_idname = "logger.set_default_log_dir"
    bl_label = "既定フォルダに設定"
    bl_description = "ログ保存フォルダを既定値に戻し、フォルダも作成します"

    def execute(self, context):
        props = context.scene.logger_props
        props.log_dir = LoggerManager.default_log_dir()
        try:
            LoggerManager.ensure_dir_exists(props.log_dir)
        except Exception as e:
            self.report({'ERROR'}, f"フォルダ作成に失敗: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"設定: {bpy.path.abspath(props.log_dir)}")
        return {'FINISHED'}


class LOGGER_OT_open_log_folder(Operator):
    bl_idname = "logger.open_log_folder"
    bl_label = "ログフォルダを開く"
    bl_description = "OSのファイルエクスプローラでログ保存フォルダを開きます"

    def execute(self, context):
        props = context.scene.logger_props
        try:
            LoggerManager.open_folder_in_os(props.log_dir or LoggerManager.default_log_dir())
        except Exception as e:
            self.report({'ERROR'}, f"フォルダを開けません: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


# =====================================================
# OPERATORS: セッション開始/終了
# =====================================================

class LOGGER_OT_start_session(Operator):
    bl_idname = "logger.start_session"
    bl_label = "計測開始"
    bl_description = "参加者の操作をバックグラウンドで記録します（進捗表示は行いません）"

    def execute(self, context):
        props = context.scene.logger_props

        if not LoggerManager.ensure_participant_log_file(context):
            self.report({'ERROR'}, props.participant_log_error or "ログファイルを作成できません")
            return {'CANCELLED'}

        # フラグ・カウンタをリセット
        props.undo_count = 0
        props.cat1_move_done = False
        props.cat1_rotate_done = False
        props.cat1_scale_done = False
        props.cat1_logged = False
        props.cat2_logged = False
        props.edit_mode_seen = False
        props.cat3_logged = False
        props.cat4_logged = False
        props.sculpt_mode_seen = False
        props.cat5_logged = False
        props.cat6_logged = False

        # ベースライン取得
        space = LoggerManager.get_view3d_space(context)
        if space and space.region_3d:
            r3d = space.region_3d
            props.baseline_view_location = tuple(r3d.view_location)
            props.baseline_view_rotation = tuple(r3d.view_rotation)
            props.baseline_view_distance = r3d.view_distance

        v, e = LoggerManager.total_mesh_vert_edge_counts(context)
        props.baseline_vert_count = v
        props.baseline_edge_count = e
        props.baseline_modifier_count = LoggerManager.total_modifier_count()

        props.session_start_time = LoggerManager._rel()
        props.session_started = True
        props.monitoring_active = True

        LoggerManager.append_event(context, {
            "t": LoggerManager._now(),
            "participant_id": LoggerManager._safe_participant_id(props.participant_id),
            "event": "measurement_start",
            "group": LoggerManager.group_label(props),
        })

        bpy.ops.wm.logger_monitoring()
        self.report({'INFO'}, "計測を開始しました")
        return {'FINISHED'}


class LOGGER_OT_stop_session(Operator):
    bl_idname = "logger.stop_session"
    bl_label = "計測終了"
    bl_description = "計測を終了し、セッション終了イベントを記録します"

    def execute(self, context):
        props = context.scene.logger_props
        elapsed = round(LoggerManager._rel() - props.session_start_time, 3) if props.session_start_time > 0 else None

        LoggerManager.append_event(context, {
            "t": LoggerManager._now(),
            "participant_id": LoggerManager._safe_participant_id(props.participant_id),
            "event": "measurement_end",
            "group": LoggerManager.group_label(props),
            "total_elapsed_s": elapsed,
            "undo_count_total": int(props.undo_count),
            "cat1_done": bool(props.cat1_logged),
            "cat2_done": bool(props.cat2_logged),
            "cat3_done": bool(props.cat3_logged),
            "cat4_done": bool(props.cat4_logged),
            "cat5_done": bool(props.cat5_logged),
            "cat6_done": bool(props.cat6_logged),
        })

        props.monitoring_active = False
        props.session_started = False
        self.report({'INFO'}, "計測を終了しました")
        return {'FINISHED'}


# =====================================================
# OPERATOR: バックグラウンド監視（モーダルタイマー）
# 参加者には何も表示しない（サイレント計測）
# =====================================================

class LOGGER_OT_monitoring(Operator):
    bl_idname = "wm.logger_monitoring"
    bl_label = "Comparison Logger Monitoring"
    _timer = None
    _last_check = 0.0
    _running = False

    def _check_categories(self, context):
        props = context.scene.logger_props
        obj = context.active_object

        # --- カテゴリ1: 基本操作（移動・回転・拡大縮小） ---
        if not props.cat1_logged and obj:
            key = obj.name
            if key not in self._object_baselines:
                self._object_baselines[key] = (
                    tuple(obj.location),
                    tuple(obj.rotation_euler),
                    tuple(obj.scale),
                )
            else:
                base_loc, base_rot, base_scale = self._object_baselines[key]
                if not props.cat1_move_done:
                    if LoggerManager.vec_dist(tuple(obj.location), base_loc) > MOVE_THRESHOLD:
                        props.cat1_move_done = True
                if not props.cat1_rotate_done:
                    rot_diff = max(abs(obj.rotation_euler[i] - base_rot[i]) for i in range(3))
                    if rot_diff > ROTATE_THRESHOLD_RAD:
                        props.cat1_rotate_done = True
                if not props.cat1_scale_done:
                    scale_diff = max(abs(obj.scale[i] - base_scale[i]) for i in range(3))
                    if scale_diff > SCALE_THRESHOLD:
                        props.cat1_scale_done = True

            if props.cat1_move_done and props.cat1_rotate_done and props.cat1_scale_done:
                props.cat1_logged = True
                LoggerManager.log_category_detected(context, 1)

        # --- カテゴリ2: ビュー操作 ---
        if not props.cat2_logged:
            space = LoggerManager.get_view3d_space(context)
            if space and space.region_3d:
                r3d = space.region_3d
                loc_diff = LoggerManager.vec_dist(tuple(r3d.view_location), tuple(props.baseline_view_location))
                rot_diff = LoggerManager.vec_dist(tuple(r3d.view_rotation), tuple(props.baseline_view_rotation))
                dist_diff = abs(r3d.view_distance - props.baseline_view_distance)
                moved = loc_diff > VIEW_LOC_THRESHOLD or rot_diff > VIEW_ROT_THRESHOLD
                zoomed = dist_diff > VIEW_DIST_THRESHOLD
                if moved and zoomed:
                    props.cat2_logged = True
                    LoggerManager.log_category_detected(context, 2)

        # --- カテゴリ3: モデリング（編集モード＋ジオメトリ増加） ---
        if context.mode == 'EDIT_MESH':
            props.edit_mode_seen = True
        if not props.cat3_logged and props.edit_mode_seen:
            _, cur_edge = LoggerManager.total_mesh_vert_edge_counts(context)
            if cur_edge > props.baseline_edge_count + EDGE_COUNT_INCREASE_THRESHOLD:
                props.cat3_logged = True
                LoggerManager.log_category_detected(context, 3)

        # --- カテゴリ4: モディファイア追加 ---
        if not props.cat4_logged:
            cur_mod_count = LoggerManager.total_modifier_count()
            if cur_mod_count > props.baseline_modifier_count:
                props.cat4_logged = True
                LoggerManager.log_category_detected(context, 4)

        # --- カテゴリ5: スカルプト変形 ---
        if context.mode == 'SCULPT':
            props.sculpt_mode_seen = True
            if not props.cat5_logged and obj and obj.type == 'MESH':
                if obj.name not in self._sculpt_baselines:
                    try:
                        self._sculpt_baselines[obj.name] = [v.co.copy() for v in obj.data.vertices]
                    except Exception:
                        pass
                else:
                    baseline_verts = self._sculpt_baselines[obj.name]
                    moved = 0
                    total = 0.0
                    try:
                        compare_count = min(len(obj.data.vertices), len(baseline_verts))
                        for i in range(compare_count):
                            dist = (obj.data.vertices[i].co - baseline_verts[i]).length
                            if dist > 0.001:
                                moved += 1
                                total += dist
                    except Exception:
                        pass
                    if moved > SCULPT_MOVED_VERTS_THRESHOLD and total > SCULPT_TOTAL_DEFORM_THRESHOLD:
                        props.cat5_logged = True
                        LoggerManager.log_category_detected(context, 5)

        # --- カテゴリ6: マテリアル作成（Roughness調整） ---
        if not props.cat6_logged:
            if LoggerManager.any_material_roughness_done():
                props.cat6_logged = True
                LoggerManager.log_category_detected(context, 6)

    def modal(self, context, event):
        if event.type == 'TIMER':
            try:
                props = context.scene.logger_props
                if not props.monitoring_active:
                    wm = context.window_manager
                    if self._timer:
                        wm.event_timer_remove(self._timer)
                    LOGGER_OT_monitoring._running = False
                    return {'FINISHED'}

                current_time = time.time()
                if current_time - self._last_check > 0.2:
                    self._check_categories(context)
                    self._last_check = current_time
            except Exception:
                pass
        return {'PASS_THROUGH'}

    def execute(self, context):
        if LOGGER_OT_monitoring._running:
            return {'CANCELLED'}
        self._object_baselines = {}
        self._sculpt_baselines = {}
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.2, window=context.window)
        self._last_check = time.time()
        LOGGER_OT_monitoring._running = True
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}


# =====================================================
# 確認テスト（両群共通）
# 課題の表示・判定・時間計測。課題定義と判定ロジックは test_tasks.py だけにある。
# =====================================================

def _test_log(context, event_type, **fields):
    props = context.scene.logger_props
    ev = {
        "t": LoggerManager._now(),
        "participant_id": LoggerManager._safe_participant_id(props.participant_id),
        "event": event_type,
        "group": LoggerManager.group_label(props),
    }
    ev.update(fields)
    LoggerManager.append_event(context, ev, kind="test")


def _view_base(context):
    space = LoggerManager.get_view3d_space(context)
    return {
        "loc": tuple(context.scene.logger_props.test_view_base_loc),
        "rot": tuple(context.scene.logger_props.test_view_base_rot),
        "dist": context.scene.logger_props.test_view_base_dist,
    }, test_tasks.view_state(space)


def _capture_view_base(context):
    props = context.scene.logger_props
    space = LoggerManager.get_view3d_space(context)
    test_tasks.reset_view(space)
    st = test_tasks.view_state(space)
    if st:
        props.test_view_base_loc = st["loc"]
        props.test_view_base_rot = st["rot"]
        props.test_view_base_dist = st["dist"]


def _judge_now(context):
    props = context.scene.logger_props
    key = test_tasks.TASKS[props.test_index]["key"]
    obj = test_tasks.find_target(context)
    selected_any = any(o.select_get() for o in context.view_layer.objects)
    base, now = _view_base(context)
    return test_tasks.judge(key, obj, selected_any, base, now)


def _begin_task(context, idx):
    props = context.scene.logger_props
    task = test_tasks.TASKS[idx]
    props.test_index = idx
    props.test_state = "RUN"
    props.test_result = ""
    props.test_reset_count = 0
    props.test_undo_count = 0
    test_tasks.reset_scene(context, select_cube=(task["key"] != "practice"))
    _capture_view_base(context)
    props.test_task_start = LoggerManager._rel()
    _test_log(context, "test_task_start", index=idx, key=task["key"],
              text=task["text"], limit_s=task["limit_s"])


def _finish_task(context, result):
    props = context.scene.logger_props
    task = test_tasks.TASKS[props.test_index]
    elapsed = LoggerManager._rel() - props.test_task_start
    try:
        _ok, sub = _judge_now(context)
    except Exception:
        sub = None
    props.test_state = "DONE"
    props.test_result = result
    props.test_task_elapsed = elapsed
    if result == "completed":
        props.test_completed_count += 1
    _test_log(context, "test_task_end", index=props.test_index, key=task["key"],
              result=result, elapsed_s=round(elapsed, 3),
              undo_count=int(props.test_undo_count), reset_count=int(props.test_reset_count),
              sub=sub)


class LOGGER_OT_test_start(Operator):
    bl_idname = "logger.test_start"
    bl_label = "テスト開始"
    bl_description = "確認テストを始めます（これまで作ったシーンは消えて、課題ごとに立方体が用意されます）"

    def execute(self, context):
        props = context.scene.logger_props
        if props.monitoring_active:
            bpy.ops.logger.stop_session()
        props.test_log_path = ""
        if not LoggerManager.ensure_participant_log_file(context, "test"):
            self.report({'ERROR'}, props.participant_log_error or "ログファイルを作成できません")
            return {'CANCELLED'}
        props.test_error = ""
        props.test_active = True
        props.test_started_at = LoggerManager._rel()
        props.test_completed_count = 0
        _test_log(context, "test_start", total_tasks=len(test_tasks.TASKS))
        _begin_task(context, 0)
        LOGGER_OT_test_monitor._running = False
        bpy.ops.wm.logger_test_monitor()
        return {'FINISHED'}


class LOGGER_OT_test_next(Operator):
    bl_idname = "logger.test_next"
    bl_label = "次の課題へ"
    bl_description = "次の課題に進みます"

    def execute(self, context):
        props = context.scene.logger_props
        if not props.test_active or props.test_state != "DONE":
            return {'CANCELLED'}
        idx = props.test_index + 1
        if idx < len(test_tasks.TASKS):
            _begin_task(context, idx)
        else:
            _test_log(context, "test_end",
                      total_elapsed_s=round(LoggerManager._rel() - props.test_started_at, 3),
                      completed=int(props.test_completed_count),
                      total_tasks=len(test_tasks.TASKS))
            props.test_state = "END"
            props.test_active = False
        return {'FINISHED'}


class LOGGER_OT_test_skip(Operator):
    bl_idname = "logger.test_skip"
    bl_label = "分からない（次へ）"
    bl_description = "この課題は未完了として次へ進みます"

    def execute(self, context):
        props = context.scene.logger_props
        if props.test_active and props.test_state == "RUN":
            _finish_task(context, "skipped")
        return {'FINISHED'}


class LOGGER_OT_test_reset_scene(Operator):
    bl_idname = "logger.test_reset_scene"
    bl_label = "シーンをやり直す"
    bl_description = "立方体を消してしまった時などに、この課題の最初の状態に戻します（時間は止まりません）"

    def execute(self, context):
        props = context.scene.logger_props
        if props.test_active and props.test_state == "RUN":
            task = test_tasks.TASKS[props.test_index]
            test_tasks.reset_scene(context, select_cube=(task["key"] != "practice"))
            _capture_view_base(context)
            props.test_reset_count += 1
            _test_log(context, "test_reset", index=props.test_index, key=task["key"])
        return {'FINISHED'}


class LOGGER_OT_test_monitor(Operator):
    bl_idname = "wm.logger_test_monitor"
    bl_label = "Comparison Test Monitor"
    _timer = None
    _last = 0.0
    _running = False

    def modal(self, context, event):
        if event.type == 'TIMER':
            try:
                props = context.scene.logger_props
                if not props.test_active:
                    if self._timer:
                        context.window_manager.event_timer_remove(self._timer)
                    LOGGER_OT_test_monitor._running = False
                    return {'FINISHED'}
                now = LoggerManager._rel()
                if props.test_state == "RUN" and now - self._last > 0.2:
                    self._last = now
                    ok, _sub = _judge_now(context)
                    limit = test_tasks.TASKS[props.test_index]["limit_s"]
                    if ok:
                        _finish_task(context, "completed")
                    elif now - props.test_task_start > limit:
                        _finish_task(context, "timeout")
                for area in context.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
            except Exception as e:
                try:
                    context.scene.logger_props.test_error = f"{type(e).__name__}: {e}"
                except Exception:
                    pass
        return {'PASS_THROUGH'}

    def execute(self, context):
        if LOGGER_OT_test_monitor._running:
            return {'CANCELLED'}
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.2, window=context.window)
        self._last = LoggerManager._rel()
        LOGGER_OT_test_monitor._running = True
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}


# =====================================================
# UNDO HANDLER
# =====================================================

def _logger_undo_handler(*args):
    try:
        scene = bpy.context.scene
        if not scene or not hasattr(scene, 'logger_props'):
            return
        props = scene.logger_props
        if props.test_active and props.test_state == "RUN":
            props.test_undo_count += 1
        if props.monitoring_active:
            props.undo_count += 1
    except Exception:
        pass


# =====================================================
# CSV エクスポート（研究者用・実験後に使用）
# =====================================================

class LOGGER_OT_export_summary_csv(Operator):
    bl_idname = "logger.export_summary_csv"
    bl_label = "計測結果CSV出力"
    bl_description = "参加者ログ(JSONL)から、カテゴリ別の検出時刻をCSV出力します"

    def execute(self, context):
        props = context.scene.logger_props
        if not props.participant_log_path:
            self.report({'ERROR'}, "ログファイルがまだありません。計測を開始してください。")
            return {'CANCELLED'}

        jsonl_path = bpy.path.abspath(props.participant_log_path)
        if not os.path.isfile(jsonl_path):
            self.report({'ERROR'}, f"ログファイルが見つかりません: {jsonl_path}")
            return {'CANCELLED'}

        events = []
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            self.report({'ERROR'}, f"ログ読み込みに失敗: {e}")
            return {'CANCELLED'}

        by_category = {i: {"category": i, "label": CATEGORY_LABELS[i],
                            "detected": False, "elapsed_s": None, "undo_count_so_far": None}
                       for i in range(1, 7)}
        total_elapsed = None
        total_undo = None

        for ev in events:
            if ev.get("event") == "category_detected":
                cat = ev.get("category")
                if cat in by_category:
                    by_category[cat]["detected"] = True
                    by_category[cat]["elapsed_s"] = ev.get("elapsed_s")
                    by_category[cat]["undo_count_so_far"] = ev.get("undo_count_so_far")
            if ev.get("event") == "measurement_end":
                total_elapsed = ev.get("total_elapsed_s")
                total_undo = ev.get("undo_count_total")

        out_csv = os.path.splitext(jsonl_path)[0] + ".category_summary.csv"
        try:
            with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["participant_log_file", os.path.basename(jsonl_path)])
                w.writerow(["total_elapsed_s", total_elapsed if total_elapsed is not None else ""])
                w.writerow(["undo_count_total", total_undo if total_undo is not None else ""])
                w.writerow([])
                w.writerow(["category", "label", "detected", "elapsed_s", "undo_count_so_far"])
                for i in range(1, 7):
                    r = by_category[i]
                    w.writerow([
                        r["category"], r["label"], r["detected"],
                        r["elapsed_s"] if r["elapsed_s"] is not None else "",
                        r["undo_count_so_far"] if r["undo_count_so_far"] is not None else "",
                    ])
        except Exception as e:
            self.report({'ERROR'}, f"CSV出力に失敗: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"CSV出力完了: {out_csv}")
        return {'FINISHED'}


# =====================================================
# PANEL（参加者には計測中/未計測しか見せない）
# =====================================================

class LOGGER_PT_main(Panel):
    bl_label = "比較実験ツール"
    bl_idname = "LOGGER_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Logger"

    def draw(self, context):
        layout = self.layout
        props = context.scene.logger_props
        in_test = props.test_active

        # テスト中は設定欄・学習ログ欄を隠して、課題だけを見せる
        if not in_test:
            box = layout.box()
            box.prop(props, "participant_id")
            box.prop(props, "group")
            box.prop(props, "log_dir")
            row = box.row(align=True)
            row.operator("logger.set_default_log_dir", text="既定フォルダに設定")
            row.operator("logger.open_log_folder", text="ログフォルダを開く")
            box.prop(props, "enable_logging")

            if props.group == 'VIDEO':
                lbox = layout.box()
                lbox.label(text="学習中の計測（動画版）")
                col = lbox.column()
                col.scale_y = 1.4
                if props.monitoring_active:
                    col.label(text="● 計測中")
                    col.operator("logger.stop_session", text="計測終了")
                else:
                    col.operator("logger.start_session", text="計測開始")

        tbox = layout.box()
        tbox.label(text="確認テスト")
        if not in_test:
            if props.test_state == "END":
                tbox.label(text="テストは終了しました。")
                tbox.label(text="お疲れさまでした。")
            col = tbox.column()
            col.scale_y = 1.4
            col.operator("logger.test_start", text="テスト開始")
        else:
            tasks = test_tasks.TASKS
            task = tasks[props.test_index]
            tbox.label(text=f"{task['title']}（{props.test_index + 1}/{len(tasks)}）")
            tbox.separator()
            for line in test_tasks.wrap_text(task["text"]):
                tbox.label(text=line)
            tbox.separator()
            if props.test_state == "RUN":
                remain = max(0, int(task["limit_s"] - (LoggerManager._rel() - props.test_task_start)))
                tbox.label(text=f"残り時間 {remain // 60}:{remain % 60:02d}")
                tbox.operator("logger.test_skip", text="分からない（次へ）")
                tbox.operator("logger.test_reset_scene", text="シーンをやり直す")
            else:
                msg = {"completed": "✓ 完了", "timeout": "時間切れ", "skipped": "スキップしました"}
                tbox.label(text=msg.get(props.test_result, ""))
                col = tbox.column()
                col.scale_y = 1.4
                last = props.test_index + 1 >= len(tasks)
                col.operator("logger.test_next", text="テストを終了する" if last else "次の課題へ")

        if props.participant_log_error:
            layout.label(text=f"注意: {props.participant_log_error}")
        if props.test_error:
            layout.label(text=f"テストエラー: {props.test_error}")

        if not in_test:
            layout.separator()
            layout.operator("logger.export_summary_csv", text="学習ログCSV出力（実験後）")


# =====================================================
# REGISTER
# =====================================================

classes = (
    LOGGER_PG_Properties,
    LOGGER_OT_set_default_log_dir,
    LOGGER_OT_open_log_folder,
    LOGGER_OT_start_session,
    LOGGER_OT_stop_session,
    LOGGER_OT_monitoring,
    LOGGER_OT_test_start,
    LOGGER_OT_test_next,
    LOGGER_OT_test_skip,
    LOGGER_OT_test_reset_scene,
    LOGGER_OT_test_monitor,
    LOGGER_OT_export_summary_csv,
    LOGGER_PT_main,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.logger_props = bpy.props.PointerProperty(type=LOGGER_PG_Properties)
    if _logger_undo_handler not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(_logger_undo_handler)

def unregister():
    if _logger_undo_handler in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(_logger_undo_handler)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.logger_props
