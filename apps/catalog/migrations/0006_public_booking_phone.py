from django.db import migrations


def update_booking_phone(apps, schema_editor):
    apps.get_model("catalog", "ServicePoint").objects.update(phone="+73519481212")


class Migration(migrations.Migration):
    dependencies = [("catalog", "0005_services_from_oils")]
    operations = [migrations.RunPython(update_booking_phone, migrations.RunPython.noop)]
