"""按模型质量关联数据的共享读取职责。

模型详情与治理看板原本各写了一遍模型归属过滤，这里把质量统计记录
（mdm_quality，仅「已完成」）与疑似重复簇（dup_cluster）按实体模型归属
的共同读取收敛到一处，产出「按模型质量关联数据」快照。

约定：
- 筛选口径沿用两个入口的既有约定：质量记录只取已完成，重复簇不按状态过滤；
  实体模型为空时不过滤归属（治理看板全局看板的缺省行为）。
- 返回的是取数时刻的深拷贝快照：取数之后发生的归属变更（如重复簇被移到
  其他模型）不会改写已取到的模型范围，单次取数确认的指标始终对应同一份
  可结算的模型范围。
- 本模块只负责读取边界，业务聚合（实体统计、看板指标）仍留在各消费方。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from app.store import store

QUALITY_MODULE = "mdm_quality"
CLUSTER_MODULE = "dup_cluster"
QUALITY_DONE_STATUS = "已完成"
MODEL_FIELD = "实体模型"


@dataclass(frozen=True)
class ModelQualityScope:
    """单次取数确认的按模型质量关联数据快照。

    quality_records: 该模型已完成的质量统计记录，保持存储顺序。
    duplicate_clusters: 该模型名下的疑似重复簇，保持存储顺序。
    """

    entity_model: str
    quality_records: list[dict[str, Any]] = field(default_factory=list)
    duplicate_clusters: list[dict[str, Any]] = field(default_factory=list)

    @property
    def latest_quality(self) -> dict[str, Any] | None:
        """已取到范围内最近一条已完成质量统计；无记录时为 None。"""
        return self.quality_records[-1] if self.quality_records else None


def load_model_quality_scope(entity_model: str | None = None) -> ModelQualityScope:
    """读取指定实体模型的质量关联数据，返回隔离快照。

    entity_model 为空时沿用看板缺省约定：不做归属过滤，取全部模型范围。
    快照为深拷贝，消费方持有的指标数据范围与后续归属变更解耦。
    """
    quality_rows = store.rows(QUALITY_MODULE)
    cluster_rows = store.rows(CLUSTER_MODULE)
    quality_records = [
        copy.deepcopy(row)
        for row in quality_rows
        if row.get("status") == QUALITY_DONE_STATUS
        and (not entity_model or row.get(MODEL_FIELD) == entity_model)
    ]
    duplicate_clusters = [
        copy.deepcopy(row)
        for row in cluster_rows
        if not entity_model or row.get(MODEL_FIELD) == entity_model
    ]
    return ModelQualityScope(
        entity_model=entity_model or "",
        quality_records=quality_records,
        duplicate_clusters=duplicate_clusters,
    )
