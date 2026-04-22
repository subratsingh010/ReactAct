from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0015_location_name_ci_unique'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='job',
            constraint=models.UniqueConstraint(
                'company',
                Lower('role'),
                Lower('location'),
                condition=models.Q(is_removed=False),
                name='uniq_active_job_company_role_location_ci',
            ),
        ),
    ]
