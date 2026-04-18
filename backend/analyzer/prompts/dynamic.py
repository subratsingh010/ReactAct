from __future__ import annotations


def _text(context: dict, key: str, default: str = "") -> str:
    return str((context or {}).get(key) or default).strip()


def _tone_rules(context: dict) -> str:
    role = _text(context, "recipient_role", "").lower()
    dept = _text(context, "recipient_department", "").lower()
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


def _prompt_shell(context: dict, template_category: str, structure_rules: str) -> str:
    recipient_role = _text(context, "recipient_role", "")
    recipient_department = _text(context, "recipient_department", "")
    employee_context = _text(context, "employee_context", "")
    achievements_block = _text(context, "achievements_block", "- (none provided)")

    return (
        "Write a short, professional email.\n"
        f"Template category: {template_category} "
        "(one of cold_applied/referral/job_inquire/follow_up_applied/follow_up_referral/follow_up_call/follow_up_interview/custom).\n"
        "\n"
        "Rules:\n"
        "- Personalize to the recipient using employee context. If about is missing, personalize using role/department.\n"
        "- Mention 1-2 achievements most relevant to the job role.\n"
        "- Keep it concise (120-180 words) and specific.\n"
        "- End with a clear ask (referral / guidance / quick chat) appropriate to template category.\n"
        "- Do NOT include any signature/contact info (it will be appended separately).\n\n"
        f"{_tone_rules(context)}\n"
        f"{structure_rules}\n"
        "Context:\n"
        f"Recipient name: {_text(context, 'recipient_name', 'there')}\n"
        f"Company: {_text(context, 'company_name', 'your company')}\n"
        f"Job role: {_text(context, 'job_role', '(unknown)')}\n"
        f"Job ID: {_text(context, 'job_id', '(none)')}\n"
        f"Job link: {_text(context, 'job_link', '(none)')}\n\n"
        f"Interaction date: {_text(context, 'interaction_date', '(not provided)')}\n\n"
        f"Recipient role: {recipient_role or '(unknown)'}\n"
        f"Recipient department: {recipient_department or '(unknown)'}\n\n"
        f"Candidate name: {_text(context, 'candidate_name', '')}\n"
        f"Years of experience: {_text(context, 'years_of_experience', '(not provided)')}\n"
        f"Current employer: {_text(context, 'current_employer', '(not provided)')}\n"
        f"Profile summary: {_text(context, 'profile_summary', '(not provided)')}\n\n"
        f"{employee_context}\n\n"
        "Candidate achievements:\n"
        f"{achievements_block}\n"
    )


def _follow_up_prompt_shell(context: dict, template_category: str, structure_rules: str) -> str:
    return (
        "Write a short, professional follow-up email for an existing thread.\n"
        f"Template category: {template_category}.\n\n"
        "Rules:\n"
        "- This is a reply/follow-up thread, so do not repeat too much background.\n"
        "- Keep it short and direct.\n"
        "- Use only minimal context needed: recipient name, role or job link, and interaction date if relevant.\n"
        "- Do NOT spend words describing the employee profile in detail.\n"
        "- Do NOT restate the full company/job background unless needed.\n"
        "- Do NOT include any signature/contact info (it will be appended separately).\n\n"
        f"{structure_rules}\n"
        "Minimal context:\n"
        f"Recipient name: {_text(context, 'recipient_name', 'there')}\n"
        f"Job role: {_text(context, 'job_role', '(unknown)')}\n"
        f"Job link: {_text(context, 'job_link', '(none)')}\n"
        f"Interaction date: {_text(context, 'interaction_date', '(not provided)')}\n"
    )


def _custom_prompt_shell(context: dict, template_category: str, structure_rules: str) -> str:
    return (
        "Write a short, professional email using the user's custom template intent.\n"
        f"Template category: {template_category}.\n\n"
        "Rules:\n"
        "- Keep only the recipient name as dynamic context.\n"
        "- Do not use extra job, company, employee-profile, or achievement context unless explicitly present in the custom message itself.\n"
        "- Do NOT include any signature/contact info (it will be appended separately).\n\n"
        f"{structure_rules}\n"
        "Minimal context:\n"
        f"Recipient name: {_text(context, 'recipient_name', 'there')}\n"
    )


class ColdAppliedPrompt:
    template_key = "cold_applied"
    def __init__(self, context: dict): self.context = context or {}
    def build(self) -> str:
        return _prompt_shell(self.context, self.template_key, (
            "For template category cold_applied, enforce this body structure exactly:\n"
            "1) Personalized paragraph about employee.\n"
            "   This first paragraph must be tightly personalized and limited to 30-35 words.\n"
            "2) 'I recently applied...' paragraph with role, company name, and optional Job ID.\n"
            "3) Achievement-impact paragraph using profile/achievements data.\n"
            "4) Final ask paragraph.\n"
            "5) Always use dynamic values from context (do not invent values).\n"
        ))


