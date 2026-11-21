"""按模型质量关联数据的共享读取边界测试。

覆盖两类核对：
1. 静态输入下，模型详情与治理看板两个消费者共用读取职责后，
   指标、筛选和缺省值仍沿用原约定（各自聚合口径不变）。
2. 取数期间发生归属变更（重复簇被移到其他模型）时，
   已取到的模型范围不被半途变更污染，报表导出拿到的是一份
   完整一致的、可结算的模型范围。
"""
from __future__ import annotations

import os
import sys

_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.store import store
from app.services.entity_model import EntityModelService
from app.services.mdm_dashboard import MdmDashboardService
from app.services.model_quality_scope import load_model_quality_scope

MODEL_A = "核对模型A"
MODEL_B = "核对模型B"

_QUALITY_ROWS = [
    {"id": 911, "status": "已完成", "pending": False, "abnormal": False,
     "统计编号": "QLTY-911", "实体模型": MODEL_A, "完备率": "90.00%", "重复率": "2.00%",
     "一致率": "95.00%", "匹配精度": "88.00%", "统计时间": "2026-10-01", "统计区间": "全量"},
    {"id": 912, "status": "计算中", "pending": True, "abnormal": False,
     "统计编号": "QLTY-912", "实体模型": MODEL_A, "完备率": "10.00%", "重复率": "90.00%",
     "一致率": "10.00%", "匹配精度": "10.00%", "统计时间": "2026-10-02", "统计区间": "全量"},
    {"id": 913, "status": "已完成", "pending": False, "abnormal": False,
     "统计编号": "QLTY-913", "实体模型": MODEL_A, "完备率": "93.00%", "重复率": "1.00%",
     "一致率": "96.00%", "匹配精度": "91.00%", "统计时间": "2026-10-03", "统计区间": "全量"},
]
_CLUSTER_ROWS = [
    {"id": 921, "status": "待确认", "pending": True, "abnormal": False,
     "簇编号": "DUP-921", "实体模型": MODEL_A, "簇大小": "3", "创建时间": "2026-10-01"},
    {"id": 922, "status": "已合并", "pending": False, "abnormal": False,
     "簇编号": "DUP-922", "实体模型": MODEL_A, "簇大小": "2", "创建时间": "2026-10-02"},
    {"id": 923, "status": "待确认", "pending": True, "abnormal": False,
     "簇编号": "DUP-923", "实体模型": MODEL_B, "簇大小": "4", "创建时间": "2026-10-03"},
]


def _reset_rows(module: str, templates: list[dict]) -> None:
    """按模板重建核对数据：缺失则补登，已存在则恢复初始字段值。"""
    rows = store.rows(module)
    for template in templates:
        for row in rows:
            if int(row.get("id", 0)) == template["id"]:
                row.clear()
                row.update(dict(template))
                break
        else:
            rows.append(dict(template))


def _seed() -> None:
    """准备核对专用数据，并把可变字段恢复到初始归属。"""
    _reset_rows("entity_model", [{
        "id": 901, "status": "已生效", "pending": False, "abnormal": False,
        "模型编号": "ENTI-0901", "模型名称": MODEL_A, "业务域": "核对域",
        "主键字段": "pk", "匹配规则": "r", "合并策略": "s", "模型版本": "v1",
    }])
    _reset_rows("mdm_quality", _QUALITY_ROWS)
    _reset_rows("dup_cluster", _CLUSTER_ROWS)
    _reset_rows("mdm_dashboard", [{
        "id": 941, "status": "已发布", "pending": False, "abnormal": False,
        "看板编号": "DASH-941", "看板名称": "核对看板", "监控实体": MODEL_A,
        "展示指标": "完备率,重复率", "刷新频率": "每日", "数据范围": "全量",
    }])


def _move_cluster(cluster_id: int, target_model: str) -> None:
    """模拟归属变更：把一条重复簇移到其他模型。"""
    for row in store.rows("dup_cluster"):
        if int(row.get("id", 0)) == cluster_id:
            row["实体模型"] = target_model
            return
    raise AssertionError(f"重复簇 {cluster_id} 不存在")


def _tamper_quality(stat_id: str, field: str, value: str) -> None:
    """模拟取数后的质量记录变更。"""
    for row in store.rows("mdm_quality"):
        if row.get("统计编号") == stat_id:
            row[field] = value
            return
    raise AssertionError(f"质量记录 {stat_id} 不存在")


