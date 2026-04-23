from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0018_tracking_interaction_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="resume",
            name="ats_pdf_builder_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