class ReferralPrompt:
    template_key = "referral"
    def __init__(self, context: dict): self.context = context or {}
    def build(self) -> str:
        return _prompt_shell(self.context, self.template_key, (
            "For template category referral, keep this structure:\n"
            "1) Personalized paragraph about employee.\n"
            "2) Role interest + optional Job ID.\n"
            "3) Relevant achievement-impact paragraph.\n"
            "4) Explicit referral ask paragraph.\n"
        ))


class JobInquiryPrompt:
    template_key = "job_inquire"
    def __init__(self, context: dict): self.context = context or {}
    def build(self) -> str:
        return _prompt_shell(self.context, self.template_key, (
            "For template category job_inquire, keep this structure:\n"
            "1) Personalized paragraph about employee.\n"
            "2) Inquiry about role/team at company (do not mention Job ID).\n"
            "3) Relevant achievement-impact paragraph.\n"
            "4) Ask for guidance / next step.\n"
            "5) Always use dynamic role/department/company values from context.\n"
            "6) Keep it concise: target 70-110 words total, short sentences, no fluff.\n"
        ))


class FollowUpAppliedPrompt:
    template_key = "follow_up_applied"
    def __init__(self, context: dict): self.context = context or {}
    def build(self) -> str:
        return _follow_up_prompt_shell(self.context, self.template_key, (
            "For template category follow_up_applied, keep this structure:\n"
            "1) Short greeting using recipient name.\n"
            "2) Mention you already applied for the role.\n"
            "3) Ask politely for update or direction.\n"
            "4) Keep concise (60-110 words).\n"
        ))


class FollowUpReferralPrompt:
    template_key = "follow_up_referral"
    def __init__(self, context: dict): self.context = context or {}
    def build(self) -> str:
        return _follow_up_prompt_shell(self.context, self.template_key, (
            "For template category follow_up_referral, keep this structure:\n"
            "1) Short greeting using recipient name.\n"
            "2) Mention brief follow-up on the previous referral request.\n"
            "3) Politely acknowledge they may be busy.\n"
            "4) Briefly ask for help when they get a moment.\n"
            "5) Keep concise (35-70 words).\n"
        ))


class FollowUpCallPrompt:
    template_key = "follow_up_call"
    def __init__(self, context: dict): self.context = context or {}
    def build(self) -> str:
        return _follow_up_prompt_shell(self.context, self.template_key, (
            "For template category follow_up_call, keep this structure:\n"
            "1) Thank them for the prior call/conversation with date.\n"
            "2) Briefly restate role interest if needed.\n"
            "3) Ask clearly whether profile is shortlisted and what next step is.\n"
            "4) Keep concise (60-110 words).\n"
        ))


class FollowUpInterviewPrompt:
    template_key = "follow_up_interview"
    def __init__(self, context: dict): self.context = context or {}
    def build(self) -> str:
        return _follow_up_prompt_shell(self.context, self.template_key, (
            "For template category follow_up_interview, keep this structure:\n"
            "1) Thank them for the interview with date.\n"
            "2) Reconfirm interest briefly if needed.\n"
            "3) Ask for feedback and next process/timeline politely.\n"
            "4) Keep concise (60-110 words).\n"
        ))


class CustomPrompt:
    template_key = "custom"
    def __init__(self, context: dict): self.context = context or {}
    def build(self) -> str:
        return _custom_prompt_shell(self.context, self.template_key, (
            "For template category custom, follow any provided user custom message if available, "
            "while keeping tone concise and professional.\n"
        ))


PROMPT_TEMPLATE_CLASSES = {
    "cold_applied": ColdAppliedPrompt,
    "referral": ReferralPrompt,
    "job_inquire": JobInquiryPrompt,
    "follow_up_applied": FollowUpAppliedPrompt,
    "follow_up_referral": FollowUpReferralPrompt,
    "follow_up_call": FollowUpCallPrompt,
    "follow_up_interview": FollowUpInterviewPrompt,
    "custom": CustomPrompt,
}


def build_tracking_mail_prompt(context: dict) -> str:
    template_category = _text(context, "template_category", "cold_applied").lower() or "cold_applied"
    prompt_class = PROMPT_TEMPLATE_CLASSES.get(template_category, ColdAppliedPrompt)
    return prompt_class(context or {}).build()
