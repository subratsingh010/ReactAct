import random
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from analyzer.models import (
    Company,
    Employee,
    Interview,
    Job,
    Location,
    Resume,
    Template,
    Tracking,
    TrackingAction,
    UserProfile,
)


class Command(BaseCommand):
    help = "Create realistic dummy data for local UI/API testing."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="dummy_admin", help="Username for the seeded user.")
        parser.add_argument("--password", default="dummy12345", help="Password for the seeded user.")
        parser.add_argument("--companies", type=int, default=3, help="Number of companies to create.")
        parser.add_argument("--employees-per-company", type=int, default=4, help="Employees to create for each company.")
        parser.add_argument("--jobs-per-company", type=int, default=3, help="Jobs to create for each company.")
        parser.add_argument("--reset", action="store_true", help="Delete the seeded user and recreate all their owned dummy data.")

    @transaction.atomic
    def handle(self, *args, **options):
        username = str(options["username"]).strip() or "dummy_admin"
        password = str(options["password"])
        company_count = max(1, int(options["companies"]))
        employees_per_company = max(1, int(options["employees_per_company"]))
        jobs_per_company = max(1, int(options["jobs_per_company"]))
        seeded_random = random.Random(f"dummy:{username}")

        if options.get("reset"):
            existing = User.objects.filter(username=username).first()
            if existing:
                existing.delete()
            Template.objects.filter(profile__isnull=True, name__startswith="[System Seed]").delete()
            Template.objects.filter(profile__isnull=True, name__in=[
                "Opening Intro",
                "Experience Highlight",
                "Closing Note",
                "Follow Up Note",
                "Personalized Intro",
            ]).delete()

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": f"{username}@example.com",
                "first_name": "Dummy",
                "last_name": "User",
            },
        )
        user.email = f"{username}@example.com"
        user.first_name = "Dummy"
        user.last_name = "User"
        user.set_password(password)
        user.save()

        admin_group = Group.objects.filter(name__iexact="admin").first()
        if admin_group:
            user.groups.add(admin_group)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.full_name = "Dummy User"
        profile.email = user.email
        profile.contact_number = "+91 9876543210"
        profile.current_employer = "Seed Labs"
        profile.years_of_experience = "4"
        profile.summary = "Seeded profile for local testing."
        profile.country = "India"
        profile.state = "Karnataka"
        profile.country_code = "+91"
        profile.location = "Bengaluru"
        profile.save()

        locations = self._ensure_locations()
        profile.preferred_locations.set([locations["Bengaluru"], locations["Remote"], locations["Hyderabad"]])

        system_templates = self._ensure_system_templates()
        user_templates = self._ensure_user_templates(profile)

        base_resume, tailored_resume = self._ensure_resumes(profile)

        companies = []
        employees = []
        jobs = []
        trackings = []
        interviews = []

        company_names = [
            "Acme Labs",
            "Northstar Systems",
            "Pixel Orbit",
            "Brightpath Tech",
            "Delta Stack",
            "Nimbus Works",
        ]
        engineering_names = [
            "Rahul Mehta",
            "Neha Verma",
            "Arjun Patel",
            "Priya Nair",
            "Sahil Gupta",
            "Ritika Rao",
            "Karan Malhotra",
            "Aditi Sharma",
        ]
        hr_names = [
            "Maya Joshi",
            "Nisha Kapoor",
            "Ishita Roy",
            "Tanvi Singh",
            "Aman Khanna",
            "Riya Das",
        ]
        role_names = [
            "Backend Engineer",
            "Frontend Engineer",
            "Full Stack Engineer",
            "Platform Engineer",
            "Python Developer",
            "Django Developer",
        ]

        opening_template = user_templates["opening"]
        experience_template = user_templates["experience"]
        closing_template = user_templates["closing"]
        follow_up_template = user_templates["follow_up"]
        personalized_template = user_templates["personalized"]
        system_personalized = system_templates["personalized"]

        for company_index in range(company_count):
            company_name = company_names[company_index % len(company_names)]
            company = Company.objects.create(
                profile=profile,
                name=f"{company_name} {company_index + 1}",
                mail_format="{first}.{last}@example.com",
                career_url=f"https://careers.example.com/{company_index + 1}",
                linkedin_url=f"https://linkedin.com/company/example-{company_index + 1}",
            )
            companies.append(company)

            company_employees = []
            for employee_index in range(employees_per_company):
                is_hr = employee_index % 3 == 0
                source_names = hr_names if is_hr else engineering_names
                full_name = source_names[(company_index + employee_index) % len(source_names)]
                first_name, last_name = full_name.split(" ", 1)
                employee = Employee.objects.create(
                    owner_profile=profile,
                    company=company,
                    name=full_name,
                    first_name=first_name,
                    last_name=last_name,
                    JobRole="Recruiter" if is_hr else role_names[(company_index + employee_index) % len(role_names)],
                    department="HR" if is_hr else "Engineering",
                    email=f"{first_name.lower()}.{last_name.lower().replace(' ', '')}@{company.name.replace(' ', '').lower()}.com",
                    working_mail=True,
                    about="Seeded employee contact for dummy data flows.",
                    personalized_template="Happy to connect regarding relevant roles.",
                    location=seeded_random.choice(["Bengaluru", "Hyderabad", "Pune", "Remote"]),
                    location_ref=locations[seeded_random.choice(list(locations.keys()))],
                )
                employees.append(employee)
                company_employees.append(employee)

            hr_contacts = [row for row in company_employees if str(row.department) == "HR"] or company_employees[:1]

            for job_index in range(jobs_per_company):
                role = role_names[(company_index + job_index) % len(role_names)]
                job = Job.objects.create(
                    company=company,
                    job_id=f"{company_index + 1:02d}-{job_index + 1:02d}",
                    role=role,
                    created_by=user,
                    job_link=f"https://jobs.example.com/{company_index + 1}/{job_index + 1}",
                    jd_text=f"We are hiring a {role} with strong Django, React, and API integration skills.",
                    date_of_posting=timezone.localdate() - timedelta(days=job_index * 2 + company_index),
                    applied_at=timezone.localdate() - timedelta(days=max(0, job_index * 2 + company_index - 1)),
                    is_closed=False,
                )
                job.assigned_to.add(user)
                jobs.append(job)

                selected_targets = hr_contacts[: min(len(hr_contacts), 2)]
                tracking = Tracking.objects.create(
                    profile=profile,
                    job=job,
                    template=opening_template,
                    template_ids_ordered=[opening_template.id, experience_template.id, closing_template.id],
                    personalized_template=personalized_template if job_index % 2 == 0 else system_personalized,
                    resume=tailored_resume if job_index % 2 == 0 else base_resume,
                    mail_type="fresh",
                    mailed=job_index % 2 == 0,
                    mail_delivery_status="successful_sent" if job_index % 2 == 0 else "pending",
                    mail_subject=f"Application for {role} at {company.name}",
                    use_hardcoded_personalized_intro=job_index % 2 == 0,
                    is_freezed=False,
                )
                tracking.selected_hrs.set(selected_targets)
                TrackingAction.objects.create(
                    tracking=tracking,
                    action_type="fresh",
                    send_mode="sent",
                    action_at=timezone.now() - timedelta(days=job_index + company_index),
                    notes="Seeded fresh action",
                )
                trackings.append(tracking)

                if job_index % 2 == 0:
                    follow_tracking = Tracking.objects.create(
                        profile=profile,
                        job=job,
                        template=follow_up_template,
                        template_ids_ordered=[follow_up_template.id],
                        personalized_template=follow_up_template,
                        resume=tailored_resume,
                        mail_type="followed_up",
                        mailed=True,
                        mail_delivery_status="successful_sent",
                        mail_subject=f"Following up for {role} at {company.name}",
                        use_hardcoded_personalized_intro=False,
                        is_freezed=False,
                    )
                    follow_tracking.selected_hrs.set(selected_targets[:1])
                    TrackingAction.objects.create(
                        tracking=follow_tracking,
                        action_type="followup",
                        send_mode="sent",
                        action_at=timezone.now() - timedelta(days=max(0, job_index)),
                        notes="Seeded follow-up action",
                    )
                    trackings.append(follow_tracking)

                interview = Interview.objects.create(
                    profile=profile,
                    job=job,
                    location_ref=locations[seeded_random.choice(list(locations.keys()))],
                    company_name=company.name,
                    job_role=role,
                    job_code=job.job_id,
                    stage="round_1" if job_index % 2 == 0 else "assignment",
                    action="active",
                    max_round_reached=1 if job_index % 2 == 0 else 0,
                    notes="Seeded interview entry for dashboard testing.",
                )
                interviews.append(interview)

        self.stdout.write(self.style.SUCCESS("Dummy data created successfully."))
        self.stdout.write(f"User: {username}")
        self.stdout.write(f"Password: {password}")
        self.stdout.write(
            f"Created {len(companies)} companies, {len(employees)} employees, {len(jobs)} jobs, "
            f"{len(trackings)} tracking rows, {len(interviews)} interviews."
        )
        self.stdout.write(
            f"Templates available: {Template.objects.filter(profile=profile).count()} personal, "
            f"{Template.objects.filter(template_scope=Template.TEMPLATE_SCOPE_SYSTEM).count()} system."
        )

    def _ensure_locations(self):
        names = ["Bengaluru", "Hyderabad", "Pune", "Chennai", "Remote"]
        return {name: Location.objects.get_or_create(name=name)[0] for name in names}

    def _ensure_system_templates(self):
        primary_specs = {
            "opening": ("Opening Intro", "opening", "I am excited to apply and believe my background aligns strongly with this role."),
            "experience": ("Experience Highlight", "experience", "I have built and shipped production Django and React features with a focus on reliability and delivery speed."),
            "closing": ("Closing Note", "closing", "Thank you for reviewing my application. I would value the chance to discuss the role further."),
            "follow_up": ("Follow Up Note", "follow_up", "Following up on my earlier application and sharing my continued interest in the opportunity."),
            "personalized": ("Personalized Intro", "personalized", "I noticed your team is focused on product quality and practical execution, which strongly matches how I work."),
        }
        extra_specs = [
            ("Opening Value Builder", "opening", "I am reaching out with a strong interest in the role and a practical track record of shipping work that matters."),
            ("Opening Delivery Focus", "opening", "This opportunity stands out because it matches the kind of execution-focused engineering work I have done in production."),
            ("Opening Product Mindset", "opening", "I enjoy building software that is useful, maintainable, and directly connected to product outcomes."),
            ("Opening Team Alignment", "opening", "Your team’s emphasis on ownership and consistent delivery feels closely aligned with how I like to work."),
            ("Opening Quick Intro", "opening", "I wanted to share a short introduction because this role looks like a strong fit for my experience."),
            ("Experience Backend Delivery", "experience", "I have delivered backend-heavy features, production fixes, and API integrations with Django and related tooling."),
            ("Experience Full Stack Ownership", "experience", "My recent work has covered both backend implementation and frontend integration, helping features move from idea to release."),
            ("Experience Platform Reliability", "experience", "I care about reliable systems, readable code, and shipping improvements without creating operational drag."),
            ("Experience Customer Impact", "experience", "Across recent roles, I have focused on features that improve workflows, reduce manual effort, and raise product quality."),
            ("Experience Practical Execution", "experience", "I work best in environments that value clear communication, hands-on problem solving, and practical execution."),
            ("Closing Short Thank You", "closing", "Thank you for taking the time to review my note and application."),
            ("Closing Invite To Connect", "closing", "I would be glad to connect and share more context on the projects most relevant to this role."),
            ("Closing Continued Interest", "closing", "I remain very interested in the position and would welcome the chance to speak further."),
            ("Closing Respectful Follow Through", "closing", "I appreciate your consideration and hope to continue the conversation if the role remains open."),
            ("Closing Availability Note", "closing", "If helpful, I am happy to provide more detail on my background, recent work, or availability."),
            ("Follow Up Gentle Nudge", "follow_up", "I wanted to follow up briefly on my earlier note and share my continued interest in the role."),
            ("Follow Up Role Interest", "follow_up", "Reaching out again to express continued interest and to see whether there might be a fit for my background."),
            ("Follow Up Short Reminder", "follow_up", "Sharing a quick follow up in case my earlier message was missed."),
            ("Follow Up Availability", "follow_up", "Happy to provide any additional information if it would be helpful as you review candidates."),
            ("Follow Up Timing Check", "follow_up", "I understand hiring timelines can vary, and I wanted to check back in respectfully on the opportunity."),
            ("Personalized Product Quality", "personalized", "Your focus on product quality and thoughtful execution is especially appealing to me."),
            ("Personalized Platform Work", "personalized", "The blend of platform thinking and application delivery in your team’s work stands out to me."),
            ("Personalized Customer Impact", "personalized", "I am drawn to teams that connect engineering decisions to real user and business impact."),
            ("Personalized Lean Team", "personalized", "Smaller, ownership-driven teams tend to be where I do my best work, which is part of why this role caught my eye."),
            ("Personalized Engineering Culture", "personalized", "The engineering culture you describe sounds aligned with the way I prefer to collaborate and deliver."),
            ("General Helpful Intro", "general", "Sharing a concise template that works as a flexible starting point for outreach and application notes."),
            ("General Follow Through", "general", "This template is useful when you want to sound direct, respectful, and easy to work with."),
            ("General Value Statement", "general", "A short value-oriented paragraph that can be adapted across multiple outreach situations."),
            ("General Concise Note", "general", "A brief note structure that keeps the message focused while still sounding thoughtful."),
            ("General Warm Outreach", "general", "A balanced outreach paragraph that stays professional, warm, and easy to personalize."),
        ]
        created = {}
        for key, (name, category, paragraph) in primary_specs.items():
            row, _ = Template.objects.get_or_create(
                profile=None,
                name=name,
                defaults={
                    "template_scope": Template.TEMPLATE_SCOPE_SYSTEM,
                    "category": category,
                    "achievement": paragraph,
                },
            )
            updates = []
            if row.template_scope != Template.TEMPLATE_SCOPE_SYSTEM:
                row.template_scope = Template.TEMPLATE_SCOPE_SYSTEM
                updates.append("template_scope")
            if row.category != category:
                row.category = category
                updates.append("category")
            if row.achievement != paragraph:
                row.achievement = paragraph
                updates.append("achievement")
            if updates:
                updates.append("updated_at")
                row.save(update_fields=updates)
            created[key] = row
        for name, category, paragraph in extra_specs:
            row, _ = Template.objects.get_or_create(
                profile=None,
                name=name,
                defaults={
                    "template_scope": Template.TEMPLATE_SCOPE_SYSTEM,
                    "category": category,
                    "achievement": paragraph,
                },
            )
            updates = []
            if row.template_scope != Template.TEMPLATE_SCOPE_SYSTEM:
                row.template_scope = Template.TEMPLATE_SCOPE_SYSTEM
                updates.append("template_scope")
            if row.category != category:
                row.category = category
                updates.append("category")
            if row.achievement != paragraph:
                row.achievement = paragraph
                updates.append("achievement")
            if updates:
                updates.append("updated_at")
                row.save(update_fields=updates)
        return created

    def _ensure_user_templates(self, profile):
        template_specs = {
            "opening": ("My Opening Template", "opening", "I am reaching out because this role is a strong match for my backend and full-stack experience."),
            "experience": ("My Experience Template", "experience", "Over the last four years, I have worked across Django APIs, frontend integrations, and production incident fixes."),
            "closing": ("My Closing Template", "closing", "I would be glad to share more detail and would appreciate the opportunity to connect."),
            "follow_up": ("My Follow Up Template", "follow_up", "Following up on my earlier note and sharing my continued interest in this position."),
            "personalized": ("My Personalized Template", "personalized", "Your recent hiring focus on practical product builders caught my attention and feels aligned with my experience."),
        }
        created = {}
        for key, (name, category, paragraph) in template_specs.items():
            row, _ = Template.objects.get_or_create(
                profile=profile,
                name=name,
                defaults={
                    "template_scope": Template.TEMPLATE_SCOPE_USER_BASED,
                    "category": category,
                    "achievement": paragraph,
                },
            )
            updates = []
            if row.template_scope != Template.TEMPLATE_SCOPE_USER_BASED:
                row.template_scope = Template.TEMPLATE_SCOPE_USER_BASED
                updates.append("template_scope")
            if row.category != category:
                row.category = category
                updates.append("category")
            if row.achievement != paragraph:
                row.achievement = paragraph
                updates.append("achievement")
            if updates:
                updates.append("updated_at")
                row.save(update_fields=updates)
            created[key] = row
        return created

    def _ensure_resumes(self, profile):
        base_builder = {
            "fullName": "Dummy User",
            "headline": "Full Stack Django Developer",
            "yearsOfExperience": "4",
            "summary": "Backend-heavy full stack developer with Django, DRF, React, and deployment experience.",
            "skills": ["Python", "Django", "DRF", "React", "PostgreSQL", "AWS"],
            "experience": [
                {
                    "company": "Seed Labs",
                    "role": "Software Engineer",
                    "startDate": "2022-01",
                    "endDate": "Present",
                    "bullets": [
                        "Built internal tools with Django and React to improve hiring and tracking workflows.",
                        "Shipped API integrations and automation features used in daily operations.",
                    ],
                }
            ],
            "education": [
                {
                    "school": "Seed University",
                    "degree": "B.Tech",
                    "field": "Computer Science",
                    "endYear": "2021",
                }
            ],
        }
        base_resume, _ = Resume.objects.get_or_create(
            profile=profile,
            title="Dummy Base Resume",
            defaults={
                "builder_data": base_builder,
                "is_default": True,
                "status": "draft",
            },
        )
        tailored_resume, _ = Resume.objects.get_or_create(
            profile=profile,
            title="Dummy Tailored Resume",
            defaults={
                "builder_data": {
                    **base_builder,
                    "headline": "Tailored Full Stack Django Developer",
                },
                "is_tailored": True,
                "source_resume": base_resume,
                "status": "optimized",
            },
        )
        if tailored_resume.source_resume_id != base_resume.id:
            tailored_resume.source_resume = base_resume
            tailored_resume.save(update_fields=["source_resume", "updated_at"])
        return base_resume, tailored_resume
