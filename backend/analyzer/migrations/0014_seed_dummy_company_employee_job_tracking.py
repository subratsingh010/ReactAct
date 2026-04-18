from django.db import migrations


def seed_dummy_rows(apps, schema_editor):
    # Intentionally left blank. Dummy seed data must never be inserted automatically.
    return


def remove_dummy_rows(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Company = apps.get_model('analyzer', 'Company')
    Employee = apps.get_model('analyzer', 'Employee')
    Job = apps.get_model('analyzer', 'Job')
    Tracking = apps.get_model('analyzer', 'Tracking')

    try:
        user = User.objects.get(username='dummy_seed_user')
    except User.DoesNotExist:
        return

    Tracking.objects.filter(user=user).delete()
    Job.objects.filter(user=user, job_id__startswith='DJ-').delete()
    Employee.objects.filter(user=user, name__startswith='Dummy Employee ').delete()
    Company.objects.filter(user=user, name__startswith='Dummy Company ').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0013_employee_about_and_template_helpful'),
    ]

    operations = [
        migrations.RunPython(seed_dummy_rows, remove_dummy_rows),
    ]
