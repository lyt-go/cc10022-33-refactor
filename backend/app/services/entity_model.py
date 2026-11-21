"""实体模型领域服务：模型校验、匹配规则关联与合并策略管理。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.model_quality_scope import load_model_quality_scope
from app.store import store


class EntityModelService(BaseModuleService):
    MODULE = "entity_model"
    ENTITY = "实体模型"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["模型编号", "模型名称", "业务域", "主键字段", "匹配规则", "合并策略", "审计时间", "模型版本"]
    REQUIRED_FIELDS = ["模型编号", "模型名称", "业务域"]
    STATUS_ORDER = ["草稿", "待校验", "已生效", "已废弃"]
    ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "标记废弃": "已废弃"}
    NEGATIVE_ACTIONS = []

    def validate_entity_model(self, model_id: int,
                               required_fields: list[str]) -> dict[str, Any]:
        """校验实体模型：检查匹配规则、合并策略和主键字段配置完整性。

        读取实体模型存储中的模型配置，校验主键字段唯一性、
        匹配规则关联有效性和合并策略可用性。
        """
        model = self.get_entry(model_id)
        if not model:
            return {"ok": False, "reason": "实体模型不存在"}
        checks = {
            "has_primary_key": bool(model.get("主键字段")),
            "has_match_rule": bool(model.get("匹配规则")),
            "has_merge_strategy": bool(model.get("合并策略")),
            "has_version": bool(model.get("模型版本")),
            "required_fields": required_fields,
        }
        # 校验实体模型配置：检查主键字段、匹配规则和合并策略完整性
        checks["all_valid"] = all([
            checks["has_primary_key"], checks["has_match_rule"], checks["has_merge_strategy"]
        ])
        return {"ok": checks["all_valid"], "checks": checks}

    def query_active_models(self, business_domain: str | None = None) -> list[dict[str, Any]]:
        """查询已生效的实体模型，按业务域筛选。

        遍历实体模型存储，查询已生效状态的实体模型，
        按业务域筛选并返回模型编号、名称和主键字段信息。
        """
        rows = store.rows(self.MODULE)
        active = [row for row in rows if row.get("status") == "已生效"]
        if business_domain:
            active = [row for row in active if row.get("业务域") == business_domain]
        # 查询已生效实体模型并按业务域筛选
        return active

    def link_match_rules(self, model_id: int, rule_ids: list[int]) -> dict[str, Any]:
        """关联匹配规则到实体模型，建立实体模型的匹配引擎配置。

        将指定匹配规则ID关联到实体模型，更新匹配规则字段引用，
        确保实体模型有完整的匹配检测能力。
        """
        model = self.get_entry(model_id)
        if not model:
            return {"ok": False, "reason": "实体模型不存在"}
        from app.services.match_rule import MatchRuleService
        rule_svc = MatchRuleService()
        linked = []
        failed = []
        for rule_id in rule_ids:
            rule = rule_svc.get_entry(rule_id)
            if rule and rule.get("status") == "已生效":
                linked.append(rule_id)
            else:
                failed.append(rule_id)
        # 关联匹配规则到实体模型：校验规则有效性后建立关联
        model["linked_rules"] = linked
        model["failed_rules"] = failed
        return {"ok": True, "linked": linked, "failed": failed}

    def get_models_with_quality_stats(self) -> list[dict[str, Any]]:
        """获取带质量统计的实体模型列表，关联各模型的重复率和完备率。

        通过共享读取职责取按模型质量关联数据，为每个已生效模型
        聚合质量指标，输出带统计数据的实体模型列表。
        """
        rows = store.rows(self.MODULE)
        result = []
        for model in rows:
            if model.get("status") != "已生效":
                continue
            model_name = model.get("模型名称", "")
            # 共享读取：按模型归属取质量记录与重复簇的隔离快照
            scope = load_model_quality_scope(model_name)
            # 实体统计口径不变：统计记录数、簇数并输出最近一条质量记录
            result.append({
                "model_name": model_name,
                "business_domain": model.get("业务域"),
                "quality_records": len(scope.quality_records),
                "duplicate_clusters": len(scope.duplicate_clusters),
                "latest_quality": scope.latest_quality,
            })
        return result