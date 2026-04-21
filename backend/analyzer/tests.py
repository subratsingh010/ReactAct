import os
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from analyzer.dummy_data import DUMMY_DATA_PERMISSION, grant_dummy_data_permission, seed_shared_dummy_workspace
from analyzer.management.commands.send_tracking_mails import Command
from analyzer.models import Company, Employee, Interview, Job, Location, MailTrackingEvent, ProfilePanel, Resume, SubjectTemplate, Template, Tracking, TrackingAction, UserProfile
from analyzer.profile_settings import resolve_imap_settings, resolve_openai_settings, resolve_smtp_settings
from analyzer.serializers import CompanySerializer, InterviewSerializer, JobSerializer, ProfilePanelSerializer, UserProfileSerializer
from analyzer.tracking_mail_utils import ensure_mail_tracking
from analyzer.views import (
    ApplicationTrackingDetailView,
    ApplicationTrackingListCreateView,
    ApplicationTrackingMailTestView,
    CompanyDetailView,
    CompanyListCreateView,
    EmployeeDetailView,
    EmployeeListCreateView,
    ExtensionCompanySearchView,
    ExtensionFormMetaView,
    ExtensionJobCreateView,
    ExportAtsPdfLocalView,
    JobDetailView,
    JobListCreateView,
    ProfilePanelListCreateView,
    ProfileInfoView,
    ResumeDetailView,
    ResumeListCreateView,
    SubjectTemplateListCreateView,
    TemplateDetailView,
    TemplateListCreateView,
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


def grant_job_permissions(user, *codenames):
    permissions = list(Permission.objects.filter(codename__in=codenames))
    if permissions:
        user.user_permissions.add(*permissions)


def grant_model_permissions(user, model_name, *actions):
    codenames = [f"{action}_{model_name}" for action in actions]
    permissions = list(Permission.objects.filter(codename__in=codenames))
    if permissions:
        user.user_permissions.add(*permissions)


class TemplateAccessTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="templater", password="x")
        self.other = User.objects.create_user(username="other_templater", password="x")
        self.profile = UserProfile.objects.create(user=self.user)
        self.other_profile = UserProfile.objects.create(user=self.other)
        self.own_template = Template.objects.create(profile=self.profile, name="My Opening", category="opening", achievement="Mine")
        self.system_template = Template.objects.create(
            profile=None,
            template_scope=Template.TEMPLATE_SCOPE_SYSTEM,
            name="System Opening",
            category="opening",
            achievement="Shared",
        )
        self.other_template = Template.objects.create(profile=self.other_profile, name="Other Opening", category="opening", achievement="Other")

    def test_template_list_returns_only_own_and_system_templates(self):
        request = self.factory.get("/api/templates/")
        force_authenticate(request, user=self.user)
        response = TemplateListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        names = {row["name"] for row in response.data}
        self.assertIn("My Opening", names)
        self.assertIn("System Opening", names)
        self.assertNotIn("Other Opening", names)
        system_row = next(row for row in response.data if row["name"] == "System Opening")
        self.assertTrue(system_row["is_system"])
        self.assertEqual(system_row["owner_label"], "system")

    def test_system_template_cannot_be_edited_from_api(self):
        request = self.factory.put(
            f"/api/templates/{self.system_template.id}/",
            {"name": "Edited System"},
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = TemplateDetailView.as_view()(request, template_id=self.system_template.id)

        self.assertEqual(response.status_code, 404)


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

    def test_get_achievements_keeps_system_and_user_templates(self):
        own_template = Template.objects.create(profile=self.profile, name="Own Opening", category="opening", achievement="Mine")
        system_template = Template.objects.create(
            profile=None,
            template_scope=Template.TEMPLATE_SCOPE_SYSTEM,
            name="System Closing",
            category="closing",
            achievement="Shared",
        )
        self.tracking.template_ids_ordered = [own_template.id, system_template.id]
        self.tracking.save(update_fields=["template_ids_ordered", "updated_at"])

        rows = self.command._get_achievements(self.tracking)

        self.assertEqual([item.id for item in rows], [own_template.id, system_template.id])

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

    @patch("analyzer.management.commands.send_tracking_mails.smtplib.SMTP", DummySMTP)
    def test_send_email_uses_profile_smtp_settings_when_present(self):
        self.profile.smtp_host = "smtp.profile.example.com"
        self.profile.smtp_port = 2525
        self.profile.smtp_user = "profile-user"
        self.profile.smtp_password = "profile-pass"
        self.profile.smtp_use_tls = False
        self.profile.smtp_from_email = "profile-sender@example.com"
        self.profile.save()

        self.command._send_email(
            self.user,
            "hr@acme.com",
            "Profile SMTP",
            "Body",
        )

        self.assertEqual(DummySMTP.last_from_email, "profile-sender@example.com")
        self.assertEqual(DummySMTP.last_to_emails, ["hr@acme.com"])

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

    @patch.object(Command, "_build_builder_pdf_bytes", return_value=b"%PDF-1.7 exact")
    def test_attachment_prefers_shared_builder_pdf_over_saved_file(self, mocked_builder_pdf):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            tmp_pdf.write(b"%PDF-1.4 saved")
            saved_path = tmp_pdf.name
        self.addCleanup(lambda: os.unlink(saved_path) if os.path.exists(saved_path) else None)

        self.resume.builder_data = {
            "resumeTitle": "Base Resume",
            "fullName": "Subrat Singh",
            "summary": "<p>Backend engineer</p>",
        }
        self.resume.ats_pdf_path = saved_path
        self.resume.save(update_fields=["builder_data", "ats_pdf_path", "updated_at"])

        payload = self.command._resolve_attachment_payload(self.tracking)

        mocked_builder_pdf.assert_called_once()
        self.assertIsNone(payload.get("path"))
        self.assertEqual(payload.get("bytes"), b"%PDF-1.7 exact")

    def test_body_html_preserves_existing_html_document(self):
        html_body = '<!DOCTYPE html><html><body><article class="resume-sheet"><h1>Subrat Singh</h1></article></body></html>'

        rendered = self.command._body_html(html_body)

        self.assertEqual(rendered, html_body)

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


class ProfileSettingsTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="profile-user", email="profile@example.com", password="x")
        self.profile = UserProfile.objects.create(user=self.user, full_name="Profile User", email="profile@example.com")

    def test_profile_info_put_persists_mail_and_ai_settings(self):
        request = self.factory.put(
            "/api/profile-info/",
            {
                "smtp_host": "smtp.profile.example.com",
                "smtp_port": 2525,
                "smtp_user": "mailer",
                "smtp_password": "secret",
                "smtp_use_tls": False,
                "imap_host": "imap.profile.example.com",
                "imap_port": 993,
                "imap_user": "imap-user",
                "imap_password": "imap-secret",
                "openai_api_key": "sk-test",
                "openai_model": "gpt-4o",
                "ai_task_instructions": "Keep responses concise.",
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ProfileInfoView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.smtp_host, "smtp.profile.example.com")
        self.assertEqual(self.profile.smtp_port, 2525)
        self.assertFalse(self.profile.smtp_use_tls)
        self.assertEqual(self.profile.imap_host, "imap.profile.example.com")
        self.assertEqual(self.profile.openai_api_key, "sk-test")
        self.assertEqual(self.profile.ai_task_instructions, "Keep responses concise.")

    def test_profile_info_put_allows_clearing_port_fields(self):
        self.profile.smtp_port = 587
        self.profile.imap_port = 993
        self.profile.save(update_fields=["smtp_port", "imap_port", "updated_at"])
        request = self.factory.put(
            "/api/profile-info/",
            {"smtp_port": "", "imap_port": ""},
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ProfileInfoView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.smtp_port)
        self.assertIsNone(self.profile.imap_port)

    @patch.dict(
        "os.environ",
        {
            "SMTP_HOST": "smtp.env.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "env-user",
            "SMTP_PASSWORD": "env-pass",
            "SMTP_FROM_EMAIL": "env@example.com",
            "SMTP_USE_TLS": "true",
            "IMAP_HOST": "imap.env.example.com",
            "IMAP_PORT": "993",
            "IMAP_USER": "imap-env-user",
            "IMAP_PASSWORD": "imap-env-pass",
            "IMAP_FOLDER": "INBOX",
            "OPENAI_API_KEY": "env-openai-key",
            "OPENAI_MODEL": "gpt-4o",
        },
        clear=False,
    )
    def test_profile_setting_resolvers_fallback_and_override(self):
        smtp_settings = resolve_smtp_settings(self.user)
        imap_settings = resolve_imap_settings(self.user)
        openai_settings = resolve_openai_settings(self.user)
        self.assertEqual(smtp_settings["host"], "smtp.env.example.com")
        self.assertEqual(imap_settings["host"], "imap.env.example.com")
        self.assertEqual(openai_settings["api_key"], "env-openai-key")

        self.profile.smtp_host = "smtp.profile.example.com"
        self.profile.smtp_port = 2525
        self.profile.smtp_use_tls = False
        self.profile.imap_host = "imap.profile.example.com"
        self.profile.openai_api_key = "profile-openai-key"
        self.profile.openai_model = "gpt-4o-mini"
        self.profile.save()

        smtp_settings = resolve_smtp_settings(self.user)
        imap_settings = resolve_imap_settings(self.user)
        openai_settings = resolve_openai_settings(self.user)
        self.assertEqual(smtp_settings["host"], "smtp.profile.example.com")
        self.assertEqual(smtp_settings["port"], 2525)
        self.assertFalse(smtp_settings["use_tls"])
        self.assertEqual(imap_settings["host"], "imap.profile.example.com")
        self.assertEqual(openai_settings["api_key"], "profile-openai-key")
        self.assertEqual(openai_settings["model"], "gpt-4o-mini")


class TrackingTemplateValidationTests(TestCase):
    def test_follow_up_requires_at_least_one_template(self):
        self.assertEqual(_validate_tracking_templates([], "followed_up"), "For follow up, select at least 1 template.")

    def test_fresh_allows_single_non_opening_template(self):
        user = User.objects.create_user(username="freshtemplateone", password="x")
        profile = UserProfile.objects.create(user=user)
        first = Template.objects.create(profile=profile, name="General 1", category="general", achievement="One")
        self.assertEqual(_validate_tracking_templates([first], "fresh"), "")

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


class ExportAtsPdfLocalViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="pdfexporter", email="pdfexporter@example.com", password="x")
        self.profile = UserProfile.objects.create(user=self.user)
        self.resume = Resume.objects.create(profile=self.profile, title="Resume")

    @patch("analyzer.views.build_builder_pdf_bytes", return_value=b"%PDF-1.7 export")
    def test_export_accepts_builder_data_without_html_payload(self, mocked_builder_pdf):
        request = self.factory.post(
            "/api/export-ats-pdf-local/",
            {
                "resume_id": self.resume.id,
                "builder_data": {
                    "fullName": "Subrat Singh",
                    "summary": "<p>Backend engineer</p>",
                },
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ExportAtsPdfLocalView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        mocked_builder_pdf.assert_called_once()
        saved_path = response.data["saved_path"]
        self.addCleanup(lambda: os.unlink(saved_path) if os.path.exists(saved_path) else None)
        self.assertTrue(os.path.exists(saved_path))
        with open(saved_path, "rb") as handle:
            self.assertEqual(handle.read(), b"%PDF-1.7 export")


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
    def test_admin_cannot_access_other_user_tracking(self):
        request = self.factory.get(f"/api/tracking/{self.tracking.id}/mail-test/")
        force_authenticate(request, user=self.member)

        response = ApplicationTrackingMailTestView.as_view()(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 404)

    def test_superadmin_cannot_access_other_user_tracking_by_default(self):
        request = self.factory.get(f"/api/tracking/{self.tracking.id}/mail-test/")
        force_authenticate(request, user=self.superadmin)

        response = ApplicationTrackingMailTestView.as_view()(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 404)

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

    def test_profile_role_does_not_block_mail_test_save(self):
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

        self.assertEqual(response.status_code, 200)


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
        grant_model_permissions(self.owner, "company", "view")
        grant_model_permissions(self.owner, "employee", "view")
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

    def test_superadmin_does_not_get_special_tracking_visibility(self):
        request = self.factory.get("/api/tracking/")
        force_authenticate(request, user=self.superadmin)

        response = ApplicationTrackingListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        results = response.data.get("results") or []
        self.assertFalse(any(int(row.get("id")) == self.tracking.id for row in results))

    def test_regular_user_cannot_expand_company_visibility_with_scope_all(self):
        outsider = User.objects.create_user(username="company-outsider", email="company-outsider@example.com", password="x")
        outsider_profile = UserProfile.objects.create(user=outsider)
        Company.objects.create(profile=outsider_profile, name="outsider company")
        request = self.factory.get("/api/companies/?scope=all")
        force_authenticate(request, user=self.owner)

        response = CompanyListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        results = response.data.get("results") or []
        names = {str(row.get("name") or "") for row in results}
        self.assertIn("gamma", names)
        self.assertNotIn("outsider company", names)

    def test_regular_user_cannot_expand_employee_visibility_with_scope_all(self):
        outsider = User.objects.create_user(username="employee-outsider", email="employee-outsider@example.com", password="x")
        outsider_profile = UserProfile.objects.create(user=outsider)
        outsider_company = Company.objects.create(profile=outsider_profile, name="employee outsider company")
        Employee.objects.create(
            owner_profile=outsider_profile,
            company=outsider_company,
            name="Outsider Employee",
            department="Engineering",
            email="outsider@example.com",
        )
        request = self.factory.get("/api/employees/?scope=all")
        force_authenticate(request, user=self.owner)

        response = EmployeeListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        names = {str(row.get("name") or "") for row in response.data}
        self.assertIn("Casey", names)
        self.assertNotIn("Outsider Employee", names)


class TrackingDuplicateRulesTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="tracking-owner", password="x")
        self.profile = UserProfile.objects.create(user=self.user)
        self.company = Company.objects.create(profile=self.profile, name="delta", mail_format="{first}.{last}@delta.com")
        self.employee = Employee.objects.create(
            owner_profile=self.profile,
            company=self.company,
            name="Nina",
            department="HR",
            email="nina@delta.com",
            working_mail=True,
        )
        self.second_employee = Employee.objects.create(
            owner_profile=self.profile,
            company=self.company,
            name="Riya",
            department="HR",
            email="riya@delta.com",
            working_mail=True,
        )
        self.job = Job.objects.create(company=self.company, job_id="D-1", role="Backend Engineer", created_by=self.user)
        self.second_job = Job.objects.create(company=self.company, job_id="D-2", role="Frontend Engineer", created_by=self.user)
        self.resume = Resume.objects.create(profile=self.profile, title="Delta Resume")
        self.opening = Template.objects.create(profile=self.profile, name="Open", category="opening", achievement="Open text")
        self.experience = Template.objects.create(profile=self.profile, name="Experience", category="experience", achievement="Experience text")
        self.closing = Template.objects.create(profile=self.profile, name="Close", category="closing", achievement="Close text")
        self.existing = Tracking.objects.create(
            profile=self.profile,
            job=self.job,
            resume=self.resume,
            template=self.opening,
            template_ids_ordered=[self.opening.id, self.experience.id, self.closing.id],
            mail_type="fresh",
        )
        self.existing.selected_hrs.set([self.employee])

    def test_create_blocks_duplicate_fresh_tracking_for_same_job(self):
        request = self.factory.post(
            "/api/tracking/",
            {
                "company": self.company.id,
                "job": self.job.id,
                "resume": self.resume.id,
                "mail_type": "fresh",
                "selected_hr_ids": [self.employee.id],
                "template_ids_ordered": [self.opening.id, self.experience.id, self.closing.id],
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ApplicationTrackingListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Tracking already exists for", str(response.data.get("detail", "")))
        self.assertIn("single tracking row per company + job", str(response.data.get("detail", "")))

    def test_create_allows_fresh_tracking_for_same_company_different_job(self):
        request = self.factory.post(
            "/api/tracking/",
            {
                "company": self.company.id,
                "job": self.second_job.id,
                "resume": self.resume.id,
                "mail_type": "fresh",
                "selected_hr_ids": [self.second_employee.id],
                "template_ids_ordered": [self.opening.id, self.experience.id, self.closing.id],
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ApplicationTrackingListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 201)


class JobAccessControlTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.owner = User.objects.create_user(username="job-owner", email="job-owner@example.com", password="x")
        self.assignee = User.objects.create_user(username="job-assignee", email="job-assignee@example.com", password="x")
        self.outsider = User.objects.create_user(username="job-outsider", email="job-outsider@example.com", password="x")
        self.viewer = User.objects.create_user(username="job-viewer", email="job-viewer@example.com", password="x")

        self.owner_profile = UserProfile.objects.create(user=self.owner)
        self.outsider_profile = UserProfile.objects.create(user=self.outsider)
        self.viewer_profile = UserProfile.objects.create(user=self.viewer)

        job_crud_permissions = ("view_job", "add_job", "change_job", "delete_job")
        grant_job_permissions(self.owner, *job_crud_permissions)
        grant_job_permissions(self.assignee, *job_crud_permissions)
        grant_job_permissions(self.outsider, *job_crud_permissions)
        grant_job_permissions(self.viewer, *job_crud_permissions)

        view_all_permission = Permission.objects.get(codename="view_all_job")
        self.viewer.user_permissions.add(view_all_permission)

        self.owner_company = Company.objects.create(profile=self.owner_profile, name="owner company")
        self.outsider_company = Company.objects.create(profile=self.outsider_profile, name="outsider company")

        self.owner_job = Job.objects.create(
            company=self.owner_company,
            job_id="OWN-1",
            role="Owner Role",
            created_by=self.owner,
        )
        self.assigned_job = Job.objects.create(
            company=self.outsider_company,
            job_id="ASSIGN-1",
            role="Assigned Role",
            created_by=self.outsider,
        )
        self.assigned_job.assigned_to.add(self.assignee)
        self.outsider_job = Job.objects.create(
            company=self.outsider_company,
            job_id="OUT-1",
            role="Outsider Role",
            created_by=self.outsider,
        )

    def test_create_sets_created_by_automatically(self):
        request = self.factory.post(
            "/api/jobs/",
            {
                "company": self.owner_company.id,
                "job_id": "OWN-2",
                "role": "Created Role",
            },
            format="json",
        )
        force_authenticate(request, user=self.owner)

        response = JobListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 201)
        job = Job.objects.get(id=response.data["id"])
        self.assertEqual(job.created_by_id, self.owner.id)
        self.assertEqual(response.data["job_id"], "OWN-2")
        self.assertIn("company_name", response.data)

    def test_create_allows_blank_job_id(self):
        request = self.factory.post(
            "/api/jobs/",
            {
                "company": self.owner_company.id,
                "job_id": "",
                "role": "Created Without Job Id",
            },
            format="json",
        )
        force_authenticate(request, user=self.owner)

        response = JobListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 201)
        job = Job.objects.get(id=response.data["id"])
        self.assertEqual(job.job_id, "")

    def test_update_allows_blank_job_id(self):
        request = self.factory.put(
            f"/api/jobs/{self.owner_job.id}/",
            {
                "company": self.owner_job.company_id,
                "job_id": "",
                "role": "Owner Role",
            },
            format="json",
        )
        force_authenticate(request, user=self.owner)

        response = JobDetailView.as_view()(request, job_id=self.owner_job.id)

        self.assertEqual(response.status_code, 200)
        self.owner_job.refresh_from_db()
        self.assertEqual(self.owner_job.job_id, "")

    def test_list_returns_only_owned_or_assigned_jobs_without_global_permission(self):
        request = self.factory.get("/api/jobs/?scope=all")
        force_authenticate(request, user=self.assignee)

        response = JobListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        returned_ids = {int(row["id"]) for row in response.data.get("results") or []}
        self.assertEqual(returned_ids, {self.assigned_job.id})

    def test_list_returns_all_jobs_with_view_all_job_permission(self):
        request = self.factory.get("/api/jobs/?scope=all")
        force_authenticate(request, user=self.viewer)

        response = JobListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        returned_ids = {int(row["id"]) for row in response.data.get("results") or []}
        self.assertEqual(returned_ids, {self.owner_job.id, self.assigned_job.id, self.outsider_job.id})

    def test_detail_hides_unrelated_job_without_global_permission(self):
        request = self.factory.get(f"/api/jobs/{self.outsider_job.id}/")
        force_authenticate(request, user=self.owner)

        response = JobDetailView.as_view()(request, job_id=self.outsider_job.id)

        self.assertEqual(response.status_code, 404)

    def test_assignee_can_update_job(self):
        request = self.factory.put(
            f"/api/jobs/{self.assigned_job.id}/",
            {
                "company": self.assigned_job.company_id,
                "job_id": self.assigned_job.job_id,
                "role": "Updated By Assignee",
            },
            format="json",
        )
        force_authenticate(request, user=self.assignee)

        response = JobDetailView.as_view()(request, job_id=self.assigned_job.id)

        self.assertEqual(response.status_code, 200)
        self.assigned_job.refresh_from_db()
        self.assertEqual(self.assigned_job.role, "Updated By Assignee")

    def test_view_all_job_does_not_allow_delete_without_ownership(self):
        request = self.factory.delete(f"/api/jobs/{self.outsider_job.id}/")
        force_authenticate(request, user=self.viewer)

        response = JobDetailView.as_view()(request, job_id=self.outsider_job.id)

        self.assertEqual(response.status_code, 404)


class ExtensionJobCreateViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="ext-job-user", email="ext-job@example.com", password="x")
        self.profile = UserProfile.objects.create(user=self.user)
        self.company = Company.objects.create(profile=self.profile, name="ext company")

    def test_extension_create_allows_blank_job_id(self):
        request = self.factory.post(
            "/api/extension/jobs/",
            {
                "company_id": self.company.id,
                "job_id": "",
                "role": "Extension Role",
                "job_link": "https://example.com/jobs/123",
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ExtensionJobCreateView.as_view()(request)

        self.assertEqual(response.status_code, 201)
        created = Job.objects.get(id=response.data["job"]["id"])
        self.assertEqual(created.job_id, "")


class ExtensionLookupViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="ext-lookup-user", email="ext-lookup@example.com", password="x")
        self.profile = UserProfile.objects.create(user=self.user)
        self.other = User.objects.create_user(username="ext-lookup-other", email="ext-lookup-other@example.com", password="x")
        self.other_profile = UserProfile.objects.create(user=self.other)
        self.company = Company.objects.create(profile=self.profile, name="acme")
        Company.objects.create(profile=self.other_profile, name="acme")
        Company.objects.create(profile=self.profile, name="beta")
        Location.objects.create(name="Bengaluru")
        Location.objects.create(name="Hyderabad")
        Job.objects.create(company=self.company, role="Backend Engineer", job_link="https://example.com/backend")
        Job.objects.create(company=self.company, role="Backend Engineer", job_link="https://example.com/backend-2")
        Job.objects.create(company=self.company, role="Fullstack Engineer", job_link="https://example.com/fullstack")
        Employee.objects.create(
            owner_profile=self.profile,
            company=self.company,
            name="Recruiter One",
            JobRole="Talent Acquisition Specialist",
            department="HR",
            profile="https://linkedin.com/in/recruiter-one",
        )
        Employee.objects.create(
            owner_profile=self.profile,
            company=self.company,
            name="Engineer Two",
            JobRole="Hiring Manager",
            department="Engineering",
            profile="https://linkedin.com/in/engineer-two",
        )

    def test_extension_company_search_returns_unique_names(self):
        request = self.factory.get("/api/extension/companies/?q=")
        force_authenticate(request, user=self.user)

        response = ExtensionCompanySearchView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        names = [row["name"] for row in response.data.get("results") or []]
        self.assertEqual(names, ["acme", "beta"])

    def test_extension_form_meta_returns_unique_locations(self):
        request = self.factory.get("/api/extension/form-meta/")
        force_authenticate(request, user=self.user)

        response = ExtensionFormMetaView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        locations = [row["value"] for row in response.data.get("location_options") or []]
        self.assertEqual(locations, ["Bengaluru", "Hyderabad"])

    def test_extension_form_meta_returns_unique_roles_and_departments(self):
        request = self.factory.get("/api/extension/form-meta/")
        force_authenticate(request, user=self.user)

        response = ExtensionFormMetaView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        job_roles = [row["value"] for row in response.data.get("job_role_options") or []]
        employee_roles = [row["value"] for row in response.data.get("employee_role_options") or []]
        departments = [row["value"] for row in response.data.get("department_options") or []]
        self.assertEqual(job_roles, ["Backend Engineer", "Fullstack Engineer"])
        self.assertEqual(employee_roles, ["Hiring Manager", "Talent Acquisition Specialist"])
        self.assertEqual(departments, ["HR", "Engineering", "Other"])


class CompanyEmployeeAccessControlTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.owner = User.objects.create_user(username="owner-ce", email="owner-ce@example.com", password="x")
        self.outsider = User.objects.create_user(username="outsider-ce", email="outsider-ce@example.com", password="x")
        self.owner_profile = UserProfile.objects.create(user=self.owner)
        self.outsider_profile = UserProfile.objects.create(user=self.outsider)
        self.owner_company = Company.objects.create(profile=self.owner_profile, name="owner co")
        self.outsider_company = Company.objects.create(profile=self.outsider_profile, name="outsider co")
        self.owner_employee = Employee.objects.create(
            owner_profile=self.owner_profile,
            company=self.owner_company,
            name="Owner Employee",
            JobRole="Recruiter",
            department="HR",
            email="owner.employee@example.com",
        )

        grant_model_permissions(self.owner, "company", "view", "add", "change", "delete")
        grant_model_permissions(self.owner, "employee", "view", "add", "change", "delete")
        grant_model_permissions(self.outsider, "company", "view", "change", "delete")
        grant_model_permissions(self.outsider, "employee", "view", "change", "delete")

    def test_company_list_is_filtered_to_owner_even_with_scope_all(self):
        request = self.factory.get("/api/companies/?scope=all")
        force_authenticate(request, user=self.owner)

        response = CompanyListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        names = {str(row.get("name") or "") for row in response.data.get("results") or []}
        self.assertIn("owner co", names)
        self.assertNotIn("outsider co", names)

    def test_outsider_cannot_update_other_company(self):
        request = self.factory.put(
            f"/api/companies/{self.owner_company.id}/",
            {"name": "Changed"},
            format="json",
        )
        force_authenticate(request, user=self.outsider)

        response = CompanyDetailView.as_view()(request, company_id=self.owner_company.id)

        self.assertEqual(response.status_code, 404)

    def test_outsider_cannot_delete_other_employee(self):
        request = self.factory.delete(f"/api/employees/{self.owner_employee.id}/")
        force_authenticate(request, user=self.outsider)

        response = EmployeeDetailView.as_view()(request, employee_id=self.owner_employee.id)

        self.assertEqual(response.status_code, 404)


class ResumeSaveStorageTests(TestCase):
    def setUp(self):
        self._temp_media_dir = tempfile.mkdtemp(prefix="reactact-test-media-")
        self._override = override_settings(MEDIA_ROOT=self._temp_media_dir, MEDIA_URL="/media/")
        self._override.enable()
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="resume-owner", email="resume-owner@example.com", password="x")
        self.profile = UserProfile.objects.create(user=self.user)

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._temp_media_dir, ignore_errors=True)
        super().tearDown()

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
        old_file_name = str(resume.file.name or '').strip()
        self.assertTrue(resume.file.storage.exists(old_file_name))

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
        self.assertFalse(resume.file.storage.exists(old_file_name))

    def test_delete_resume_removes_existing_file_attachment(self):
        resume = Resume.objects.create(
            profile=self.profile,
            title="Delete Resume",
            original_text="Delete text",
            file=SimpleUploadedFile("delete-resume.pdf", b"%PDF-1.4 delete file", content_type="application/pdf"),
        )
        old_file_name = str(resume.file.name or '').strip()
        self.assertTrue(resume.file.storage.exists(old_file_name))

        request = self.factory.delete(f"/api/resumes/{resume.id}/")
        force_authenticate(request, user=self.user)

        response = ResumeDetailView.as_view()(request, resume_id=resume.id)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Resume.objects.filter(id=resume.id).exists())
        self.assertFalse(resume.file.storage.exists(old_file_name))


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

    def test_signup_serializer_adds_user_to_admin_group_when_present(self):
        Group.objects.create(name='admin')

        from analyzer.serializers import SignupSerializer

        serializer = SignupSerializer(
            data={
                'username': 'new-user',
                'email': 'new@example.com',
                'password': 'Testpass123!',
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertTrue(user.groups.filter(name__iexact='admin').exists())
        self.assertTrue(user.has_perm(DUMMY_DATA_PERMISSION))


class DummyWorkspaceSharingTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(username="viewer", password="x")
        self.profile = UserProfile.objects.create(user=self.user, full_name="Viewer")
        grant_dummy_data_permission(self.user)
        self.state = seed_shared_dummy_workspace()

    def test_seed_shared_dummy_workspace_creates_minimum_rows_for_each_panel(self):
        profile = self.state["profile"]

        self.assertGreaterEqual(Company.objects.filter(profile=profile).count(), 3)
        self.assertGreaterEqual(Employee.objects.filter(owner_profile=profile).count(), 3)
        self.assertGreaterEqual(Job.objects.filter(company__profile=profile).count(), 3)
        self.assertGreaterEqual(Tracking.objects.filter(profile=profile).count(), 3)
        self.assertGreaterEqual(Interview.objects.filter(profile=profile).count(), 3)
        self.assertGreaterEqual(ProfilePanel.objects.filter(profile=profile).count(), 3)
        self.assertGreaterEqual(Template.objects.filter(profile=profile, template_scope=Template.TEMPLATE_SCOPE_USER_BASED).count(), 3)
        self.assertGreaterEqual(SubjectTemplate.objects.filter(profile=profile).count(), 3)
        self.assertGreaterEqual(Resume.objects.filter(profile=profile).count(), 3)

    def test_profile_panel_list_includes_dummy_rows_when_user_has_permission(self):
        request = self.factory.get("/api/profile-panels/")
        force_authenticate(request, user=self.user)

        response = ProfilePanelListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        titles = {row["title"] for row in response.data}
        self.assertIn("Backend Outreach Profile", titles)
        self.assertIn("Full Stack Profile", titles)
        self.assertIn("Follow Up Profile", titles)

    def test_profile_panel_list_hides_dummy_rows_when_user_hides_dummy_data(self):
        self.profile.hide_dummy_data = True
        self.profile.save(update_fields=["hide_dummy_data", "updated_at"])

        request = self.factory.get("/api/profile-panels/")
        force_authenticate(request, user=self.user)
        response = ProfilePanelListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_profile_panel_list_hides_dummy_rows_when_admin_disables_shared_dummy_data(self):
        dummy_profile = self.state["profile"]
        dummy_profile.hide_shared_dummy_data = True
        dummy_profile.save(update_fields=["hide_shared_dummy_data", "updated_at"])

        request = self.factory.get("/api/profile-panels/")
        force_authenticate(request, user=self.user)
        response = ProfilePanelListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_subject_template_list_includes_dummy_subject_templates(self):
        request = self.factory.get("/api/subject-templates/")
        force_authenticate(request, user=self.user)

        response = SubjectTemplateListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        names = {row["name"] for row in response.data}
        self.assertIn("Demo Fresh Subject", names)
        self.assertIn("Demo Follow Up Subject", names)

    def test_shared_dummy_resume_cannot_be_updated_by_viewer(self):
        resume = Resume.objects.filter(profile=self.state["profile"]).order_by("id").first()
        request = self.factory.put(
            f"/api/resumes/{resume.id}/",
            {"title": "Attempted overwrite"},
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ResumeDetailView.as_view()(request, resume_id=resume.id)

        self.assertEqual(response.status_code, 404)
        resume.refresh_from_db()
        self.assertNotEqual(resume.title, "Attempted overwrite")


class DummyDataCommandTests(TestCase):
    def test_create_dummy_data_command_populates_core_models(self):
        call_command(
            "create_dummy_data",
            username="seed_user",
            password="seed12345",
            companies=2,
            employees_per_company=2,
            jobs_per_company=2,
        )

        user = User.objects.get(username="seed_user")
        profile = UserProfile.objects.get(user=user)

        self.assertTrue(Company.objects.filter(profile=profile).exists())
        self.assertTrue(Employee.objects.filter(owner_profile=profile).exists())
        self.assertTrue(Job.objects.filter(created_by=user).exists())
        self.assertTrue(Tracking.objects.filter(profile=profile).exists())
        self.assertTrue(Interview.objects.filter(profile=profile).exists())
        self.assertTrue(ProfilePanel.objects.filter(profile=profile).exists())
        self.assertTrue(SubjectTemplate.objects.filter(profile=profile).exists())
        self.assertTrue(Template.objects.filter(profile=profile, template_scope=Template.TEMPLATE_SCOPE_USER_BASED).exists())
        self.assertTrue(Template.objects.filter(template_scope=Template.TEMPLATE_SCOPE_SYSTEM).exists())
