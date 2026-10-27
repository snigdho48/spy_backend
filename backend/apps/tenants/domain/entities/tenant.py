from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class TenantEntity:
    id: UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    created_at: datetime
