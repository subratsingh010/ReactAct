from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0016_job_role_location_unique'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='job',
            name='uniq_active_job_company_role_location_ci',
        ),
        migrations.AddConstraint(
            model_name='job',
            constraint=models.UniqueConstraint(
                'company',
                Lower('job_id'),
                Lower('location'),
                condition=models.Q(is_removed=False) & ~models.Q(job_id=''),
                name='uniq_active_job_company_jobid_location_ci',
            ),
        ),
    ]
