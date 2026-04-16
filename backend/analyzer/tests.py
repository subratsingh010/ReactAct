from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from analyzer.management.commands.send_tracking_mails import Command
from analyzer.models import Company, Employee, Job, MailTrackingEvent, Resume, Template, Tracking, TrackingAction
from analyzer.serializers import CompanySerializer, InterviewSerializer, JobSerializer, ProfilePanelSerializer, UserProfileSerializer
from analyzer.tracking_mail_utils import ensure_mail_tracking
from analyzer.views import ApplicationTrackingDetailView, ApplicationTrackingMailTestView


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
        self.company = Company.objects.create(user=self.user, name="acme")
        self.employee = Employee.objects.create(
            user=self.user,
            company=self.company,
            name="Recruiter",
            email="hr@acme.com",
        )
        self.job = Job.objects.create(user=self.user, company=self.company, job_id="J-1", role="Engineer")
        self.resume = Resume.objects.create(user=self.user, title="Base Resume")
        self.tracking = Tracking.objects.create(
            user=self.user,
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


class TrackingFreshRuleApiTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ApplicationTrackingDetailView.as_view()
        self.user = User.objects.create_user(username="tracker", email="tracker@example.com", password="x")
        self.company = Company.objects.create(user=self.user, name="beta", mail_format="{first}@beta.com")
        self.employee_one = Employee.objects.create(
            user=self.user,
            company=self.company,
            name="Alice",
            department="Engineering",
            email="alice@beta.com",
        )
        self.employee_two = Employee.objects.create(
            user=self.user,
            company=self.company,
            name="Bob",
            department="Engineering",
            email="bob@beta.com",
        )
        self.job = Job.objects.create(user=self.user, company=self.company, job_id="J-2", role="Backend")
        self.resume = Resume.objects.create(user=self.user, title="Resume")
        self.template_opening = Template.objects.create(user=self.user, name="Opening", category="opening", achievement="Open")
        self.template_experience = Template.objects.create(user=self.user, name="Experience", category="experience", achievement="Exp")
        self.template_closing = Template.objects.create(user=self.user, name="Closing", category="closing", achievement="Close")
        self.tracking = Tracking.objects.create(
            user=self.user,
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
        self.company = Company.objects.create(user=self.owner, name="Acme")
        self.employee = Employee.objects.create(
            user=self.owner,
            company=self.company,
            name="Recruiter",
            email="recruiter@acme.com",
        )
        self.job = Job.objects.create(user=self.owner, company=self.company, job_id="AC-1", role="Backend")
        self.resume = Resume.objects.create(user=self.owner, title="Resume")
        self.tracking = Tracking.objects.create(
            user=self.owner,
            job=self.job,
            resume=self.resume,
            mail_type="fresh",
            use_hardcoded_personalized_intro=False,
        )
        self.tracking.selected_hrs.set([self.employee])
        from analyzer.models import WorkspaceMember
        WorkspaceMember.objects.create(owner=self.owner, member=self.member, is_active=True)

    def test_member_can_access_mail_test_for_owner_tracking(self):
        request = self.factory.get(f"/api/tracking/{self.tracking.id}/mail-test/")
        force_authenticate(request, user=self.member)

        response = ApplicationTrackingMailTestView.as_view()(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 200)

    def test_generate_reports_complete_ai_when_hardcoded_intro_disabled(self):
        request = self.factory.post(
            f"/api/tracking/{self.tracking.id}/mail-test/",
            {"action": "generate"},
            format="json",
        )
        force_authenticate(request, user=self.owner)

        response = ApplicationTrackingMailTestView.as_view()(request, tracking_id=self.tracking.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get("compose_mode"), "complete_ai")
        previews = response.data.get("previews") or []
        self.assertTrue(previews)
        self.assertEqual(previews[0].get("compose_mode"), "complete_ai")


class SerializerNormalizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="serializer-user", email="serializer@example.com", password="x")
        self.company = Company.objects.create(user=self.user, name="Serializer Co")

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
