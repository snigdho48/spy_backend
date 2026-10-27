"""Predefined subscription packages — single source of truth."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanDefinition:
    code: str
    name: str
    price_monthly_usd: float
    max_devices: int
    max_members: int
    event_retention_days: int
    features: tuple[str, ...]
    is_active_listing: bool = True


PLAN_CATALOG: dict[str, PlanDefinition] = {
    "free": PlanDefinition(
        code="free",
        name="Free",
        price_monthly_usd=0,
        max_devices=2,
        max_members=2,
        event_retention_days=7,
        features=(
            "Up to 2 monitored devices",
            "Location, battery & network",
            "Call log & SMS history",
            "WhatsApp / Messenger notification capture",
            "7-day event history",
            "Email support",
        ),
    ),
    "pro": PlanDefinition(
        code="pro",
        name="Pro",
        price_monthly_usd=9.99,
        max_devices=10,
        max_members=10,
        event_retention_days=90,
        features=(
            "Up to 10 monitored devices",
            "All consent scopes",
            "90-day event history",
            "Audit log access",
            "Priority support",
        ),
    ),
    "enterprise": PlanDefinition(
        code="enterprise",
        name="Enterprise",
        price_monthly_usd=29.99,
        max_devices=100,
        max_members=50,
        event_retention_days=365,
        features=(
            "Up to 100 monitored devices",
            "All consent scopes",
            "1-year event history",
            "Dedicated support",
            "Custom retention policies",
        ),
    ),
}


def get_plan(code: str) -> PlanDefinition | None:
    return PLAN_CATALOG.get(code)


def list_plans() -> list[PlanDefinition]:
    return [p for p in PLAN_CATALOG.values() if p.is_active_listing]


def plan_to_dict(plan: PlanDefinition) -> dict:
    return {
        "code": plan.code,
        "name": plan.name,
        "price_monthly_usd": plan.price_monthly_usd,
        "max_devices": plan.max_devices,
        "max_members": plan.max_members,
        "event_retention_days": plan.event_retention_days,
        "features": list(plan.features),
    }
