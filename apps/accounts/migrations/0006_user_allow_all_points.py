from django.db import migrations, models


def preserve_existing_access(apps, schema_editor):
    # Существующие мастера сохраняют текущий доступ. Новые сотрудники
    # без назначений получают нулевой доступ до явной настройки.
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="master", service_points__isnull=True).update(allow_all_points=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_accountdeletionrequest")]
    operations = [
        migrations.AddField(
            model_name="user", name="allow_all_points",
            field=models.BooleanField(
                default=False, verbose_name="все точки при пустом списке назначений",
                help_text="Только для сотрудников, которым нужен доступ ко всей сети.",
            ),
        ),
        migrations.AlterField(
            model_name="user", name="service_points",
            field=models.ManyToManyField(
                blank=True, related_name="masters", to="catalog.servicepoint",
                verbose_name="точки мастера",
                help_text="Назначьте точки или явно разрешите доступ ко всей сети ниже.",
            ),
        ),
        migrations.RunPython(preserve_existing_access, migrations.RunPython.noop),
    ]
