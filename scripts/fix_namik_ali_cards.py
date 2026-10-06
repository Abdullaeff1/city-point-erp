#!/usr/bin/env python3
"""One-shot: assign card 006001 to Namik (City Point); deactivate Əli Cumayev (Simbrella)."""
from django.utils import timezone

from apps.residents.models import ResidentEmployee


def main():
    ali = ResidentEmployee.objects.filter(
        full_name__icontains="Cumayev", company__name__icontains="Simbrella"
    ).first()
    namik = ResidentEmployee.objects.filter(
        full_name__icontains="Namik", company__name__icontains="City Point"
    ).first()
    print("before namik=", namik, getattr(namik, "card_number", None))
    print("before ali=", ali, getattr(ali, "card_number", None), getattr(ali, "is_active", None))
    if not namik or not ali:
        raise SystemExit("employees not found")
    ResidentEmployee.objects.filter(card_number="006001").exclude(pk=namik.pk).update(card_number="")
    namik.card_number = "006001"
    namik.is_active = True
    namik.deactivated_at = None
    namik.save()
    ali.is_active = False
    if ali.deactivated_at is None:
        ali.deactivated_at = timezone.now()
    ali.card_number = ""
    ali.save()
    print(
        "after",
        list(
            ResidentEmployee.objects.filter(pk__in=[namik.pk, ali.pk]).values_list(
                "full_name", "company__name", "card_number", "is_active"
            )
        ),
    )
    print(
        "006001 holders",
        list(ResidentEmployee.objects.filter(card_number="006001").values_list("full_name", "company__name")),
    )


if __name__ == "__main__":
    main()
