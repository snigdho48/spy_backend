from django.db import models
from django.utils.text import slugify

from core.infrastructure.models.base import BaseModel


class Tenant(BaseModel):
    class Plan(models.TextChoices):
        FREE = "free", "Free"
        PRO = "pro", "Pro"
        ENTERPRISE = "enterprise", "Enterprise"

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    plan = models.CharField(max_length=32, choices=Plan.choices, default=Plan.FREE)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "tenants_tenant"
        indexes = [
            models.Index(fields=["is_active", "created_at"]),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
