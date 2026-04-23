from .models import SubjectTemplate, Template


DEFAULT_TRACKING_TEMPLATE_SEEDS = [
    {
        "name": "General Intro - Role And Company",
        "category": "general",
        "achievement": "I am reaching out regarding the {role} opportunity at {company_name}{job_id_line}.",
    },
    {
        "name": "General Experience - Background",
        "category": "general",
        "achievement": "I bring {years_of_experience} years of experience and am currently working at {current_employer}.",
    },
    {
        "name": "General Closing - Connect",
        "category": "general",
        "achievement": "If helpful, I would be glad to connect and share more about how I can contribute to {company_name}.",
    },
    {
        "name": "Personalized Intro - Employee Focus",
        "category": "personalized",
        "achievement": "I noticed your work as {employee_role} in {employee_department} at {company_name}, and it stood out to me.",
    },
    {
        "name": "Personalized Intro - Shared Context",
        "category": "personalized",
        "achievement": "Your experience in {department} at {company_name} caught my attention, so I wanted to reach out directly about the {role} role.",
    },
    {
        "name": "Follow Up - Application Reminder",
        "category": "follow_up",
        "achievement": "Following up on my earlier note about the {role} role at {company_name}{job_id_line}.",
    },
    {
        "name": "Follow Up - Gentle Check In",
        "category": "follow_up",
        "achievement": "I wanted to check whether there has been any update on the {role} opportunity at {company_name}.",
    },
]


DEFAULT_SUBJECT_TEMPLATE_SEEDS = [
    {
        "name": "Fresh Subject - Application",
        "category": "fresh",
        "subject": "Application for {role} at {company_name} | {job_id}",
    },
    {
        "name": "Fresh Subject - Intro",
        "category": "fresh",
        "subject": "{user_name} | {role} | {company_name}",
    },
    {
        "name": "Follow Up Subject - Application",
        "category": "follow_up",
        "subject": "Follow up on {role} at {company_name} | {job_id}",
    },
    {
        "name": "Follow Up Subject - Interview",
        "category": "follow_up",
        "subject": "Follow up after {interview_round} | {company_name}",
    },
]


def ensure_default_mail_templates_for_profile(profile):
    if profile is None:
        return {"templates_created": 0, "subject_templates_created": 0}

    created_template_count = 0
    created_subject_count = 0

    for seed in DEFAULT_TRACKING_TEMPLATE_SEEDS:
        _row, created = Template.objects.get_or_create(
            profile=profile,
            name=seed["name"],
            defaults={
                "template_scope": Template.TEMPLATE_SCOPE_USER_BASED,
                "category": seed["category"],
                "achievement": seed["achievement"],
            },
        )
        if created:
            created_template_count += 1

    for seed in DEFAULT_SUBJECT_TEMPLATE_SEEDS:
        _row, created = SubjectTemplate.objects.get_or_create(
            profile=profile,
            name=seed["name"],
            defaults={
                "category": seed["category"],
                "subject": seed["subject"],
            },
        )
        if created:
            created_subject_count += 1

    return {
        "templates_created": created_template_count,
        "subject_templates_created": created_subject_count,
    }
