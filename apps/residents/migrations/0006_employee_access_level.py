from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0005_employee_card_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="residentemployee",
            name="access_level",
            field=models.CharField(
                choices=[
                    ("1", "Səviyyə 1 — turn_back yox"),
                    ("2", "Səviyyə 2 — turn_back icazəli"),
                ],
                default="1",
                help_text="1 = arxa turniket (turn_back) yox; 2 = turn_back icazəli",
                max_length=8,
            ),
        ),
    ]
