from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0012_employee_department'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='about',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='employee',
            name='personalized_template_helpful',
            field=models.CharField(
                choices=[
                    ('good', 'Good'),
                    ('partial_somewhat', 'Partial / Somewhat'),
                    ('never', 'Never'),
                ],
                default='partial_somewhat',
                max_length=20,
            ),
        ),
    ]
