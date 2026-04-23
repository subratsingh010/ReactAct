from django.core.management.base import BaseCommand

from analyzer.default_mail_templates import ensure_default_mail_templates_for_profile
from analyzer.models import UserProfile


class Command(BaseCommand):
    help = "Seed default tracking templates and subject templates for existing profiles."

    def handle(self, *args, **options):
        template_total = 0
        subject_total = 0
        profile_total = 0

        for profile in UserProfile.objects.select_related("user").all().order_by("id"):
            result = ensure_default_mail_templates_for_profile(profile)
            template_total += int(result.get("templates_created") or 0)
            subject_total += int(result.get("subject_templates_created") or 0)
            profile_total += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded default mail templates for {profile_total} profile(s): "
                f"{template_total} template(s), {subject_total} subject template(s)."
            )
        )
