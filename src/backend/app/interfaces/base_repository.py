"""BaseRepository - 通用 Repository Protocol（结构化子类型）。

4 个方法：
- get_by_id()  按主键查单条
- create()     新增
- update()     按主键更新
- list()       条件查询列表

设计选择：用 Protocol 而非 ABC，避免 isinstance 检查，更轻量。
实现层：app/implementations/db/repositories/

SOP：SOP-REPO-001（4 个逆向场景：主键冲突/字段超长/NULL 违反/无结果）
"""

from typing import Protocol, TypeVar, Generic, Optional, runtime_checkable

# TypeVar 约束为 BaseModel 子类（Pydantic v2）
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class BaseRepository(Protocol, Generic[T]):
    """通用 Repository 协议。

    评审意义：所有 Repository 都遵循同一接口，业务代码可不感知具体实体。

    实现示例：
        class MerchantRepository:
            def get_by_id(self, merchant_id: str) -> Optional[Merchant]: ...
            def create(self, merchant: Merchant) -> bool: ...
            def update(self, merchant_id: str, merchant: Merchant) -> bool: ...
            def list(self, filters=None, limit=100) -> list[Merchant]: ...
    """

    def get_by_id(self, id: str) -> Optional[T]:
        """按主键查单条。"""
        ...

    def create(self, entity: T) -> bool:
        """新增。"""
        ...

    def update(self, id: str, entity: T) -> bool:
        """按主键更新（需 entity 含 id 字段）。"""
        ...

    def list(
        self, filters: Optional[dict] = None, limit: int = 100
    ) -> list[T]:
        """条件查询列表。"""
        ...


# === 通用异常 ===

class RepositoryError(Exception):
    """Repository 通用异常基类。"""


class NotFoundError(RepositoryError):
    """记录不存在。"""


class DuplicateKeyError(RepositoryError):
    """主键冲突。"""


class ValidationError(RepositoryError):
    """数据校验失败（字段超长/NULL 违反等）。"""