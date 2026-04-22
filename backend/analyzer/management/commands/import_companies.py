import json
from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError
from analyzer.models import Company, UserProfile


class Command(BaseCommand):
    help = "Import companies from JSON"

    def add_arguments(self, parser):
        parser.add_argument("json_path", type=str)
        parser.add_argument("--dry-run", action="store_true")

    def generate_mail_format(self, company_name):
        return f"{{firstname}}.{{lastname}}@{company_name}.com"

    def handle(self, *args, **options):
        json_path = options["json_path"]
        dry_run = options["dry_run"]

        # Load JSON
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                companies_data = json.load(f)
        except Exception as e:
            self.stderr.write(f"❌ JSON error: {e}")
            return

        # Get profile
        try:
            profile = UserProfile.objects.get(id=1)
        except UserProfile.DoesNotExist:
            self.stderr.write("❌ UserProfile id=1 not found")
            return

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for data in companies_data:
            raw_name = data.get("name")

            if not raw_name:
                skipped_count += 1
                self.stdout.write("⚠️ Skipped: missing name")
                continue

            # ✅ normalize (fix duplicate issue)
            name = raw_name.strip().lower()

            try:
                with transaction.atomic():

                    # ✅ find existing
                    company = Company.objects.filter(
                        name=name,
                        profile=profile
                    ).first()

                    created = False

                    if not company:
                        # ✅ create new
                        company = Company.objects.create(
                            name=name,
                            profile=profile
                        )
                        created = True

                    # ✅ generate default mail_format if missing
                    mail_format = data.get("mail_format")
                    if not mail_format:
                        mail_format = self.generate_mail_format(name)

                    if not dry_run:
                        company.mail_format = mail_format
                        company.career_url = data.get("career_url") or ""
                        company.workday_domain_url = data.get("workday_domain_url") or ""
                        company.linkedin_url = data.get("linkedin_url") or ""
                        company.save()

                    if created:
                        created_count += 1
                    else:
                        updated_count += 1

                    self.stdout.write(
                        f"{'DRY-RUN ' if dry_run else ''}"
                        f"{'Created' if created else 'Updated'}: {name}"
                    )

            except IntegrityError as e:
                skipped_count += 1
                self.stderr.write(f"❌ Integrity error ({name}): {e}")

            except Exception as e:
                skipped_count += 1
                self.stderr.write(f"❌ Unexpected error ({name}): {e}")

        # Summary
        self.stdout.write("\n===== SUMMARY =====")
        self.stdout.write(f"Created: {created_count}")
        self.stdout.write(f"Updated: {updated_count}")
        self.stdout.write(f"Skipped: {skipped_count}")