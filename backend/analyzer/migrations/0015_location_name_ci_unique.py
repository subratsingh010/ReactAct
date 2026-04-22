from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0014_normalize_location_fields'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='location',
            constraint=models.UniqueConstraint(
                Lower('name'),
                name='uniq_location_name_ci',
            ),
        ),
    ]
