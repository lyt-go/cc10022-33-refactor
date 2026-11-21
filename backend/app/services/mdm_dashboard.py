"""看板配置领域服务：看板统计、实时指标展示与治理趋势分析。"""
from __future__ import annotations

import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.services.model_quality_scope import load_model_quality_scope
from app.store import store


class MdmDashboardService(BaseModuleService):
    MODULE = "mdm_dashboard"
    ENTITY = "看板配置"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["看板编号", "看板名称", "监控实体", "展示指标", "刷新频率", "数据范围", "分享链接", "看板版本"]
    REQUIRED_FIELDS = ["看板编号", "看板名称", "监控实体"]
    STATUS_ORDER = ["草稿", "待校验", "已发布", "已停用"]
    ACTION_RULES = {"提交校验": "待校验", "确认发布": "已发布", "停用看板": "已停用"}
    NEGATIVE_ACTIONS = ["停用看板"]

    def generate_governance_dashboard(self, dashboard_id: int) -> dict[str, Any]:
        """生成治理看板：汇总主数据质量、合并和同步维度的实时指标。

        读取看板配置的监控实体和展示指标，聚合来源系统接入数、
        黄金记录总量、重复率和质量完备率等治理关键指标。
        """
        dashboard = self.get_entry(dashboard_id)
        if not dashboard:
            return {"ok": False, "reason": "看板配置不存在"}
        entity = dashboard.get("监控实体", "")
        metrics = [m.strip() for m in dashboard.get("展示指标", "").split(",") if m.strip()]

        panel_data: dict[str, Any] = {
            "dashboard_name": dashboard.get("看板名称"),
            "generated_at": datetime.datetime.utcnow().isoformat(),
        }

        # 聚合来源系统接入统计
        sources = store.rows("source_system")
        panel_data["total_source_systems"] = len(sources)
        panel_data["active_systems"] = sum(1 for s in sources if s.get("status") == "已接入")

        # 聚合黄金记录统计
        golden = store.rows("golden_record")
        panel_data["total_golden_records"] = len(golden)
        panel_data["active_golden"] = sum(1 for g in golden if g.get("status") == "已生效")

        # 共享读取：单次取数确认按模型质量关联数据快照，
        # 本次看板的重复簇与质量指标均对应这一份已取到的模型范围
        scope = load_model_quality_scope(entity)

        # 聚合重复簇统计（沿用原口径：簇不按状态过滤，分别统计各状态数量）
        clusters = scope.duplicate_clusters
        panel_data["total_clusters"] = len(clusters)
        panel_data["pending_clusters"] = sum(1 for c in clusters if c.get("status") == "待确认")
        panel_data["merged_clusters"] = sum(1 for c in clusters if c.get("status") == "已合并")

        # 聚合质量统计（沿用原口径：仅已完成记录，取最近一条的指标值）
        completed_quality = scope.quality_records
        if completed_quality:
            latest = completed_quality[-1]
            panel_data["completeness"] = latest.get("完备率", "N/A")
            panel_data["duplication"] = latest.get("重复率", "N/A")
            panel_data["consistency"] = latest.get("一致率", "N/A")

        # 聚合同步统计
        sync_cfgs = store.rows("mdm_sync")
        panel_data["total_sync_configs"] = len(sync_cfgs)
        panel_data["active_syncs"] = sum(1 for s in sync_cfgs if s.get("status") == "同步中")

        # 生成治理看板：汇总主数据质量、合并和同步维度实时指标
        panel_data["metrics"] = metrics
        return {"ok": True, "dashboard": panel_data}

    def query_published_dashboards(self, entity_model: str | None = None) -> list[dict[str, Any]]:
        """查询已发布的治理看板配置。

        遍历看板配置存储，检索已发布状态的看板，
        按监控实体筛选并返回看板名称、展示指标和刷新频率。
        """
        rows = store.rows(self.MODULE)
        dashboards = [row for row in rows if row.get("status") == "已发布"]
        if entity_model:
            dashboards = [d for d in dashboards if d.get("监控实体") == entity_model]
        # 查询已发布看板配置：按监控实体筛选
        return dashboards

    def refresh_dashboard_data(self, dashboard_id: int) -> dict[str, Any]:
        """刷新看板数据：重新计算最新指标并更新看板展示。

        读取看板配置的刷新频率，触发指标重新计算流程，
        更新治理看板的实时数据并返回快照时间戳。
        """
        dashboard = self.get_entry(dashboard_id)
        if not dashboard:
            return {"ok": False, "reason": "看板不存在"}
        refreshed = self.generate_governance_dashboard(dashboard_id)
        if refreshed["ok"]:
            dashboard["last_refreshed"] = datetime.datetime.utcnow().isoformat()
            dashboard["refresh_count"] = str(int(dashboard.get("refresh_count", "0")) + 1)
        return refreshed

    def aggregate_governance_summary(self) -> dict[str, Any]:
        """聚合全局治理摘要：汇总所有看板的关键指标。

        读取所有看板配置和底层业务数据，计算全局治理总览，
        包含来源系统数、黄金记录数、重复率和质量完备率。
        """
        all_sources = store.rows("source_system")
        all_golden = store.rows("golden_record")
        all_clusters = store.rows("dup_cluster")
        all_quality = store.rows("mdm_quality")
        completed_q = [q for q in all_quality if q.get("status") == "已完成"]
        # 聚合全局治理摘要：汇总所有看板的来源、记录、重复和质量指标
        return {
            "source_systems": {"total": len(all_sources), "active": sum(1 for s in all_sources if s.get("status") == "已接入")},
            "golden_records": {"total": len(all_golden), "active": sum(1 for g in all_golden if g.get("status") == "已生效")},
            "duplicate_clusters": {"total": len(all_clusters), "pending": sum(1 for c in all_clusters if c.get("status") == "待确认")},
            "quality_stats": {"total": len(completed_q), "latest_at": completed_q[-1].get("统计时间") if completed_q else "N/A"},
        }

    def export_dashboard_report(self, dashboard_id: int) -> dict[str, Any]:
        """导出治理看板报告：将看板数据输出为结构化报告。

        消费共享读取产出的按模型质量关联数据（经由看板生成入口），
        按原指标合同生成交付文件，包含指标数据、生成时间和监控实体信息，
        供外部系统消费；已取到的模型范围不受取数后归属变更影响。
        """
        result = self.generate_governance_dashboard(dashboard_id)
        if not result["ok"]:
            return result
        dashboard = self.get_entry(dashboard_id)
        # 导出治理看板报告：结构化输出看板数据供外部消费
        result["dashboard"]["report_id"] = f"RPT-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        result["dashboard"]["entity"] = dashboard.get("监控实体") if dashboard else "N/A"
        return result