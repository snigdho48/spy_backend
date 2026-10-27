from uuid import UUID

from apps.tenants.domain.entities.tenant import TenantEntity
from apps.tenants.domain.repositories.tenant_repository import TenantRepository
from apps.tenants.infrastructure.models.tenant import Tenant


class DjangoTenantRepository(TenantRepository):
    def _to_entity(self, model: Tenant) -> TenantEntity:
        return TenantEntity(
            id=model.id,
            name=model.name,
            slug=model.slug,
            plan=model.plan,
            is_active=model.is_active,
            created_at=model.created_at,
        )

    def get_by_id(self, entity_id: UUID) -> TenantEntity | None:
        try:
            return self._to_entity(Tenant.objects.get(pk=entity_id))
        except Tenant.DoesNotExist:
            return None

    def get_by_slug(self, slug: str) -> TenantEntity | None:
        try:
            return self._to_entity(Tenant.objects.get(slug=slug))
        except Tenant.DoesNotExist:
            return None

    def slug_exists(self, slug: str) -> bool:
        return Tenant.objects.filter(slug=slug).exists()

    def save(self, entity: TenantEntity) -> TenantEntity:
        model, _ = Tenant.objects.update_or_create(
            id=entity.id,
            defaults={
                "name": entity.name,
                "slug": entity.slug,
                "plan": entity.plan,
                "is_active": entity.is_active,
            },
        )
        return self._to_entity(model)

    def delete(self, entity_id: UUID) -> None:
        Tenant.objects.filter(pk=entity_id).delete()
