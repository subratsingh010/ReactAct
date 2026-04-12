from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0009_tailoredjobrun'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApplicationTracking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('company_name', models.CharField(max_length=180)),
                ('job_id', models.CharField(blank=True, max_length=120)),
                ('mailed', models.BooleanField(default=False)),
                ('applied_date', models.DateField(blank=True, null=True)),
                ('posting_date', models.DateField(blank=True, null=True)),
                ('is_open', models.BooleanField(default=True)),
                ('available_hrs', models.JSONField(blank=True, default=list)),
                ('selected_hrs', models.JSONField(blank=True, default=list)),
                ('got_replied', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tracking_rows', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-applied_date', '-created_at'],
            },
        ),
    ]
