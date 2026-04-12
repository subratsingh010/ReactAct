from django.db import migrations


def seed_dummy_rows(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Company = apps.get_model('analyzer', 'Company')
    Employee = apps.get_model('analyzer', 'Employee')
    Job = apps.get_model('analyzer', 'Job')
    Tracking = apps.get_model('analyzer', 'Tracking')

    user, _ = User.objects.get_or_create(
        username='dummy_seed_user',
        defaults={
            'email': 'dummy_seed_user@example.com',
        },
    )

    companies = []
    for i in range(1, 11):
        company, _ = Company.objects.get_or_create(
            user=user,
            name=f'Dummy Company {i}',
            defaults={
                'career_url': f'https://dummy-company-{i}.example.com/careers',
                'workday_domain_url': f'https://dummy-company-{i}.myworkdayjobs.com/external',
            },
        )
        companies.append(company)

    employees = []
    helpful_values = ['good', 'partial_somewhat', 'never']
    for i in range(1, 11):
        company = companies[(i - 1) % len(companies)]
        employee, _ = Employee.objects.get_or_create(
            user=user,
            company=company,
            name=f'Dummy Employee {i}',
            defaults={
                'department': 'Talent Acquisition',
                'about': f'Dummy about text for employee {i}.',
                'personalized_template_helpful': helpful_values[(i - 1) % len(helpful_values)],
                'profile': f'https://linkedin.com/in/dummy-employee-{i}',
                'location': 'Bengaluru, India',
            },
        )
        employees.append(employee)

    jobs = []
    for i in range(1, 11):
        company = companies[(i - 1) % len(companies)]
        job, _ = Job.objects.get_or_create(
            user=user,
            company=company,
            job_id=f'DJ-{1000 + i}',
            defaults={
                'role': f'Software Engineer {i}',
                'job_link': f'https://jobs.example.com/dummy-job-{i}',
                'date_of_posting': f'2026-04-{i:02d}',
            },
        )
        jobs.append(job)

    for i in range(1, 11):
        company = companies[(i - 1) % len(companies)]
        employee = employees[(i - 1) % len(employees)]
        job = jobs[(i - 1) % len(jobs)]
        Tracking.objects.get_or_create(
            user=user,
            company=company,
            employee=employee,
            job=job,
            defaults={
                'mailed': i % 2 == 0,
                'applied_date': f'2026-04-{i:02d}',
                'is_open': i % 3 != 0,
                'got_replied': i % 4 == 0,
            },
        )


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
