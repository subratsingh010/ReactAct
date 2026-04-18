from django.db import migrations, models


def populate_template_scope(apps, schema_editor):
    Template = apps.get_model("analyzer", "Template")
    Template.objects.filter(profile__isnull=True).update(template_scope="system")
    Template.objects.exclude(profile__isnull=True).update(template_scope="user_based")


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0004_template_profile_nullable"),
    ]

    operations = [
        migrations.AddField(
            model_name="template",
            name="template_scope",
            field=models.CharField(
                choices=[("system", "System"), ("user_based", "User Based")],
                default="user_based",
                max_length=20,
            ),
        ),
        migrations.RunPython(populate_template_scope, migrations.RunPython.noop),
    ]

