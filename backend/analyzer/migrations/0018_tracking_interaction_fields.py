from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0017_adjust_job_location_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='tracking',
            name='interaction_time',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='tracking',
            name='interview_round',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
