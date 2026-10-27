from abc import abstractmethod

from core.domain.repository import Repository

from apps.tenants.domain.entities.tenant import TenantEntity


class TenantRepository(Repository[TenantEntity]):
    @abstractmethod
    def get_by_slug(self, slug: str) -> TenantEntity | None: ...

    @abstractmethod
    def slug_exists(self, slug: str) -> bool: ...
