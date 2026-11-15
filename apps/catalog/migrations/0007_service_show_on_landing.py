from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0006_public_booking_phone")]
    operations = [migrations.AddField(
        model_name="service", name="show_on_landing",
        field=models.BooleanField(
            default=False, verbose_name="показывать на лендинге",
            help_text="Название и описание появятся на сайте без цены и остатков.",
        ),
    )]
