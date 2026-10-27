from django.db import models

from core.infrastructure.models.base import BaseModel


class SocialAccount(BaseModel):
    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="social_accounts",
    )
    provider = models.CharField(max_length=32, choices=Provider.choices, db_index=True)
    provider_uid = models.CharField(max_length=255)
    email = models.EmailField(blank=True)

    class Meta:
        db_table = "accounts_social_account"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_uid"],
                name="accounts_social_provider_uid_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "provider"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.provider_uid}"
