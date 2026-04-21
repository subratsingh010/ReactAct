from django.db import migrations


def delete_dummy_permission(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        codename="view_dummy_data",
        content_type__app_label="analyzer",
        content_type__model="userprofile",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0010_subjecttemplate_template_scope_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="userprofile",
            name="hide_dummy_data",
        ),
        migrations.RemoveField(
            model_name="userprofile",
            name="hide_shared_dummy_data",
        ),
        migrations.RemoveField(
            model_name="userprofile",
            name="is_dummy_profile",
        ),
        migrations.AlterModelOptions(
            name="userprofile",
            options={"ordering": ["-updated_at", "-created_at"]},
        ),
        migrations.RunPython(delete_dummy_permission, migrations.RunPython.noop),
    ]
