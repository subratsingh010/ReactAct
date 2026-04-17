from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from analyzer.management.commands.send_tracking_mails import Command
from analyzer.models import Company, Employee, Job, MailTrackingEvent, Resume, Template, Tracking, TrackingAction, UserProfile
from analyzer.serializers import CompanySerializer, InterviewSerializer, JobSerializer, ProfilePanelSerializer, UserProfileSerializer
from analyzer.tracking_mail_utils import ensure_mail_tracking
from analyzer.views import (
    ApplicationTrackingDetailView,
    ApplicationTrackingListCreateView,
    ApplicationTrackingMailTestView,
    ResumeDetailView,
    ResumeListCreateView,
    _validate_tracking_templates,
)


class DummySMTP:
    last_message = None
    last_from_email = None
    last_to_emails = None

    def __init__(self, host, port, timeout=30):
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        return None

    def login(self, username, password):
        return None

    def sendmail(self, from_email, to_emails, message):
        type(self).last_from_email = from_email
        type(self).last_to_emails = to_emails
        type(self).last_message = message


class SendTrackingMailsThreadingTests(TestCase):
    def setUp(self):
        self.command = Command()
        self.user = User.objects.create_user(username="mailer", email="sender@example.com", password="x")
        self.profile = UserProfile.objects.create(user=self.user)
        self.company = Company.objects.create(profile=self.profile, name="acme")
        self.employee = Employee.objects.create(
            owner_profile=self.profile,
            company=self.company,
            name="Recruiter",
            email="hr@acme.com",
        )
        self.job = Job.objects.create(company=self.company, job_id="J-1", role="Engineer")
        self.resume = Resume.objects.create(profile=self.profile, title="Base Resume")
        self.tracking = Tracking.objects.create(
            profile=self.profile,
            job=self.job,
            resume=self.resume,
            mail_type="followed_up",
        )
        self.mail_tracking = ensure_mail_tracking(self.tracking)

    def test_resolve_thread_context_uses_latest_sent_message_for_followup(self):
        MailTrackingEvent.objects.create(
            mail_tracking=self.mail_tracking,
            tracking=self.tracking,
            employee=self.employee,
            mail_type="fresh",
            send_mode="sent",
            status="sent",
            action_at=self.tracking.created_at,
            notes="sent",
            source_message_id="<first@example.com>",
            raw_payload={
                "to_email": "hr@acme.com",
                "subject": "Application for Engineer at acme",
                "message_id": "<first@example.com>",
            },
        )
        MailTrackingEvent.objects.create(
            mail_tracking=self.mail_tracking,
            tracking=self.tracking,
            employee=self.employee,
            mail_type="followup",
            send_mode="sent",
            status="sent",
            action_at=self.tracking.updated_at,
            notes="followup",
            source_message_id="<second@example.com>",
            raw_payload={
                "to_email": "hr@acme.com",
                "subject": "Re: Application for Engineer at acme",
                "message_id": "<second@example.com>",
                "references": ["<first@example.com>"],
            },
        )

        context = self.command._resolve_thread_context(self.mail_tracking, self.tracking, "hr@acme.com")

        self.assertEqual(context["in_reply_to"], "<second@example.com>")
        self.assertEqual(context["references"], ["<first@example.com>", "<second@example.com>"])
        self.assertEqual(context["subject"], "Re: Application for Engineer at acme")

    @patch("analyzer.management.commands.send_tracking_mails.smtplib.SMTP", DummySMTP)
    @patch.dict(
        "os.environ",
        {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_FROM_EMAIL": "sender@example.com",
            "SMTP_USE_TLS": "false",
        },
        clear=False,
    )
    def test_send_email_sets_thread_headers(self):
        message_id = self.command._send_email(
            self.user,
            "hr@acme.com",
            "Re: Application for Engineer at acme",
            "Follow up body",
            in_reply_to="<parent@example.com>",
            references=["<root@example.com>", "<parent@example.com>"],
        )

        self.assertTrue(message_id.startswith("<"))
        self.assertIn("Message-ID:", DummySMTP.last_message)
        self.assertIn("In-Reply-To: <parent@example.com>", DummySMTP.last_message)
        self.assertIn("References: <root@example.com> <parent@example.com>", DummySMTP.last_message)

    def test_attachment_fallback_uses_in_memory_pdf_bytes(self):
        self.resume.builder_data = {
            "resumeTitle": "Base Resume",
            "fullName": "Subrat Singh",
            "summary": "<p>Backend engineer</p>",
        }
        self.resume.ats_pdf_path = ""
        self.resume.save(update_fields=["builder_data", "ats_pdf_path", "updated_at"])

        payload = self.command._resolve_attachment_payload(self.tracking)

        self.assertIsNone(payload.get("path"))
        attachment_bytes = payload.get("bytes")
        self.assertTrue(isinstance(attachment_bytes, (bytes, bytearray)))
        self.assertTrue(bytes(attachment_bytes).startswith(b"%PDF-1.4"))

    def test_log_success_persists_message_metadata(self):
        self.command._log_success(
            self.mail_tracking,
            self.tracking,
            self.employee,
            "Re: Application for Engineer at acme",
            "Follow up body",
            "hr@acme.com",
            message_id="<child@example.com>",
            in_reply_to="<parent@example.com>",
            references=["<root@example.com>", "<parent@example.com>"],
        )

        event = MailTrackingEvent.objects.get(mail_tracking=self.mail_tracking)
        self.assertEqual(event.source_message_id, "<child@example.com>")
        self.assertEqual(event.raw_payload["message_id"], "<child@example.com>")
        self.assertEqual(event.raw_payload["in_reply_to"], "<parent@example.com>")
        self.assertEqual(
            event.raw_payload["references"],
            ["<root@example.com>", "<parent@example.com>"],
        )

    def test_mail_placeholder_map_keeps_only_allowed_dynamic_fields(self):
        self.employee.department = "HR"
        self.employee.JobRole = "Talent Acquisition Specialist"
        self.employee.about = "Experienced in technical and non-technical hiring across product and engineering teams."
        self.employee.save(update_fields=["department", "JobRole", "about", "updated_at"])
        self.profile.years_of_experience = "3"
        self.profile.current_employer = "Inspektlabs"
        self.profile.save(update_fields=["years_of_experience", "current_employer", "updated_at"])

        values = self.command._mail_placeholder_map(
            self.tracking,
            self.employee,
            self.profile,
            company_name="Acme",
            role="Fullstack",
            job_id="J-1",
        )

        self.assertEqual(values["job_id_line"], " (Job ID: J-1)")
        self.assertEqual(values["years_of_experience"], "3")
        self.assertEqual(values["yoe"], "3")
        self.assertEqual(values["department"], "HR")
        self.assertEqual(values["current_employer"], "Inspektlabs")
        self.assertTrue(values["interaction_time"])
        self.assertEqual(values["interview_round"], "")
        self.assertNotIn("employee_focus_area", values)
        self.assertNotIn("skills_text", values)
        self.assertNotIn("profile_role", values)

    def test_render_mail_placeholders_renders_optional_fragments_cleanly(self):
        rendered = self.command._render_mail_placeholders(
            "I applied for the {role} role{job_id_line} at {company_name}.",
            {
                "role": "fullstack",
                "job_id_line": " (Job ID: Test-01)",
                "company_name": "test",
            },
        )

        self.assertEqual(
            rendered,
            "I applied for the Fullstack role (Job ID: Test-01) at Test.",
        )

    def test_render_mail_placeholders_strips_unsupported_tokens(self):
        rendered = self.command._render_mail_placeholders(
            "I noticed your work in {employee_focus_area}. I am a {profile_role} with {skills_text}.",
            {
                "employee_focus_area": "technical hiring",
                "profile_role": "fullstack engineer",
                "skills_text": "python, react",
            },
        )

        self.assertEqual(rendered, "I noticed your work in . I am a with .")

    def test_render_mail_placeholders_supports_interaction_time_and_interview_round(self):
        rendered = self.command._render_mail_placeholders(
            "Thank you again for the {interview_round} interview at {interaction_time} for the {role} role at {company_name}.",
            {
                "interview_round": "technical",
                "interaction_time": "17 Apr 2026",
                "role": "fullstack",
                "company_name": "test",
            },
        )

        self.assertEqual(
            rendered,
            "Thank you again for the Technical interview at 17 Apr 2026 for the Fullstack role at Test.",
        )


