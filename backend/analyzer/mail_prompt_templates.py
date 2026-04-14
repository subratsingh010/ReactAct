from __future__ import annotations


def _tone_rules(recipient_role: str, recipient_department: str) -> str:
    role = str(recipient_role or "").strip().lower()
    dept = str(recipient_department or "").strip().lower()
    audience = f"{role} {dept}".strip()

    if any(key in audience for key in ["hr", "talent", "recruit", "people"]):
        return (
            "Tone guidance:\n"
            "- Keep tone warm and concise for HR/Talent audience.\n"
            "- Emphasize fit, process clarity, and recruiter-friendly communication.\n"
            "- Ask for referral guidance or routing to the right recruiter/hiring manager.\n"
        )
    if any(key in audience for key in ["manager", "team lead", "lead", "head"]):
        return (
            "Tone guidance:\n"
            "- Keep tone professional and outcome-focused for manager/team-lead audience.\n"
            "- Emphasize ownership, execution, and impact metrics.\n"
            "- Ask for perspective on team fit and whether they can direct you to the right contact.\n"
        )
    if any(key in audience for key in ["engineer", "developer", "sde", "software"]):
        return (
            "Tone guidance:\n"
            "- Keep tone peer-to-peer and technical for engineering audience.\n"
            "- Emphasize technical depth, architecture, performance, and delivery impact.\n"
            "- Ask for technical fit perspective and referral if appropriate.\n"
        )
    return (
        "Tone guidance:\n"
        "- Keep tone professional, polite, and concise.\n"
        "- Emphasize role fit and measurable impact.\n"
    )


def _cold_applied_structure_rules() -> str:
    return (
        "For template category cold_applied, enforce this body structure exactly:\n"
        "1) Personalized paragraph about employee.\n"
        "2) 'I recently applied...' paragraph with role, company name, and optional Job ID.\n"
        "3) Achievement-impact paragraph using profile/achievements data.\n"
        "4) Final ask paragraph.\n"
        "5) Always use dynamic values from context (do not invent values).\n"
    )


def _referral_structure_rules() -> str:
    return (
        "For template category referral, keep this structure:\n"
        "1) Personalized paragraph about employee.\n"
        "2) Role interest + optional Job ID.\n"
        "3) Relevant achievement-impact paragraph.\n"
        "4) Explicit referral ask paragraph.\n"
    )


def _job_inquire_structure_rules() -> str:
    return (
        "For template category job_inquire, keep this structure:\n"
        "1) Personalized paragraph about employee.\n"
        "2) Inquiry about role/team at company (do not mention Job ID).\n"
        "3) Relevant achievement-impact paragraph.\n"
        "4) Ask for guidance / next step.\n"
        "5) Always use dynamic role/department/company values from context.\n"
        "6) Keep it concise: target 70-110 words total, short sentences, no fluff.\n"
    )


def _custom_structure_rules() -> str:
    return (
        "For template category custom, follow any provided user custom message if available, "
        "while keeping tone concise and professional.\n"
    )


def _follow_up_applied_structure_rules() -> str:
    return (
        "For template category follow_up_applied, keep this structure:\n"
        "1) Personalized paragraph about employee.\n"
        "2) Mention you already applied for the role at company.\n"
        "3) One short achievement-impact paragraph.\n"
        "4) Polite follow-up ask for update or direction.\n"
        "5) Keep concise (90-140 words).\n"
    )


def _follow_up_call_structure_rules() -> str:
    return (
        "For template category follow_up_call, keep this structure:\n"
        "1) Thank them for the prior call/conversation with date.\n"
        "2) Briefly restate role interest at company.\n"
        "3) One short impact/fit line.\n"
        "4) Ask clearly whether profile is shortlisted and what next step is.\n"
        "5) Keep concise (80-130 words).\n"
        "6) Always use dynamic values from context: recipient name, company, and date.\n"
    )


def _follow_up_interview_structure_rules() -> str:
    return (
        "For template category follow_up_interview, keep this structure:\n"
        "1) Thank them for the interview with date.\n"
        "2) Reconfirm interest in role/team at company.\n"
        "3) One short impact/fit line.\n"
        "4) Ask for feedback and next process/timeline politely.\n"
        "5) Keep concise (80-130 words).\n"
        "6) Always use dynamic values from context: recipient name, company, and date.\n"
    )


def _rules_for_template_category(template_category: str) -> str:
    choice = str(template_category or "").strip().lower()
    if choice == "referral":
        return _referral_structure_rules()
    if choice == "job_inquire":
        return _job_inquire_structure_rules()
    if choice == "follow_up_applied":
        return _follow_up_applied_structure_rules()
    if choice == "follow_up_call":
        return _follow_up_call_structure_rules()
    if choice == "follow_up_interview":
        return _follow_up_interview_structure_rules()
    if choice == "custom":
        return _custom_structure_rules()
    return _cold_applied_structure_rules()


def build_tracking_mail_prompt(context: dict) -> str:
    template_category = str(context.get("template_category") or "cold_applied").strip().lower() or "cold_applied"
    mail_type = str(context.get("mail_type") or "fresh").strip().lower() or "fresh"
    employee_context = str(context.get("employee_context") or "").strip()
    achievements_block = str(context.get("achievements_block") or "").strip() or "- (none provided)"
    recipient_role = str(context.get("recipient_role") or "").strip()
    recipient_department = str(context.get("recipient_department") or "").strip()

    return (
        "Write a short, professional email.\n"
        f"Template category: {template_category} (one of cold_applied/referral/job_inquire/follow_up_applied/follow_up_call/follow_up_interview/custom).\n"
        f"Mail type: {mail_type} (fresh/followed_up).\n\n"
        "Rules:\n"
        "- Personalize to the recipient using employee context. If about is missing, personalize using role/department.\n"
        "- Mention 1-2 achievements most relevant to the job role.\n"
        "- Keep it concise (120-180 words) and specific.\n"
        "- End with a clear ask (referral / guidance / quick chat) appropriate to template category.\n"
        "- Do NOT include any signature/contact info (it will be appended separately).\n\n"
        f"{_tone_rules(recipient_role, recipient_department)}\n"
        f"{_rules_for_template_category(template_category)}\n"
        "Context:\n"
        f"Recipient name: {str(context.get('recipient_name') or 'there').strip()}\n"
        f"Company: {str(context.get('company_name') or 'your company').strip()}\n"
        f"Job role: {str(context.get('job_role') or '(unknown)').strip()}\n"
        f"Job ID: {str(context.get('job_id') or '(none)').strip()}\n"
        f"Job link: {str(context.get('job_link') or '(none)').strip()}\n\n"
        f"Interaction date: {str(context.get('interaction_date') or '(not provided)').strip()}\n\n"
        f"Recipient role: {recipient_role or '(unknown)'}\n"
        f"Recipient department: {recipient_department or '(unknown)'}\n\n"
        f"Candidate name: {str(context.get('candidate_name') or '').strip()}\n"
        f"Years of experience: {str(context.get('years_of_experience') or '(not provided)').strip()}\n"
        f"Current employer: {str(context.get('current_employer') or '(not provided)').strip()}\n"
        f"Profile summary: {str(context.get('profile_summary') or '(not provided)').strip()}\n\n"
        f"{employee_context}\n\n"
        "Candidate achievements:\n"
        f"{achievements_block}\n"
    )
