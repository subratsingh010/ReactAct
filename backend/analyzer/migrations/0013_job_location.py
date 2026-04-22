from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0012_remove_subjecttemplate_template_scope_and_restore_profile'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='location',
            field=models.CharField(blank=True, max_length=180),
        ),
    ]