class TrackingTemplateValidationTests(TestCase):
    def test_follow_up_requires_at_least_one_template(self):
        self.assertEqual(_validate_tracking_templates([], "followed_up"), "For follow up, select at least 1 template.")

    def test_follow_up_allows_up_to_two_follow_up_templates(self):
        user = User.objects.create_user(username="followuptemplates", password="x")
        profile = UserProfile.objects.create(user=user)
        first = Template.objects.create(profile=profile, name="Follow 1", category="follow_up", achievement="One")
        second = Template.objects.create(profile=profile, name="Follow 2", category="follow_up", achievement="Two")
        self.assertEqual(_validate_tracking_templates([first, second], "followed_up"), "")

    def test_follow_up_rejects_more_than_two_templates(self):
        user = User.objects.create_user(username="followuptemplatesmax", password="x")
        profile = UserProfile.objects.create(user=user)
        rows = [
            Template.objects.create(profile=profile, name=f"Follow {index}", category="follow_up", achievement=str(index))
            for index in range(1, 4)
        ]
        self.assertEqual(_validate_tracking_templates(rows, "followed_up"), "For follow up, select at most 2 templates.")


class SendTrackingAttachmentSafetyTests(TestCase):
    def test_missing_attachment_payload_defaults_to_empty_dict(self):
        command = Command()
        user = User.objects.create_user(username="attachsafe", email="attachsafe@example.com", password="x")
        profile = UserProfile.objects.create(user=user)
        company = Company.objects.create(profile=profile, name="acme", mail_format="{first}.{last}@acme.com")
        employee = Employee.objects.create(
            owner_profile=profile,
            company=company,
            name="Recruiter One",
            first_name="Recruiter",
            last_name="One",
            email="recruiter.one@acme.com",
            working_mail=True,
        )
        job = Job.objects.create(company=company, job_id="J-9", role="Engineer")
        tracking = Tracking.objects.create(profile=profile, job=job, mail_type="fresh", schedule_time=timezone.now())
        tracking.selected_hrs.set([employee])

        command._resolve_attachment_payload = lambda row: None

        payload = command._resolve_attachment_payload(tracking) or {}
        self.assertIsNone(payload.get("path"))
        self.assertIsNone(payload.get("bytes"))


class TrackingFreshRuleApiTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ApplicationTrackingDetailView.as_view()
        self.user = User.objects.create_user(username="tracker", email="tracker@example.com", password="x")
        self.profile = UserProfile.objects.create(user=self.user)
        self.company = Company.objects.create(profile=self.profile, name="beta", mail_format="{first}@beta.com")
        self.employee_one = Employee.objects.create(
            owner_profile=self.profile,
            company=self.company,
            name="Alice",
            department="Engineering",
            email="alice@beta.com",
        )
        self.employee_two = Employee.objects.create(
            owner_profile=self.profile,
            company=self.company,
            name="Bob",
            department="Engineering",
            email="bob@beta.com",
        )
        self.job = Job.objects.create(company=self.company, job_id="J-2", role="Backend")
        self.resume = Resume.objects.create(profile=self.profile, title="Resume")
        self.template_opening = Template.objects.create(profile=self.profile, name="Opening", category="opening", achievement="Open")
        self.template_experience = Template.objects.create(profile=self.profile, name="Experience", category="experience", achievement="Exp")
        self.template_closing = Template.objects.create(profile=self.profile, name="Closing", category="closing", achievement="Close")
        self.tracking = Tracking.objects.create(
            profile=self.profile,
            job=self.job,
            resume=self.resume,
            mail_type="fresh",
            template=self.template_opening,
            template_ids_ordered=[self.template_opening.id, self.template_experience.id, self.template_closing.id],
        )
        self.tracking.selected_hrs.set([self.employee_one])
        TrackingAction.objects.create(
            tracking=self.tracking,
            action_type="fresh",
            send_mode="sent",
            action_at=timezone.now(),
            notes='{"employee_ids":[%d]}' % self.employee_one.id,
        )

    def test_update_blocks_same_day_same_employee_fresh(self):
        request = self.factory.put(
            f"/api/tracking/{self.tracking.id}/",
            {
                "company": self.company.id,
                "job": self.job.id,
                "mail_type": "fresh",
                "template_ids_ordered": [
                    str(self.template_opening.id),
                    str(self.template_experience.id),
                    str(self.template_closing.id),
                ],
                "selected_hr_ids": [str(self.employee_one.id)],
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = self.view(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Fresh mail already used these employees earlier today in this tracking", str(response.data.get("detail", "")))

    def test_update_allows_same_day_fresh_for_fully_different_employee(self):
        request = self.factory.put(
            f"/api/tracking/{self.tracking.id}/",
            {
                "company": self.company.id,
                "job": self.job.id,
                "mail_type": "fresh",
                "template_ids_ordered": [
                    str(self.template_opening.id),
                    str(self.template_experience.id),
                    str(self.template_closing.id),
                ],
                "selected_hr_ids": [str(self.employee_two.id)],
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = self.view(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 200)


class TrackingMailTestViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.owner = User.objects.create_user(username="owner", email="owner@example.com", password="x")
        self.member = User.objects.create_user(username="member", email="member@example.com", password="x")
        self.superadmin = User.objects.create_user(username="superadmin", email="superadmin@example.com", password="x", is_superuser=True, is_staff=True)
        self.owner_profile = UserProfile.objects.create(user=self.owner)
        self.company = Company.objects.create(profile=self.owner_profile, name="Acme")
        self.employee = Employee.objects.create(
            owner_profile=self.owner_profile,
            company=self.company,
            name="Recruiter",
            email="recruiter@acme.com",
        )
        self.job = Job.objects.create(company=self.company, job_id="AC-1", role="Backend")
        self.resume = Resume.objects.create(profile=self.owner_profile, title="Resume")
        self.tracking = Tracking.objects.create(
            profile=self.owner_profile,
            job=self.job,
            resume=self.resume,
            mail_type="fresh",
            use_hardcoded_personalized_intro=False,
        )
        self.tracking.selected_hrs.set([self.employee])
        from analyzer.models import WorkspaceMember
        WorkspaceMember.objects.create(owner=self.owner, member=self.member, is_active=True)

    def test_admin_cannot_access_other_user_tracking(self):
        request = self.factory.get(f"/api/tracking/{self.tracking.id}/mail-test/")
        force_authenticate(request, user=self.member)

        response = ApplicationTrackingMailTestView.as_view()(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 404)

    def test_superadmin_can_access_other_user_tracking(self):
        request = self.factory.get(f"/api/tracking/{self.tracking.id}/mail-test/")
        force_authenticate(request, user=self.superadmin)

        response = ApplicationTrackingMailTestView.as_view()(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 200)

    def test_generate_reports_template_based_when_personalized_intro_is_not_selected(self):
        request = self.factory.post(
            f"/api/tracking/{self.tracking.id}/mail-test/",
            {"action": "generate"},
            format="json",
        )
        force_authenticate(request, user=self.owner)

        response = ApplicationTrackingMailTestView.as_view()(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("compose_mode"), "template_based")
        previews = response.data.get("previews") or []
        self.assertTrue(previews)
        self.assertEqual(previews[0].get("compose_mode"), "template_based")

    def test_read_only_cannot_save_mail_test_payloads(self):
        self.owner_profile.role = UserProfile.ROLE_READ_ONLY
        self.owner_profile.save(update_fields=["role", "updated_at"])
        request = self.factory.post(
            f"/api/tracking/{self.tracking.id}/mail-test/",
            {
                "action": "save",
                "previews": [
                    {
                        "employee_id": self.employee.id,
                        "employee_name": self.employee.name,
                        "email": self.employee.email,
                        "subject": "Subject",
                        "body": "Body",
                    }
                ],
            },
            format="json",
        )
        force_authenticate(request, user=self.owner)

        response = ApplicationTrackingMailTestView.as_view()(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 403)


class SuperadminVisibilityTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.owner = User.objects.create_user(username="owner-list", email="owner-list@example.com", password="x")
        self.superadmin = User.objects.create_user(
            username="superadmin-list",
            email="superadmin-list@example.com",
            password="x",
            is_superuser=True,
            is_staff=True,
        )
        self.owner_profile = UserProfile.objects.create(user=self.owner)
        self.company = Company.objects.create(profile=self.owner_profile, name="gamma", mail_format="{first}@gamma.com")
        self.employee = Employee.objects.create(
            owner_profile=self.owner_profile,
            company=self.company,
            name="Casey",
            department="Engineering",
            email="casey@gamma.com",
        )
        self.job = Job.objects.create(company=self.company, job_id="G-1", role="Platform Engineer")
        self.resume = Resume.objects.create(profile=self.owner_profile, title="Gamma Resume")
        self.tracking = Tracking.objects.create(profile=self.owner_profile, job=self.job, resume=self.resume, mail_type="fresh")
        self.tracking.selected_hrs.set([self.employee])

    def test_superadmin_can_see_other_user_tracking_list(self):
        request = self.factory.get("/api/tracking/")
        force_authenticate(request, user=self.superadmin)

        response = ApplicationTrackingListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        results = response.data.get("results") or []
        self.assertTrue(any(int(row.get("id")) == self.tracking.id for row in results))


class ResumeSaveStorageTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="resume-owner", email="resume-owner@example.com", password="x")
        self.profile = UserProfile.objects.create(user=self.user)

    def test_create_resume_keeps_only_db_data_without_file(self):
        request = self.factory.post(
            "/api/resumes/",
            {
                "title": "DB Resume",
                "builder_data": {"fullName": "Subrat Singh"},
                "original_text": "Subrat Singh",
                "is_default": False,
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ResumeListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 201)
        resume = Resume.objects.get(id=response.data["id"])
        self.assertFalse(bool(resume.file))

    def test_update_resume_clears_existing_file_attachment(self):
        resume = Resume.objects.create(
            profile=self.profile,
            title="Old Resume",
            original_text="Old text",
            file=SimpleUploadedFile("resume.pdf", b"%PDF-1.4 test file", content_type="application/pdf"),
        )
        self.assertTrue(bool(resume.file))

        request = self.factory.put(
            f"/api/resumes/{resume.id}/",
            {
                "title": "Updated Resume",
                "builder_data": {"fullName": "Updated User"},
                "original_text": "Updated User",
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ResumeDetailView.as_view()(request, resume_id=resume.id)

        self.assertEqual(response.status_code, 200)
        resume.refresh_from_db()
        self.assertFalse(bool(resume.file))


class SerializerNormalizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="serializer-user", email="serializer@example.com", password="x")
        self.profile = UserProfile.objects.create(user=self.user)
        self.company = Company.objects.create(profile=self.profile, name="Serializer Co")

    def test_company_serializer_trims_and_normalizes_urls(self):
        serializer = CompanySerializer(
            data={
                'name': '  Example Inc  ',
                'mail_format': ' firstname.lastname@example.com ',
                'career_url': 'careers.example.com',
                'workday_domain_url': 'https://jobs.example.com/workday',
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['name'], 'Example Inc')
        self.assertEqual(serializer.validated_data['mail_format'], 'firstname.lastname@example.com')
        self.assertEqual(serializer.validated_data['career_url'], 'https://careers.example.com')
        self.assertEqual(serializer.validated_data['workday_domain_url'], 'https://jobs.example.com/workday')

    def test_job_serializer_trims_fields_and_normalizes_job_link(self):
        serializer = JobSerializer(
            data={
                'company': self.company.id,
                'job_id': '  J-1001  ',
                'role': '  Backend Engineer  ',
                'job_link': 'jobs.example.com/apply',
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['job_id'], 'J-1001')
        self.assertEqual(serializer.validated_data['role'], 'Backend Engineer')
        self.assertEqual(serializer.validated_data['job_link'], 'https://jobs.example.com/apply')

    def test_user_profile_serializer_normalizes_email_and_urls(self):
        serializer = UserProfileSerializer(
            data={
                'full_name': '  Subrat Singh  ',
                'email': '  TEST@EXAMPLE.COM  ',
                'linkedin_url': 'linkedin.com/in/subrat',
                'github_url': 'github.com/subrat',
                'portfolio_url': 'portfolio.example.com',
                'summary': '  Backend developer  ',
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['full_name'], 'Subrat Singh')
        self.assertEqual(serializer.validated_data['email'], 'test@example.com')
        self.assertEqual(serializer.validated_data['linkedin_url'], 'https://linkedin.com/in/subrat')
        self.assertEqual(serializer.validated_data['github_url'], 'https://github.com/subrat')
        self.assertEqual(serializer.validated_data['portfolio_url'], 'https://portfolio.example.com')
        self.assertEqual(serializer.validated_data['summary'], 'Backend developer')

    def test_profile_panel_serializer_normalizes_contact_fields(self):
        serializer = ProfilePanelSerializer(
            data={
                'title': '  Recruiter Panel  ',
                'email': '  panel@example.com ',
                'linkedin_url': 'linkedin.com/in/panel',
                'summary': '  Recruiter-focused summary  ',
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['title'], 'Recruiter Panel')
        self.assertEqual(serializer.validated_data['email'], 'panel@example.com')
        self.assertEqual(serializer.validated_data['linkedin_url'], 'https://linkedin.com/in/panel')
        self.assertEqual(serializer.validated_data['summary'], 'Recruiter-focused summary')

    def test_interview_serializer_trims_company_role_and_notes(self):
        serializer = InterviewSerializer(
            data={
                'company_name': '  Example Inc  ',
                'job_role': '  Backend Engineer  ',
                'job_code': '  J-7  ',
                'stage': ' Round_1 ',
                'action': ' Active ',
                'notes': '  Strong first call  ',
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['company_name'], 'Example Inc')
        self.assertEqual(serializer.validated_data['job_role'], 'Backend Engineer')
        self.assertEqual(serializer.validated_data['job_code'], 'J-7')
        self.assertEqual(serializer.validated_data['stage'], 'round_1')
        self.assertEqual(serializer.validated_data['action'], 'active')
        self.assertEqual(serializer.validated_data['notes'], 'Strong first call')
