from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0011_company_employee_job_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='department',
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
