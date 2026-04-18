from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0005_template_template_scope"),
    ]

    operations = [
        migrations.DeleteModel(
            name="WorkspaceMember",
        ),
    ]

