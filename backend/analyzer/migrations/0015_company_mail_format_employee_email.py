from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0014_seed_dummy_company_employee_job_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='mail_format',
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddField(
            model_name='employee',
            name='email',
            field=models.EmailField(blank=True, max_length=320),
        ),
    ]