class TestModelQualityScope:
    """共享读取职责：按模型质量关联数据的边界与快照隔离。"""

    def setup_method(self):
        _seed()

    # ── 静态输入：筛选与缺省值沿用原约定 ──
    def test_scope_filters_by_model_ownership(self):
        """质量记录只取已完成，重复簇不按状态过滤，均按实体模型归属。"""
        scope = load_model_quality_scope(MODEL_A)
        assert [q["统计编号"] for q in scope.quality_records] == ["QLTY-911", "QLTY-913"]
        assert [c["簇编号"] for c in scope.duplicate_clusters] == ["DUP-921", "DUP-922"]
        assert scope.latest_quality["统计编号"] == "QLTY-913"

    def test_scope_empty_model_keeps_global_default(self):
        """实体模型为空时不过滤归属（看板全局口径的缺省约定）。"""
        scope = load_model_quality_scope("")
        total_completed = sum(
            1 for q in store.rows("mdm_quality") if q.get("status") == "已完成")
        assert len(scope.quality_records) == total_completed
        assert len(scope.duplicate_clusters) == len(store.rows("dup_cluster"))

    def test_consumers_keep_their_own_aggregation(self):
        """两个消费者各自维持原业务聚合口径，共用读取但不统一统计。"""
        details = EntityModelService().get_models_with_quality_stats()
        detail_a = next(d for d in details if d["model_name"] == MODEL_A)
        # 模型详情：实体统计口径（记录数、簇数、最近一条质量记录）
        assert detail_a["quality_records"] == 2
        assert detail_a["duplicate_clusters"] == 2
        assert detail_a["latest_quality"]["完备率"] == "93.00%"

        panel = MdmDashboardService().generate_governance_dashboard(941)["dashboard"]
        # 治理看板：看板指标口径（分状态簇计数、最近一条质量的指标值）
        assert panel["total_clusters"] == 2
        assert panel["pending_clusters"] == 1
        assert panel["merged_clusters"] == 1
        assert panel["completeness"] == "93.00%"
        assert panel["duplication"] == "1.00%"
        assert panel["consistency"] == "96.00%"

    # ── 取数期间归属变更：已取到的模型范围不被半途变更污染 ──
    def test_fetched_scope_isolated_from_ownership_change(self):
        """取数后把簇移到其他模型，已确认的指标仍对应已取到的模型范围。"""
        scope = load_model_quality_scope(MODEL_A)
        fetched_ids = [c["簇编号"] for c in scope.duplicate_clusters]

        _move_cluster(921, MODEL_B)  # 归属变更：DUP-921 被移到模型B

        # 已取到的范围保持原样：簇仍在快照内，归属字段仍是取数时的值
        assert [c["簇编号"] for c in scope.duplicate_clusters] == fetched_ids
        moved = next(c for c in scope.duplicate_clusters if c["簇编号"] == "DUP-921")
        assert moved["实体模型"] == MODEL_A

    def test_model_details_isolated_from_ownership_change(self):
        """模型详情已取到的实体统计不随取数后的归属变更漂移。"""
        details = EntityModelService().get_models_with_quality_stats()
        detail_a = next(d for d in details if d["model_name"] == MODEL_A)
        assert detail_a["duplicate_clusters"] == 2

        _move_cluster(921, MODEL_B)
        _tamper_quality("QLTY-913", "完备率", "0.00%")

        # 已取到的详情快照不变：簇数、最近质量记录仍是取数时的口径
        assert detail_a["duplicate_clusters"] == 2
        assert detail_a["latest_quality"]["实体模型"] == MODEL_A
        assert detail_a["latest_quality"]["完备率"] == "93.00%"

    def test_export_after_ownership_change_is_consistent_scope(self):
        """归属变更完成后导出质量台账：拿到的是变更后完整一致的模型范围。"""
        svc = MdmDashboardService()
        _move_cluster(921, MODEL_B)  # 变更先完成，值班随后导出

        report = svc.export_dashboard_report(941)
        assert report["ok"] is True
        panel = report["dashboard"]
        # 交付文件仍按原指标合同生成
        assert panel["entity"] == MODEL_A
        assert panel["report_id"].startswith("RPT-")
        # 指标数据范围是变更后的一致快照：模型A只剩 DUP-922 一条已合并簇
        assert panel["total_clusters"] == 1
        assert panel["pending_clusters"] == 0
        assert panel["merged_clusters"] == 1
        assert panel["completeness"] == "93.00%"
        # 不存在半途变更的混合口径：计数与归属过滤来自同一次取数
        scope_after = load_model_quality_scope(MODEL_A)
        assert panel["total_clusters"] == len(scope_after.duplicate_clusters)


if __name__ == "__main__":
    suite = TestModelQualityScope()
    cases = [name for name in dir(suite) if name.startswith("test_")]
    failed = 0
    for name in cases:
        try:
            suite.setup_method()
            getattr(suite, name)()
            print(f"  PASS: {name}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL: {name} -> {exc}")
            failed += 1
    print(f"\n结果: {len(cases) - failed}/{len(cases)} 通过, {failed} 失败")
    assert failed == 0, f"{failed} 条用例失败！"
