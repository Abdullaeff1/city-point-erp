from django.db import migrations

QUEUE_CODES = ("hvac", "electric", "plumbing", "lift", "technical", "cleaning")
CATEGORY_SLUGS = ("technical", "cleaning")


def route_to_service_desk(apps, schema_editor):
    TicketDepartment = apps.get_model("tickets", "TicketDepartment")
    TicketQueue = apps.get_model("tickets", "TicketQueue")
    RoutingRule = apps.get_model("tickets", "RoutingRule")
    Ticket = apps.get_model("tickets", "Ticket")
    desk = TicketDepartment.objects.filter(code="servicedesk").first()
    if desk is None:
        return
    TicketQueue.objects.filter(code__in=QUEUE_CODES).update(department=desk)
    RoutingRule.objects.filter(queue__code__in=QUEUE_CODES).update(department=desk)
    Ticket.objects.filter(category__slug__in=CATEGORY_SLUGS).update(department=desk)


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0006_phases_3_13_foundations"),
    ]

    operations = [
        migrations.RunPython(route_to_service_desk, migrations.RunPython.noop),
    ]
