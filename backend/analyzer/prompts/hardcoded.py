from __future__ import annotations


def build_cold_applied_mail(
    *,
    emp_name: str,
    personalized_intro: str,
    role: str,
    years_of_experience: str,
    skills_text: str,
    achievement_line: str,
    ask_line: str,
    sender_name: str,
    linkedin: str,
    email: str,
    contact: str,
    job_id: str = "",
    job_link: str = "",
) -> str:
    intro_role = role or "SDE"
    intro_yoe = str(years_of_experience or "3").strip() or "3"
    if intro_yoe.endswith("+"):
        intro_yoe = intro_yoe[:-1].strip() or "3"
    intro_skills = skills_text or "Python, React, MCP and AWS"

    body_parts = [
        f"Hi {emp_name},",
        "",
        str(personalized_intro or "").strip() or "I hope you are doing well.",
        "",
        (
            f"I recently applied for the {intro_role} role"
            f"{f' (Job ID: {job_id})' if str(job_id or '').strip() else ''} and wanted to reach out. "
            f"I'm a {intro_role} with {intro_yoe}+ years of experience in {intro_skills}, "
            "with hands-on experience in deploying and scaling backend services."
        ),
        "",
        str(achievement_line or "").strip() or "I have worked on backend systems with measurable product and performance impact.",
    ]

    if str(job_link or "").strip():
        body_parts.extend(["", f"Job Link: {job_link.strip()}"])

    body_parts.extend([
        "",
        str(ask_line or "").strip() or "Would you be open to sharing your perspective on my fit, or pointing me to the right person for this role?",
        "",
        "Thanks,",
        sender_name or "",
    ])

    if linkedin:
        body_parts.append(f"LinkedIn: {linkedin}")
    if email:
        body_parts.append(f"Email: {email}")
    if contact:
        body_parts.append(contact)
    return "\n".join([part for part in body_parts if part is not None])


def build_referral_mail(*, emp_name: str, role: str, company_name: str, job_link: str, linkedin: str, email: str, contact: str, sender_name: str) -> str:
    detail_lines = []
    if linkedin:
        detail_lines.append(f"LinkedIn: {linkedin}")
    if email:
        detail_lines.append(f"Email: {email}")
    if contact:
        detail_lines.append(f"Contact: {contact}")

    body_parts = [
        f"Hi {emp_name},",
        "",
        "I hope you are doing well.",
        "",
        f"I noticed that your company is currently hiring for {role or 'open'} positions, and I am very interested in exploring opportunities with the team. If you are open to it, I would truly appreciate your kind consideration for a referral for a suitable role.",
    ]
    if job_link:
        body_parts.extend(["", "Here is the job link for your reference:", f"Job Link: {job_link}"])
    if detail_lines:
        body_parts.extend(["", "I have attached my resume and shared my details below for quick reference:", *detail_lines])
    body_parts.extend([
        "",
        "Please let me know if you need any additional information from my side. I truly appreciate your time and support.",
        "",
        "Thank you very much.",
        "",
        f"Best regards,\n{sender_name}",
    ])
    return "\n".join(body_parts)


def build_follow_up_applied_mail(*, emp_name: str, employee_personalization: str, role: str, company_name: str, achievement_impact: str, closing_line: str, attachment_line: str, signature: str) -> str:
    body_core = (
        f"Hi {emp_name},\n\n"
        f"{employee_personalization}\n\n"
        f"I wanted to follow up on my application for the {role or 'role'} position at {company_name}.\n\n"
        f"{achievement_impact[:150].rstrip('.') }.\n\n"
        "I would appreciate any update you can share, or guidance on the next step."
    )
    return f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"


def build_follow_up_referral_mail(*, emp_name: str, role: str, company_name: str) -> str:
    return (
        f"Hi {emp_name},\n\n"
        f"just following up on my previous message regarding the referral for {role or 'Software Engineer'} at {company_name}. "
        "I completely understand you may be busy - whenever you get a moment, I'd really appreciate your help.\n"
        "Thank you again!"
    )


def build_follow_up_call_mail(*, emp_name: str, interaction_date: str, role: str, company_name: str, achievement_impact: str, closing_line: str, attachment_line: str, signature: str) -> str:
    body_core = (
        f"Hi {emp_name},\n\n"
        f"Thank you again for the call on {interaction_date}. We had discussed the {role or 'role'} opportunity at {company_name}.\n\n"
        f"I remain very interested in the {role or 'role'} position at {company_name}.\n"
        f"{achievement_impact[:140].rstrip('.') }.\n\n"
        "Could you please share whether my profile is shortlisted, and what the next step in the process will be?"
    )
    return f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"


def build_follow_up_interview_mail(*, emp_name: str, interaction_date: str, role: str, company_name: str, achievement_impact: str, closing_line: str, attachment_line: str, signature: str) -> str:
    body_core = (
        f"Hi {emp_name},\n\n"
        f"Thank you for taking the time to interview me on {interaction_date}.\n\n"
        f"I remain excited about the opportunity to contribute to the {role or 'role'} team at {company_name}.\n"
        f"{achievement_impact[:140].rstrip('.') }.\n\n"
        "Could you please share feedback from the interview and the next process/timeline?"
    )
    return f"{body_core}\n\n{closing_line}\n\n{attachment_line}\n\n{signature}"
