from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0003_userprofile_ai_task_instructions_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="template",
            name="profile",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name="templates", to="analyzer.userprofile"),
        ),
    ]

