import json
import os
import random
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import escape

from .profile_settings import resolve_openai_settings


BUZZWORDS = {
    "passionate",
    "ninja",
    "rockstar",
    "synergy",
    "guru",
    "dynamic",
    "go-getter",
    "world-class",
    "best-in-class",
    "cutting-edge",
    "cutting edge",
    "results-driven",
    "results driven",
    "results-oriented",
    "results oriented",
    "highly motivated",
    "self-motivated",
    "self motivated",
    "hard-working",
    "hardworking",
    "team player",
    "go above and beyond",
    "detail-oriented",
    "detail oriented",
    "excellent communication",
    "out-of-the-box",
    "out of the box",
    "visionary",
    "game-changing",
    "game changing",
    "proactive",
    "fast learner",
    "quick learner",
    "backend-heavy",
    "backend heavy",
    "frontend-heavy",
    "frontend heavy",
    "full-stack profile",
    "full stack profile",
}

ACTION_VERBS = [
    "Built",
    "Delivered",
    "Reduced",
    "Improved",
    "Automated",
    "Designed",
    "Implemented",
    "Optimized",
    "Migrated",
    "Launched",
    "Integrated",
    "Scaled",
    "Accelerated",
    "Streamlined",
    "Enhanced",
    "Refactored",
    "Developed",
    "Engineered",
    "Architected",
    "Created",
    "Formulated",
    "Established",
    "Deployed",
    "Orchestrated",
    "Directed",
    "Spearheaded",
    "Executed",
    "Drove",
    "Led",
    "Championed",
    "Modernized",
    "Stabilized",
    "Hardened",
    "Monitored",
    "Secured",
    "Instrumented",
    "Remediated",
    "Resolved",
    "Consolidated",
    "Standardized",
    "Simplified",
    "Reduced",
    "Boosted",
    "Strengthened",
    "Expanded",
    "Advanced",
    "Facilitated",
    "Managed",
    "Coordinated",
    "Validated",
    "Tested",
    "Migrated",
    "Integrated",
    "Automated",
    "Optimized",
    "Scaled",
    "Measured",
    "Quantified",
    "Revamped",
    "Overhauled",
    "Rebuilt",
    "Reworked",
    "Expedited",
]

SUMMARY_MIN_CHARS = 150
SUMMARY_MAX_CHARS = 250
BULLET_MAX_CHARS = 200
CURRENT_EXP_MIN_BULLETS = 5
CURRENT_EXP_MAX_BULLETS = 5
PAST_EXP_MIN_BULLETS = 3
PAST_EXP_MAX_BULLETS = 4
PROJECT_MIN_BULLETS = 3
PROJECT_MAX_BULLETS = 3
MAX_SKILL_CATEGORIES = 4
PERCENT_MIN = 5
PERCENT_MAX = 85
NON_NEGOTIABLE_SKILLS = ["python", "fastapi", "django", "mcp", "rag"]
ALLOWED_AI_MODELS = {
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.2",
    "gpt-5-nano",
    "o1",
    "gpt-4o",
}

COMMON_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "you",
    "your",
    "our",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "will",
    "must",
    "should",
    "can",
    "may",
    "etc",
    "job",
    "role",
    "team",
    "work",
    "working",
    "experience",
    "years",
    "year",
}


def _bullet_count_rules_text() -> str:
    return (
        "Bullet count rules: current role must have exactly 5 bullets, "
        "previous roles must have 3 to 4 bullets, each project must have exactly 3 bullets. "
    )


def _common_bullet_rules_text() -> str:
    return (
        "Rules: no buzzwords, no duplicate bullet statements, every bullet must include at least one concrete number/metric, "
        "and the starting action verb of each bullet must be globally unique. "
        "Each bullet must be at most 200 characters. "
        "Assume candidate profile is 3+ years only; avoid senior/staff/principal scope claims. "
        "If a bullet already indicates revenue gains or optimization impact, preserve that intent in the rewrite. "
        "Use percentage sparingly; prefer concrete counts, ranges, and float values when possible. "
        f"If using percentages, keep them in realistic range {PERCENT_MIN}% to {PERCENT_MAX}% and make them believable. "
        "Never introduce exceptional or outlier metrics that are hard to justify for a 3+ year profile. "
        "If using %, include baseline context when naturally available, and avoid artificial placeholders. "
    )


def _bullet_min_required_for_model(model_override: str | None = None) -> int:
    selected = _resolve_ai_model_name(model_override)
    # User rule: only gpt-5.4 can go below 100 chars; all others require >= 100.
    return 0 if selected == "gpt-5.4" else 100

KNOWN_TECH_TERMS = [
    "python",
    "java",
    "spring",
    "spring boot",
    "spring core",
    "django",
    "flask",
    "fastapi",
    "javascript",
    "typescript",
    "react",
    "node.js",
    "node",
    "next.js",
    "go",
    "rust",
    "html",
    "css",
    "tailwind",
    "redux",
    "rest",
    "rest api",
    "restful apis",
    "grpc",
    "api",
    "graphql",
    "postgresql",
    "postgres",
    "mysql",
    "sqlite",
    "mongodb",
    "redis",
    "qdrant",
    "chroma",
    "weaviate",
    "vector database",
    "docker",
    "kubernetes",
    "k3s",
    "aws",
    "gcp",
    "azure",
    "ci/cd",
    "jenkins",
    "github actions",
    "terraform",
    "linux",
    "git",
    "jwt",
    "oauth",
    "microservices",
    "celery",
    "rabbitmq",
    "kafka",
    "prometheus",
    "grafana",
    "elasticsearch",
    "openai",
    "llm",
    "llms",
    "rag",
    "langchain",
    "llamaindex",
    "scikit-learn",
    "pytorch",
    "tensorflow",
    "hugging face",
    "mlops",
    "mlflow",
    "kubeflow",
    "xgboost",
    "random forest",
    "gradient boosting",
    "logistic regression",
    "k-means",
    "pca",
    "anomaly detection",
    "asyncio",
    "pydantic",
    "mcp",
    "spring security",
    "jpa",
    "orm",
    "hibernate",
    "jsonb",
    "valkey",
    "design patterns",
    "ddd",
    "solid",
    "chatgpt",
    "gen ai",
    "agentic frameworks",
    "machine learning",
    "ai-driven apis",
    "messaging platforms",
]

PLACEHOLDER_SNIPPETS = [
    "write 3+ bullets",
    "write 3 bullets",
    "write three bullets",
    "add 2-3 bullet points",
    "add 2-3 bullets",
    "add 3-4 bullets",
    "add bullet points",
    "what you built",
    "what impact",
    "replace with your",
    "lorem ipsum",
]

KEYWORD_DISPLAY_OVERRIDES = {
    "python": "Python",
    "java": "Java",
    "c++": "C++",
    "node.js": "Node.js",
    "next.js": "Next.js",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "fastapi": "FastAPI",
    "openai": "OpenAI",
    "mcp": "MCP",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "react": "React",
    "html": "HTML",
    "css": "CSS",
    "ci/cd": "CI/CD",
    "aws": "AWS",
    "gcp": "GCP",
    "llm": "LLMs",
    "rag": "RAG",
    "api": "API",
    "apis": "APIs",
    "sql": "SQL",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "milvus": "Milvus",
    "prometheus": "Prometheus",
    "grafana": "Grafana",
    "loki": "Loki",
    "rabbitmq": "RabbitMQ",
    "celery": "Celery",
    "linux": "Linux",
    "docker": "Docker",
    "django": "Django",
    "flask": "Flask",
    "azure": "Azure",
    "git": "Git",
    "rest api": "REST API",
    "graphql": "GraphQL",
    "grpc": "gRPC",
    "asyncio": "AsyncIO",
    "pydantic": "Pydantic",
    "rust": "Rust",
    "k3s": "K3s",
    "qdrant": "Qdrant",
    "chroma": "Chroma",
    "weaviate": "Weaviate",
    "llamaindex": "LlamaIndex",
    "vector database": "Vector Databases",
    "soc 2": "SOC 2",
    "iso 27001": "ISO 27001",
    "on-prem deployment": "On-prem Deployment",
    "air-gapped network": "Air-gapped Network",
    "scikit-learn": "Scikit-learn",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "hugging face": "Hugging Face",
    "mlops": "MLOps",
    "mlflow": "MLflow",
    "kubeflow": "Kubeflow",
    "xgboost": "XGBoost",
    "random forest": "Random Forest",
    "gradient boosting": "Gradient Boosting",
    "logistic regression": "Logistic Regression",
    "k-means": "K-Means",
    "pca": "PCA",
    "anomaly detection": "Anomaly Detection",
    "spring security": "Spring Security",
    "jpa": "JPA",
    "orm": "ORM",
    "hibernate": "Hibernate",
    "jsonb": "JSONB",
    "valkey": "Valkey",
    "ddd": "DDD",
    "solid": "SOLID",
    "chatgpt": "ChatGPT",
    "gen ai": "Gen AI",
    "agentic frameworks": "Agentic Frameworks",
    "machine learning": "Machine Learning",
    "ai-driven apis": "AI-driven APIs",
    "messaging platforms": "Messaging Platforms",
}

REQUIRED_CORE_SKILLS = ["python", "fastapi", "mcp"]

SKILL_ALIAS_MAP = {
    "nodejs": "node.js",
    "node js": "node.js",
    "ci cd": "ci/cd",
    "cicd": "ci/cd",
    "llms": "llm",
    "postgres": "postgresql",
    "fast api": "fastapi",
    "open ai": "openai",
    "html5": "html",
    "css3": "css",
    "microsoft sql server": "sql",
    "ms sql server": "sql",
    "graphql api": "graphql",
    "grpc api": "grpc",
    "restful": "rest api",
    "restful api": "rest api",
    "rest": "rest api",
    "mcp protocol": "mcp",
    "soc2": "soc 2",
    "iso27001": "iso 27001",
    "k8s": "kubernetes",
    "vector databases": "vector database",
    "vector db": "vector database",
    "containerisation": "containerization",
    "llm apis": "llm api",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "hf": "hugging face",
    "java17": "java",
    "java 17": "java",
    "spring3": "spring",
    "spring 3": "spring",
    "react18": "react",
    "react 18": "react",
    "python3": "python",
    "python 3": "python",
    "restful apis": "rest api",
    "restful api": "rest api",
    "restful services": "rest api",
    "k8": "kubernetes",
    "k8s": "kubernetes",
    "genai": "gen ai",
    "agentic framework": "agentic frameworks",
    "ai driven apis": "ai-driven apis",
    "ai driven api": "ai-driven apis",
    "jpa/orm": "jpa",
    "orm/jpa": "orm",
    "microservice": "microservices",
    "design pattern": "design patterns",
    "solid principles": "solid",
    "domain-driven design": "ddd",
    "messaging platform": "messaging platforms",
}

SKILL_CATEGORY_RULES = [
    (
        "ML/AI",
        {
            "scikit-learn",
            "pytorch",
            "tensorflow",
            "hugging face",
            "mlops",
            "mlflow",
            "kubeflow",
            "xgboost",
            "random forest",
            "gradient boosting",
            "logistic regression",
            "k-means",
            "pca",
            "anomaly detection",
        },
    ),
    (
        "Languages",
        {
            "python",
            "java",
            "javascript",
            "typescript",
            "sql",
            "c++",
            "c#",
            "go",
            "rust",
            "ruby",
            "php",
            "html",
            "css",
        },
    ),
    (
        "Frameworks",
        {
            "fastapi",
            "django",
            "flask",
            "react",
            "next.js",
            "node.js",
            "spring",
            "spring boot",
            "spring core",
            "express",
            "angular",
            "vue",
            "rest api",
            "graphql",
            "grpc",
            "asyncio",
            "pydantic",
            "spring security",
            "jpa",
            "orm",
            "hibernate",
            "microservices",
        },
    ),
    (
        "GenAI/Agentic AI",
        {
            "rag",
            "llm",
            "langchain",
            "langgraph",
            "openai",
            "mcp",
            "llamaindex",
            "chatgpt",
            "gen ai",
            "agentic frameworks",
            "machine learning",
            "ai-driven apis",
        },
    ),
    (
        "Databases",
        {
            "postgresql",
            "mysql",
            "mongodb",
            "redis",
            "valkey",
            "milvus",
            "sqlite",
            "qdrant",
            "chroma",
            "weaviate",
            "vector database",
            "jsonb",
        },
    ),
    (
        "Cloud & DevOps",
        {
            "aws",
            "gcp",
            "azure",
            "docker",
            "kubernetes",
            "ci/cd",
            "git",
            "linux",
            "terraform",
            "jenkins",
            "github actions",
            "k3s",
            "messaging platforms",
        },
    ),
    (
        "Monitoring & Messaging",
        {
            "prometheus",
            "grafana",
            "loki",
            "rabbitmq",
            "celery",
            "kafka",
            "sqs",
        },
    ),
]

ALLOWED_SKILL_TOKENS = {
    skill
    for _, skills in SKILL_CATEGORY_RULES
    for skill in skills
}

LOW_VALUE_SKILL_TOKENS = {
    "backend engineering",
    "system design",
    "distributed systems",
    "job queues",
    "async processing",
    "caching",
    "failure handling",
    "api design",
    "containerization",
    "llm api",
    "security-hardened api design",
    "enterprise security",
    "compliance requirements",
}

ALLOWED_LONG_OTHER_TOKENS = {
    "on-prem deployment",
    "air-gapped network",
    "soc 2",
    "iso 27001",
}

SKILL_TOKEN_BLOCKLIST = {
    "skills",
    "skill",
    "tech stack",
    "technologies used",
    "technology",
    "technologies",
    "tools",
    "frameworks",
    "languages",
    "databases",
    "cloud",
    "devops",
    "monitoring",
    "messaging",
    "genai",
    "agentic ai",
}

BACKEND_FOCUS_SKILLS = {
    "python",
    "java",
    "fastapi",
    "django",
    "flask",
    "spring",
    "spring boot",
    "spring core",
    "node.js",
    "sql",
    "mysql",
    "postgresql",
    "mongodb",
    "redis",
    "sqlite",
    "aws",
    "gcp",
    "azure",
    "docker",
    "kubernetes",
    "linux",
    "ci/cd",
    "terraform",
    "jenkins",
    "github actions",
    "rabbitmq",
    "celery",
    "kafka",
    "jwt",
    "oauth",
    "microservices",
    "prometheus",
    "grafana",
    "loki",
    "openai",
    "llm",
    "rag",
    "langchain",
    "langgraph",
    "mcp",
}

FRONTEND_FOCUS_SKILLS = {
    "javascript",
    "typescript",
    "react",
    "next.js",
    "html",
    "css",
    "tailwind",
    "redux",
    "vue",
    "angular",
    "node.js",
}

AI_SIGNAL_SKILLS = {"openai", "llm", "rag", "langchain", "langgraph", "mcp"}

BACKEND_WEB_SIGNAL_SKILLS = BACKEND_FOCUS_SKILLS - AI_SIGNAL_SKILLS

OTHER_ROLE_HINTS = {
    "analyst",
    "analysis",
    "data scientist",
    "data science",
    "machine learning",
    "ml engineer",
    "ai engineer",
    "qa engineer",
    "test engineer",
    "support engineer",
}

SOFTWARE_ROLE_HINTS = {
    "software developer",
    "software engineer",
    "backend",
    "front-end",
    "frontend",
    "full-stack",
    "full stack",
    "web developer",
    "application developer",
}

NON_SOFTWARE_ROLE_HINTS = {
    "data scientist",
    "data science",
    "data analyst",
    "machine learning",
    "ml engineer",
    "ai engineer",
    "analytics",
    "research scientist",
    "business analyst",
}


def plain_text_from_html(value: str) -> str:
    t = str(value or "")
    t = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_placeholder_text(value: str) -> bool:
    low = plain_text_from_html(value).strip().lower()
    if not low:
        return True
    if any(snippet in low for snippet in PLACEHOLDER_SNIPPETS):
        return True
    if re.fullmatch(r"(write|add|include|replace)\b[\w\s,+/%-]{0,90}", low):
        return True
    return False


def _is_meaningful_entry(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    values = []
    for key in ["company", "title", "name", "institution", "program", "scoreValue", "highlights", "content"]:
        raw = entry.get(key)
        text = plain_text_from_html(raw) if key in {"highlights", "content"} else str(raw or "").strip()
        if text and not is_placeholder_text(text):
            values.append(text)
    return bool(values)


def sanitize_builder_data(builder_data: dict) -> dict:
    source = json.loads(json.dumps(builder_data or {}))

    for key in ["summary", "skills"]:
        value = source.get(key)
        text = plain_text_from_html(value) if key in {"summary", "skills"} else str(value or "").strip()
        if is_placeholder_text(text):
            source[key] = ""

    experiences = []
    for exp in source.get("experiences") or []:
        if not isinstance(exp, dict):
            continue
        highlights = plain_text_from_html(exp.get("highlights") or "")
        has_core = any(str(exp.get(k) or "").strip() for k in ["company", "title"])
        if has_core or (highlights and not is_placeholder_text(highlights)):
            if is_placeholder_text(highlights):
                exp["highlights"] = ""
            experiences.append(exp)
    source["experiences"] = experiences

    projects = []
    for proj in source.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        highlights = plain_text_from_html(proj.get("highlights") or "")
        name = str(proj.get("name") or "").strip()
        if (name and not is_placeholder_text(name)) or (highlights and not is_placeholder_text(highlights)):
            if is_placeholder_text(highlights):
                proj["highlights"] = ""
            projects.append(proj)
    source["projects"] = projects

    educations = []
    for edu in source.get("educations") or []:
        if not isinstance(edu, dict):
            continue
        if any(str(edu.get(k) or "").strip() for k in ["institution", "program", "scoreValue"]):
            educations.append(edu)
    source["educations"] = educations

    custom_sections = []
    for item in source.get("customSections") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        content = plain_text_from_html(item.get("content") or "")
        if title or (content and not is_placeholder_text(content)):
            custom_sections.append(item)
    source["customSections"] = custom_sections

    return source


def builder_has_substance(builder_data: dict) -> bool:
    data = sanitize_builder_data(builder_data or {})
    summary = plain_text_from_html(data.get("summary") or "")
    skills = plain_text_from_html(data.get("skills") or "")
    if summary and not is_placeholder_text(summary):
        return True
    if skills and not is_placeholder_text(skills):
        return True
    for key in ["experiences", "projects", "educations", "customSections"]:
        entries = data.get(key) or []
        if any(_is_meaningful_entry(item) for item in entries):
            return True
    return False


def format_keyword_display(keyword: str) -> str:
    key = _normalize_keyword(keyword)
    if not key:
        return ""
    if key in KEYWORD_DISPLAY_OVERRIDES:
        return KEYWORD_DISPLAY_OVERRIDES[key]
    return " ".join(part.capitalize() for part in key.split(" "))


def builder_data_to_text(builder_data: dict) -> str:
    data = sanitize_builder_data(builder_data or {})
    parts = []
    for key in ["fullName", "location", "phone", "email", "resumeTitle"]:
        v = str(data.get(key, "") or "").strip()
        if v:
            parts.append(v)

    summary = plain_text_from_html(data.get("summary") or "")
    if summary:
        parts.append(summary)

    skills = plain_text_from_html(data.get("skills") or "")
    if skills:
        parts.append(skills)

    for exp in data.get("experiences") or []:
        company = str(exp.get("company") or "").strip()
        title = str(exp.get("title") or "").strip()
        dates = " ".join([str(exp.get("startDate") or "").strip(), str(exp.get("endDate") or "").strip()]).strip()
        head = " | ".join([p for p in [company, title, dates] if p])
        if head:
            parts.append(head)
        highlights = plain_text_from_html(exp.get("highlights") or "")
        if highlights and not is_placeholder_text(highlights):
            parts.append(highlights)

    for proj in data.get("projects") or []:
        name = str(proj.get("name") or "").strip()
        if name:
            parts.append(name)
        highlights = plain_text_from_html(proj.get("highlights") or "")
        if highlights and not is_placeholder_text(highlights):
            parts.append(highlights)

    for edu in data.get("educations") or []:
        inst = str(edu.get("institution") or "").strip()
        program = str(edu.get("program") or "").strip()
        if inst or program:
            parts.append(" | ".join([p for p in [inst, program] if p]))

    return "\n".join([p for p in [p.strip() for p in parts] if p])


def extract_bullets_from_html(value: str):
    raw = str(value or "")
    if not raw.strip():
        return []
    li_matches = re.findall(r"<li[^>]*>([\s\S]*?)</li>", raw, flags=re.I)
    if li_matches:
        bullets = []
        for item in li_matches:
            cleaned = plain_text_from_html(item).lstrip("-• ").strip()
            if cleaned:
                bullets.append(cleaned)
        return bullets

    raw = re.sub(r"</li>\s*<li[^>]*>", "\n", raw, flags=re.I)
    raw = raw.replace("</li>", "\n")
    raw = re.sub(r"<li[^>]*>", "", raw, flags=re.I)
    text = plain_text_from_html(raw)
    lines = [ln.strip() for ln in re.split(r"[\n\r]+", text) if ln.strip()]
    bullets = []
    for ln in lines:
        cleaned = ln.lstrip("-• ").strip()
        if cleaned:
            bullets.append(cleaned)
    return bullets


def bullets_to_html(bullets):
    items = [f"<li>{escape(str(line).strip())}</li>" for line in bullets if str(line).strip()]
    return f"<ul>{''.join(items)}</ul>" if items else "<ul><li>Improved delivery time by 20%.</li></ul>"


def _dedupe_keep_order(items):
    seen = set()
    out = []
    for item in items:
        key = str(item).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(item).strip())
    return out


def _normalize_keyword(text: str) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = value.strip(",.;:()[]{} ")
    return value


def _canonicalize_skill_token(text: str) -> str:
    token = _normalize_keyword(text)
    if not token:
        return ""
    return SKILL_ALIAS_MAP.get(token, token)


def _is_low_value_skill_token(token: str) -> bool:
    value = _canonicalize_skill_token(token)
    if not value:
        return True
    if value in LOW_VALUE_SKILL_TOKENS:
        return True
    # Drop broad multi-word phrases unless explicitly allowed.
    if len(value.split()) > 2 and value not in ALLOWED_LONG_OTHER_TOKENS:
        return True
    return False


def _is_technical_skill_token(token: str) -> bool:
    value = _canonicalize_skill_token(token)
    if not value:
        return False
    if _is_low_value_skill_token(value):
        return False
    if value in ALLOWED_SKILL_TOKENS:
        return True
    if value in KNOWN_TECH_TERMS:
        return True
    # Allow a narrow set of technical terms that may be categorized as "Other".
    return value in {
        "on-prem deployment",
        "air-gapped network",
        "soc 2",
        "iso 27001",
    }


def _infer_role_from_jd(jd_text: str) -> str:
    text = str(jd_text or "")
    if not text.strip():
        return ""
    lowered = text.lower()

    match = re.search(r"\bas a[n]?\s+([A-Za-z][A-Za-z/& -]{2,80})\b", text, flags=re.I)
    if match:
        role = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;")
        role = re.sub(r"\bwithin\b.*$", "", role, flags=re.I).strip(" .,:;")
        if role:
            return role

    patterns = [
        (r"\bdata scientist associate\b", "Data Scientist Associate"),
        (r"\bdata scientist\b", "Data Scientist"),
        (r"\bmachine learning engineer\b", "Machine Learning Engineer"),
        (r"\bml engineer\b", "Machine Learning Engineer"),
        (r"\bai engineer\b", "AI Engineer"),
        (r"\bbackend engineer\b", "Backend Engineer"),
        (r"\bfrontend engineer\b", "Frontend Engineer"),
        (r"\bfull[\s-]?stack\b", "Full-stack Engineer"),
        (r"\bsoftware engineer\b", "Software Engineer"),
        (r"\bsoftware developer\b", "Software Developer"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, lowered, flags=re.I):
            return label
    return ""


def _normalize_experience_role_title(inferred_role: str) -> str:
    role = re.sub(r"\s+", " ", str(inferred_role or "").strip())
    if not role:
        return ""
    lowered = role.lower()
    if any(marker in lowered for marker in ("backend", "frontend", "front-end", "full-stack", "full stack")):
        return "Software Developer"
    if lowered in {"software engineer", "software developer", "developer", "engineer"}:
        return "Software Developer"
    return role


def _is_software_track_role(role_text: str, jd_text: str = "") -> bool:
    role_low = str(role_text or "").strip().lower()
    jd_low = str(jd_text or "").strip().lower()
    combined = f"{role_low} {jd_low}".strip()

    if any(hint in role_low for hint in SOFTWARE_ROLE_HINTS):
        return True
    if any(hint in role_low for hint in NON_SOFTWARE_ROLE_HINTS):
        return False

    software_hits = sum(1 for hint in SOFTWARE_ROLE_HINTS if hint in combined)
    non_software_hits = sum(1 for hint in NON_SOFTWARE_ROLE_HINTS if hint in combined)
    if non_software_hits > software_hits:
        return False
    if software_hits > 0:
        return True
    return False


def _ensure_summary_three_plus(summary: str) -> str:
    value = re.sub(r"\s+", " ", str(summary or "").strip())
    if not value:
        return value
    value = re.sub(r"\b\d+\+?\s*(?:years?|yrs?)\b", "3+ years", value, flags=re.I)
    if "3+ years" not in value.lower():
        value = value.rstrip(".")
        value = f"{value} with 3+ years of experience".strip()
    return re.sub(r"\s+", " ", value).strip()


def _extract_skill_tokens_from_html(html_value: str):
    text = plain_text_from_html(html_value or "")
    if not text:
        return []
    for label, _ in SKILL_CATEGORY_RULES:
        text = re.sub(rf"\b{re.escape(label)}\s*:", " ", text, flags=re.I)

    def extract_from_part(raw_part: str):
        raw = str(raw_part or "").strip(" .:-")
        if not raw:
            return []

        direct = _canonicalize_skill_token(raw)
        if direct in ALLOWED_SKILL_TOKENS:
            return [direct]

        normalized = _normalize_keyword(raw)
        words = re.findall(r"[a-z0-9+.#/]+", normalized)
        if not words:
            return []

        out = []
        i = 0
        while i < len(words):
            matched = False
            max_n = min(3, len(words) - i)
            for n in range(max_n, 0, -1):
                phrase = " ".join(words[i : i + n])
                token = _canonicalize_skill_token(phrase)
                if token in ALLOWED_SKILL_TOKENS:
                    out.append(token)
                    i += n
                    matched = True
                    break
            if not matched:
                i += 1
        out = _dedupe_keep_order(out)
        if out:
            return out

        fallback = _canonicalize_skill_token(raw)
        if not fallback or fallback in SKILL_TOKEN_BLOCKLIST:
            return []
        if _is_low_value_skill_token(fallback):
            return []
        if re.fullmatch(r"[a-z0-9+.#/& -]{2,40}", fallback):
            return [fallback]
        return []

    tokens = []
    for part in re.split(r"[,\n;|]+", text):
        raw = str(part or "").strip()
        if not raw:
            continue
        for token in extract_from_part(raw):
            if token in SKILL_TOKEN_BLOCKLIST:
                continue
            if _is_low_value_skill_token(token):
                continue
            tokens.append(token)
    return _dedupe_keep_order(tokens)


def _build_categorized_skills_html(tokens):
    normalized = _dedupe_keep_order(
        [
            _canonicalize_skill_token(x)
            for x in tokens
            if _canonicalize_skill_token(x) and not _is_low_value_skill_token(x)
        ]
    )
    if not normalized:
        return ""

    buckets = {label: [] for label, _ in SKILL_CATEGORY_RULES}
    other_bucket = []
    for token in normalized:
        assigned = False
        for label, allowed in SKILL_CATEGORY_RULES:
            if token in allowed:
                buckets[label].append(token)
                assigned = True
                break
        if not assigned:
            if _is_low_value_skill_token(token):
                continue
            other_bucket.append(token)

    # Keep at most 4 rows total. Prefer stable core categories first;
    # use "Other" only when tokens cannot be fit cleanly.
    category_index = {label: idx for idx, (label, _) in enumerate(SKILL_CATEGORY_RULES)}
    populated = [
        (label, _dedupe_keep_order(buckets.get(label) or []))
        for label, _ in SKILL_CATEGORY_RULES
        if buckets.get(label)
    ]

    populated_map = {label: values for label, values in populated}
    preferred_order = ["Languages", "Frameworks", "GenAI/Agentic AI", "Cloud & DevOps", "Databases"]
    selected_order = []

    for label in preferred_order:
        if label in populated_map and label not in selected_order and len(selected_order) < max(0, MAX_SKILL_CATEGORIES - 1):
            selected_order.append(label)

    remaining_ranked = [
        label
        for label, _ in sorted(
            populated,
            key=lambda item: (-len(item[1]), category_index[item[0]]),
        )
        if label not in selected_order
    ]
    for label in remaining_ranked:
        if len(selected_order) >= max(0, MAX_SKILL_CATEGORIES - 1):
            break
        selected_order.append(label)

    selected_labels = set(selected_order)
    for label, values in populated:
        if label in selected_labels:
            continue
        other_bucket.extend(values)

    items = []
    for label in selected_order:
        if label not in selected_labels:
            continue
        values = populated_map.get(label) or []
        display = ", ".join(format_keyword_display(v) for v in values if v)
        if display:
            items.append(f"<li><strong>{escape(label)}:</strong> {escape(display)}</li>")

    other_values = _dedupe_keep_order(other_bucket)
    if other_values:
        other_display = ", ".join(format_keyword_display(v) for v in other_values if v)
        if other_display:
            items.append(f"<li><strong>Other:</strong> {escape(other_display)}</li>")

    return f"<ul>{''.join(items)}</ul>" if items else ""


def _normalize_for_skill_match(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _canonical_bullet_key(text: str) -> str:
    value = _normalize_for_skill_match(text)
    value = re.sub(r"\b\d+(?:\.\d+)?\b", "<num>", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _next_unique_action_verb(used_verbs) -> str:
    used = {str(v).lower() for v in (used_verbs or set())}
    for verb in ACTION_VERBS:
        if verb.lower() not in used:
            return verb
    # Fallback should still be a verb and distinct enough.
    return "Executed"


def _text_mentions_any_skill(text: str, skill_tokens) -> bool:
    haystack = f" {_normalize_for_skill_match(text)} "
    if not haystack.strip():
        return False
    for token in skill_tokens or []:
        normalized_token = _normalize_for_skill_match(token)
        if normalized_token and f" {normalized_token} " in haystack:
            return True
    return False


def _ensure_non_negotiable_skills(skill_tokens):
    normalized = _dedupe_keep_order(
        [
            _canonicalize_skill_token(x)
            for x in (skill_tokens or [])
            if _canonicalize_skill_token(x)
        ]
    )
    must_have = _dedupe_keep_order(
        [
            _canonicalize_skill_token(x)
            for x in NON_NEGOTIABLE_SKILLS
            if _canonicalize_skill_token(x)
        ]
    )
    return _dedupe_keep_order([*normalized, *must_have])


def _is_agentic_project_signal(name: str, bullets) -> bool:
    haystack = " ".join(
        [
            str(name or ""),
            *[str(x or "") for x in (bullets or [])],
        ]
    ).lower()
    return bool(
        re.search(
            r"\b(agentic|agent|llm|rag|langchain|langgraph|openai|mcp|support agent|assistant)\b",
            haystack,
        )
    )


def _ensure_second_project_mcp_if_agentic(projects, used_verbs=None, seen_bullets=None):
    if not isinstance(projects, list) or len(projects) < 2:
        return projects
    second = projects[1]
    if not isinstance(second, dict):
        return projects
    current_bullets = extract_bullets_from_html(second.get("highlights") or "")
    if not _is_agentic_project_signal(second.get("name") or "", current_bullets):
        return projects
    normalized = _ensure_skill_coverage_in_bullets(
        current_bullets,
        ["mcp"],
        min_count=PROJECT_MIN_BULLETS,
        max_count=PROJECT_MAX_BULLETS,
        used_verbs=used_verbs,
        seen_bullets=seen_bullets,
    )
    second["highlights"] = bullets_to_html(normalized)
    projects[1] = second
    return projects


def _infer_resume_focus(jd_text: str, skill_tokens):
    text = str(jd_text or "").lower()
    backend_score = 0
    frontend_score = 0
    ai_score = 0

    for token in skill_tokens or []:
        canonical = _canonicalize_skill_token(token)
        if canonical in BACKEND_WEB_SIGNAL_SKILLS:
            backend_score += 1
        if canonical in FRONTEND_FOCUS_SKILLS:
            frontend_score += 1
        if canonical in AI_SIGNAL_SKILLS:
            ai_score += 1

    backend_mentions = len(re.findall(r"\b(back[\s-]?end|server[\s-]?side|api|microservice)\b", text))
    frontend_mentions = len(re.findall(r"\b(front[\s-]?end|client[\s-]?side|ui|ux|web)\b", text))
    backend_score += backend_mentions
    frontend_score += frontend_mentions

    explicit_backend = bool(re.search(r"\b(back[\s-]?end|server[\s-]?side)\b", text))
    explicit_frontend = bool(re.search(r"\b(front[\s-]?end|client[\s-]?side)\b", text))
    explicit_fullstack = bool(re.search(r"\b(full[\s-]?stack)\b", text))
    has_other_hint = any(hint in text for hint in OTHER_ROLE_HINTS)

    if explicit_backend and not explicit_frontend and not explicit_fullstack:
        mode = "backend_heavy"
    elif explicit_frontend and not explicit_backend and not explicit_fullstack:
        mode = "frontend_heavy"
    elif explicit_fullstack:
        if backend_score > 0 and frontend_score > 0:
            ratio = backend_score / max(1, frontend_score)
            if ratio >= 1.35:
                mode = "backend_heavy"
            elif ratio <= 0.74:
                mode = "frontend_heavy"
            else:
                mode = "balanced"
        else:
            mode = "balanced"
    elif backend_score > 0 and frontend_score > 0:
        ratio = backend_score / max(1, frontend_score)
        if ratio >= 1.35:
            mode = "backend_heavy"
        elif ratio <= 0.74:
            mode = "frontend_heavy"
        else:
            mode = "balanced"
    elif backend_score > 0:
        mode = "backend_heavy"
    elif frontend_score > 0:
        mode = "frontend_heavy"
    elif ai_score > 0:
        mode = "other"
    else:
        mode = "other" if has_other_hint else "balanced"

    return {
        "mode": mode,
        "backend_score": backend_score,
        "frontend_score": frontend_score,
        "ai_score": ai_score,
    }


def _prioritize_skills_for_focus(skill_tokens, focus_mode: str):
    normalized = _dedupe_keep_order([_canonicalize_skill_token(x) for x in skill_tokens or [] if _canonicalize_skill_token(x)])
    if not normalized:
        return []

    backend = [s for s in normalized if s in BACKEND_FOCUS_SKILLS]
    frontend = [s for s in normalized if s in FRONTEND_FOCUS_SKILLS]
    neutral = [s for s in normalized if s not in BACKEND_FOCUS_SKILLS and s not in FRONTEND_FOCUS_SKILLS]

    def take(seq, n):
        return seq[: max(0, n)]

    ordered = []
    if focus_mode == "backend_heavy":
        ordered = [*take(backend, 8), *take(frontend, 3), *take(neutral, 3)]
    elif focus_mode == "frontend_heavy":
        ordered = [*take(frontend, 8), *take(backend, 3), *take(neutral, 3)]
    elif focus_mode == "balanced":
        ordered = [*take(backend, 5), *take(frontend, 5), *take(neutral, 3)]
    else:
        ordered = [*take(neutral, 6), *take(backend, 4), *take(frontend, 4)]

    return _dedupe_keep_order(ordered) or normalized


def _build_skill_bullet(skill_tokens, variant: int = 0) -> str:
    picks = []
    for token in skill_tokens or []:
        display = format_keyword_display(token)
        if display:
            picks.append(display)
        if len(picks) >= 3:
            break
    if not picks:
        return "Delivered production features that reduced average response time from 420 ms to 315 ms across 2 release cycles."
    phrase = ", ".join(picks)
    templates = [
        f"Leveraged {phrase} to reduce delivery cycle time from 9.5 days to 7.8 days across 3 release windows.",
        f"Implemented {phrase} workflows that lowered issue resolution from 14.0 hours to 10.4 hours across 2 support queues.",
        f"Optimized systems using {phrase}, cutting p95 latency from 320 ms to 236 ms for 1.2K requests per minute.",
        f"Scaled services with {phrase} to support 2x traffic growth.",
        f"Automated releases around {phrase}, reducing deployment effort from 18.0 hours to 13.4 hours per sprint.",
    ]
    return templates[variant % len(templates)]


def _inject_skills_into_summary(summary: str, skill_tokens, focus_mode: str = "balanced") -> str:
    value = _strip_buzzwords(str(summary or "").strip())
    if not value:
        return value
    if _text_mentions_any_skill(value, skill_tokens):
        return _fit_summary_length(value)

    picks = []
    for token in skill_tokens or []:
        display = format_keyword_display(token)
        if display:
            picks.append(display)
        if len(picks) >= 3:
            break

    if picks:
        value = f"{value} using {', '.join(picks)}."
    value = _strip_buzzwords(value)
    return _fit_summary_length(value)


def _ensure_skill_coverage_in_bullets(
    bullets,
    skill_tokens,
    min_count: int = 1,
    max_count: int = 4,
    used_verbs=None,
    seen_bullets=None,
    min_chars_required: int = 0,
):
    normalized = [str(line or "").strip() for line in (bullets or []) if str(line or "").strip()]
    target_min = max(1, int(min_count or 1))
    target_max = max(target_min, int(max_count or target_min))

    if not skill_tokens:
        seed = normalized or ["Improved workflow efficiency by 20%."]
        while len(seed) < target_min:
            seed.append("Improved delivery predictability by 22%.")
        return enforce_bullet_rules(
            seed[:target_max],
            used_verbs=used_verbs,
            seen_bullets=seen_bullets,
            skill_tokens=skill_tokens,
            min_chars_required=min_chars_required,
        )

    joined = " ".join(normalized)
    if not _text_mentions_any_skill(joined, skill_tokens):
        normalized.append(_build_skill_bullet(skill_tokens, variant=0))

    variant = 1
    while len(normalized) < target_min:
        normalized.append(_build_skill_bullet(skill_tokens, variant=variant))
        variant += 1

    return enforce_bullet_rules(
        normalized[:target_max],
        used_verbs=used_verbs,
        seen_bullets=seen_bullets,
        skill_tokens=skill_tokens,
        min_chars_required=min_chars_required,
    )


def _build_jd_guided_bullet(jd_tokens, variant: int = 0) -> str:
    picks = []
    for token in jd_tokens or []:
        display = format_keyword_display(token)
        if display:
            picks.append(display)
        if len(picks) >= 3:
            break

    if picks:
        stack = ", ".join(picks)
        templates = [
            f"Built {stack} pipelines that improved KPI accuracy from 0.71 to 0.82 and reduced turnaround from 9.2 hours to 6.8 hours per batch.",
            f"Implemented {stack} solutions that raised model reliability from 97.1 to 98.6 and cut analysis cycle time from 6.5 hours to 4.8 hours.",
            f"Optimized {stack} workflows to reduce manual effort from 22.0 hours to 14.4 hours and increased weekly throughput from 180 to 246 tasks.",
            f"Engineered {stack} delivery processes that lifted end-to-end throughput from 410 to 522 events per hour and reduced rework from 19 to 11 cases.",
        ]
        return templates[variant % len(templates)]

    generic = [
        "Delivered JD-aligned outcomes that improved KPI scores from 0.68 to 0.79 and reduced operational turnaround from 8.0 hours to 5.9 hours.",
        "Executed role-specific initiatives that raised system reliability from 97.3 to 98.7 while increasing daily processing volume from 1.1K to 1.5K records.",
        "Drove business-impact projects that reduced process cycle time from 12.0 hours to 8.7 hours and lifted weekly output from 42 to 58 deliverables.",
    ]
    return generic[variant % len(generic)]


def _ensure_jd_guided_bullets(
    bullets,
    jd_tokens,
    min_count: int = 1,
    max_count: int = 4,
    used_verbs=None,
    seen_bullets=None,
    min_chars_required: int = 0,
):
    normalized = [str(line or "").strip() for line in (bullets or []) if str(line or "").strip()]
    target_min = max(1, int(min_count or 1))
    target_max = max(target_min, int(max_count or target_min))

    if not normalized:
        normalized = [_build_jd_guided_bullet(jd_tokens, variant=0)]

    variant = 1
    while len(normalized) < target_min:
        normalized.append(_build_jd_guided_bullet(jd_tokens, variant=variant))
        variant += 1

    return enforce_bullet_rules(
        normalized[:target_max],
        used_verbs=used_verbs,
        seen_bullets=seen_bullets,
        skill_tokens=jd_tokens,
        min_chars_required=min_chars_required,
    )


def extract_keywords_heuristic(jd_text: str):
    text = str(jd_text or "")
    low = text.lower()
    found = []

    for term in KNOWN_TECH_TERMS:
        pattern = r"\b" + re.escape(term.lower()) + r"\b"
        if re.search(pattern, low):
            found.append(term)

    comma_chunks = re.split(r"[\n;]", text)
    for chunk in comma_chunks:
        if len(found) >= 80:
            break
        if not re.search(r"(skill|require|technology|tech|stack|must|experience|tools?)", chunk, flags=re.I):
            continue
        for part in chunk.split(","):
            token = _normalize_keyword(part)
            if not token or token in COMMON_STOPWORDS:
                continue
            if len(token) < 2 or len(token) > 35:
                continue
            if re.fullmatch(r"[0-9+\-/% ]+", token):
                continue
            found.append(token)

    words = re.findall(r"[A-Za-z][A-Za-z0-9+.#/-]{1,24}", text)
    for w in words:
        if len(found) >= 80:
            break
        token = _normalize_keyword(w)
        if token in COMMON_STOPWORDS:
            continue
        if token in KNOWN_TECH_TERMS:
            found.append(token)

    keywords = _dedupe_keep_order([_normalize_keyword(x) for x in found])[:80]
    return keywords


def _resolve_ai_model_name(model_override: str | None = None, user=None) -> str:
    override = str(model_override or "").strip()
    if override in ALLOWED_AI_MODELS:
        return override
    resolved_model = str(resolve_openai_settings(user).get("model", "gpt-4o") or "").strip() or "gpt-4o"
    if resolved_model in ALLOWED_AI_MODELS:
        return resolved_model
    return "gpt-4o"


def _openai_chat_json(system_prompt: str, user_prompt: str, model_override: str | None = None, user=None):
    settings = resolve_openai_settings(user)
    api_key = settings.get("api_key", "").strip()
    if not api_key:
        return None, "OPENAI_API_KEY is not set"

    model = _resolve_ai_model_name(model_override, user=user)
    task_instructions = str(settings.get("task_instructions", "") or "").strip()
    if task_instructions:
        system_prompt = f"{system_prompt}\n\nAdditional user instructions:\n{task_instructions[:2000]}"
    body = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        return None, f"OpenAI HTTP {exc.code}: {raw[:240]}"
    except Exception as exc:  # noqa: BLE001
        return None, f"OpenAI request failed: {exc}"

    content = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not content:
        return None, "OpenAI returned empty content"
    try:
        return json.loads(content), None
    except json.JSONDecodeError:
        maybe = re.search(r"\{[\s\S]*\}", content)
        if maybe:
            try:
                return json.loads(maybe.group(0)), None
            except json.JSONDecodeError:
                pass
        return None, "Could not parse JSON from OpenAI response"


def extract_keywords_ai(jd_text: str, model_override: str | None = None, user=None):
    system = (
        "Extract ONLY skill/technology keywords from a job description. "
        "Return JSON with key 'keywords' as unique lowercase terms or short phrases."
    )
    user_prompt = (
        "Job description:\n"
        f"{jd_text}\n\n"
        "Return JSON only like: {\"keywords\": [\"python\", \"django\", \"aws\"]}. "
        "Do not include soft skills, generic verbs, or company filler."
    )
    result, error = _openai_chat_json(system, user_prompt, model_override=model_override, user=user)
    if error or not isinstance(result, dict):
        return extract_keywords_heuristic(jd_text), False, error or "AI keyword extraction failed"
    raw = result.get("keywords") or []
    if not isinstance(raw, list):
        return extract_keywords_heuristic(jd_text), False, "AI keywords payload invalid"
    keywords = _dedupe_keep_order([_normalize_keyword(x) for x in raw if _normalize_keyword(x)])[:80]
    if not keywords:
        return extract_keywords_heuristic(jd_text), False, "AI returned empty keywords"
    return keywords, True, ""


def score_resume_keyword_match(jd_keywords, resume_text):
    text = str(resume_text or "").lower()
    if not jd_keywords:
        return 0.0, []
    matched = []
    for kw in jd_keywords:
        if not kw:
            continue
        pattern = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pattern, text):
            matched.append(kw)
    ratio = len(matched) / max(1, len(jd_keywords))
    return ratio, matched


def _strip_buzzwords(text: str):
    out = str(text or "")
    for w in BUZZWORDS:
        out = re.sub(rf"\b{re.escape(w)}\b", "", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,.;")
    return out


def _ensure_quantified(line: str):
    value = str(line or "").strip()
    if not value:
        return value
    if re.search(r"\d", value):
        return value
    suffixes = [
        "from 7.2 hours to 5.4 hours.",
        "for 1.4K monthly requests.",
        "from 320 ms to 210.5 ms.",
        "for 10K+ users.",
        "in 185.0 ms.",
    ]
    suffix = random.choice(suffixes)
    if value.endswith("."):
        value = value[:-1]
    return f"{value} {suffix}"


def _has_numeric_quantity(text: str) -> bool:
    return bool(re.search(r"\d", str(text or "")))


def _force_numeric_quantity(line: str) -> str:
    value = str(line or "").strip()
    if not value:
        return value
    if _has_numeric_quantity(value):
        return value

    candidates = [
        "improving throughput from 820 to 1,040 requests per minute while reducing turnaround from 9.5 to 6.8 hours",
        "supporting 10K+ monthly requests with 98.8% availability",
        "cutting manual effort from 26.0 to 16.4 hours per cycle",
    ]
    for frag in candidates:
        attempt = _fit_bullet_length(f"{value}; {frag}")
        if _has_numeric_quantity(attempt):
            return attempt

    fallback = _fit_bullet_length(f"{value} for 2 production workflows.")
    return fallback


def _sanitize_percentage_range(line: str) -> str:
    value = str(line or "").strip()
    if not value:
        return value

    def _replace(match):
        raw = match.group(1)
        try:
            numeric = float(raw)
        except Exception:  # noqa: BLE001
            return match.group(0)
        bounded = min(PERCENT_MAX, max(PERCENT_MIN, numeric))
        if "." in raw:
            text = f"{bounded:.1f}".rstrip("0").rstrip(".")
        else:
            text = str(int(round(bounded)))
        return f"{text}%"

    return re.sub(r"(\d{1,3}(?:\.\d+)?)\s*%", _replace, value)


def _has_baseline_context(text: str) -> bool:
    value = str(text or "")
    return bool(
        re.search(r"\bfrom\b.+\bto\b", value, flags=re.I)
    ) or bool(
        re.search(
            r"\b\d+(?:\.\d+)?\s*(?:ms|s|sec|secs|seconds|min|mins|minutes|hr|hrs|hours|rpm|req/?min|requests?|users?|records?)?\s*(?:->|to)\s*\d+(?:\.\d+)?",
            value,
            flags=re.I,
        )
    )


def _reduce_percent_symbol_density(line: str, max_percent_symbols: int = 1) -> str:
    value = str(line or "").strip()
    if not value:
        return value

    # Keep % usage minimal; do not inject artificial baselines.
    if "%" in value and not _has_baseline_context(value):
        # Keep first %, strip the rest.
        matches = list(re.finditer(r"(\d{1,3}(?:\.\d+)?)\s*%", value))
        if len(matches) <= 1:
            return value
        kept = 0
        out = []
        last = 0
        for m in matches:
            out.append(value[last:m.start()])
            number_text = m.group(1)
            kept += 1
            out.append(f"{number_text}%" if kept == 1 else f"{number_text}")
            last = m.end()
        out.append(value[last:])
        return "".join(out)

    matches = list(re.finditer(r"(\d{1,3}(?:\.\d+)?)\s*%", value))
    if len(matches) <= max_percent_symbols:
        return value

    kept = 0
    out = []
    last = 0
    for m in matches:
        out.append(value[last:m.start()])
        number_text = m.group(1)
        kept += 1
        if kept <= max_percent_symbols:
            out.append(f"{number_text}%")
        else:
            out.append(f"{number_text}")
        last = m.end()
    out.append(value[last:])
    return "".join(out)


def _trim_to_max_chars(value: str, max_chars: int):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rsplit(" ", 1)[0].strip(" ,;:-")
    return trimmed if trimmed else text[:max_chars].strip(" ,;:-")


def _expand_text_to_min_chars(value: str, min_chars: int, expansions):
    text = re.sub(r"\s+", " ", str(value or "").strip()).strip(" ,;:-")
    if not text:
        return text
    start_offset = sum(ord(ch) for ch in text) % max(1, len(expansions))
    idx = start_offset
    max_rounds = max(1, len(expansions) * 4)
    while len(text) < min_chars and idx < max_rounds:
        fragment = str(expansions[idx % len(expansions)]).strip(" .")
        if not fragment:
            idx += 1
            continue
        sep = "; " if len(text) < (min_chars - 80) else ", "
        text = f"{text}{sep}{fragment}".strip(" ,;:-")
        idx += 1
    return text


def _fit_bullet_length(line: str):
    value = re.sub(r"\s+", " ", str(line or "").strip())
    if not value:
        return value
    value = _trim_to_max_chars(value, BULLET_MAX_CHARS)
    if value and not value.endswith("."):
        value = f"{value}."
    return value


def _apply_bullet_min_chars(line: str, min_chars_required: int = 0):
    value = str(line or "").strip()
    if not value:
        return value
    minimum = max(0, int(min_chars_required or 0))
    if minimum <= 0:
        return value
    value = _expand_text_to_min_chars(
        value,
        minimum,
        [
            "while strengthening reliability across 2 production services",
            "and sustaining throughput under 1.2K requests per minute during peak windows",
            "while meeting 98.7% uptime SLO across 3 release cycles",
        ],
    )
    return value


def _remove_artificial_100_baseline(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return value
    # Replace suspicious synthetic baseline pattern: "from 100(.0) to X"
    return re.sub(
        r",?\s*from\s+100(?:\.0+)?\s+to\s+(\d+(?:\.\d+)?)",
        "",
        value,
        flags=re.I,
    )


def _cleanup_bullet_language(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return value
    # Remove repetitive generic filler if present.
    value = re.sub(
        r",?\s*with measurable impact across 3 operational checkpoints\.?",
        "",
        value,
        flags=re.I,
    )
    # Fix awkward phrasing patterns.
    value = re.sub(r"^\s*Reduced on\b", "Optimized", value, flags=re.I)
    value = re.sub(r"^\s*Improved on Kubernetes\b", "Deployed on Kubernetes", value, flags=re.I)
    value = re.sub(r"^\s*Delivered Spring Security\b", "Implemented Spring Security", value, flags=re.I)
    value = re.sub(r"\s+,", ",", value)
    value = re.sub(r"\s+\.", ".", value)
    value = re.sub(r"\s{2,}", " ", value).strip(" ,")
    if value and not value.endswith("."):
        value = f"{value}."
    return value


def _fit_summary_length(text: str):
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return value
    value = _expand_text_to_min_chars(
        value,
        SUMMARY_MIN_CHARS,
        [
            "with proven impact on latency, release velocity, and reliability across production systems",
            "delivering measurable outcomes such as 25% faster delivery cycles and 30% better operational stability",
            "by aligning architecture, execution, and business priorities for scalable product growth",
        ],
    )
    value = _trim_to_max_chars(value, SUMMARY_MAX_CHARS)
    if value and not value.endswith("."):
        value = f"{value}."
    return value


def _fit_summary_length_non_software(text: str):
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return value
    value = value.rstrip(".")
    value = _expand_text_to_min_chars(
        value,
        SUMMARY_MIN_CHARS,
        [
            "delivering quantified improvements in model quality, analytical rigor, and decision support outcomes",
            "translating complex datasets into measurable business impact with reliable experimentation and monitoring",
            "aligning statistical methods and machine learning workflows to practical business objectives",
        ],
    )
    value = _trim_to_max_chars(value, SUMMARY_MAX_CHARS)
    if value and not value.endswith("."):
        value = f"{value}."
    return value


def _extract_first_word(line: str):
    words = re.findall(r"[A-Za-z][A-Za-z-]*", str(line or ""))
    return words[0].lower() if words else ""


def _extract_priority_tags(text: str):
    value = str(text or "")
    tags = set()
    if re.search(r"\b(revenue|profit|sales|arr|mrr)\b", value, flags=re.I):
        tags.add("revenue")
    if re.search(r"\b(optimi[sz]e[drs]?|optimization|latency|throughput|performance|efficien(?:cy|t))\b", value, flags=re.I):
        tags.add("optimization")
    return tags


def _ensure_priority_tags(candidate: str, tags):
    value = str(candidate or "").strip()
    if not value or not tags:
        return value
    if "revenue" in tags and not re.search(r"\b(revenue|profit|sales|arr|mrr)\b", value, flags=re.I):
        value = value.rstrip(".")
        value = f"{value}, improving revenue outcomes across 2 business segments."
    if "optimization" in tags and not re.search(
        r"\b(optimi[sz]e[drs]?|optimization|latency|throughput|performance|efficien(?:cy|t))\b",
        value,
        flags=re.I,
    ):
        value = value.rstrip(".")
        value = f"{value}, optimizing performance across 2 critical workflows."
    return value


def _replace_action_verb(line: str, new_verb: str):
    words = re.findall(r"[A-Za-z][A-Za-z-]*", str(line or ""))
    if not words:
        return f"{new_verb} {line}".strip()
    first = words[0]
    return re.sub(rf"^\s*{re.escape(first)}\b", new_verb, line, count=1)


def _to_ats_friendly_text(value: str) -> str:
    text = str(value or "")
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\x20-\x7E]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def enforce_bullet_rules(
    bullets,
    used_verbs=None,
    seen_bullets=None,
    skill_tokens=None,
    min_chars_required: int = 0,
):
    external_used_verbs = used_verbs if isinstance(used_verbs, set) else set()
    external_seen_bullets = seen_bullets if isinstance(seen_bullets, set) else set()

    cleaned = []
    for line in bullets:
        original_text = str(line or "").strip()
        priority_tags = _extract_priority_tags(original_text)
        text = _strip_buzzwords(original_text)
        if not text:
            continue
        text = _ensure_quantified(text)
        text = _force_numeric_quantity(text)
        text = _sanitize_percentage_range(text)
        text = _reduce_percent_symbol_density(text, max_percent_symbols=1)
        text = _remove_artificial_100_baseline(text)
        text = _cleanup_bullet_language(text)
        text = _ensure_priority_tags(text, priority_tags)
        text = _apply_bullet_min_chars(text, min_chars_required=min_chars_required)
        text = _fit_bullet_length(text)
        cleaned.append((text, priority_tags))

    deduped = []
    seen_cleaned = set()
    for text, tags in cleaned:
        key = _canonical_bullet_key(text)
        if not key or key in seen_cleaned:
            continue
        seen_cleaned.add(key)
        deduped.append((text, tags))
    cleaned = deduped
    if not cleaned:
        cleaned = [("Improved process time by 20%.", set())]

    local_used_verbs = set()
    final = []
    for idx, packed in enumerate(cleaned):
        line, priority_tags = packed
        candidate = _strip_buzzwords(line)
        attempts = 0
        while attempts < 16:
            verb = _extract_first_word(candidate)
            if not verb:
                replacement = _next_unique_action_verb(external_used_verbs.union(local_used_verbs))
                candidate = _replace_action_verb(candidate, replacement)
                verb = replacement.lower()

            all_used = external_used_verbs.union(local_used_verbs)
            if verb in all_used:
                replacement = _next_unique_action_verb(all_used)
                candidate = _replace_action_verb(candidate, replacement)
                verb = replacement.lower()

            candidate = _strip_buzzwords(candidate)
            candidate = _ensure_quantified(candidate)
            candidate = _force_numeric_quantity(candidate)
            candidate = _sanitize_percentage_range(candidate)
            candidate = _reduce_percent_symbol_density(candidate, max_percent_symbols=1)
            candidate = _remove_artificial_100_baseline(candidate)
            candidate = _cleanup_bullet_language(candidate)
            candidate = _ensure_priority_tags(candidate, priority_tags)
            candidate = _apply_bullet_min_chars(candidate, min_chars_required=min_chars_required)
            candidate = _fit_bullet_length(candidate)
            key = _canonical_bullet_key(candidate)

            if key and key not in external_seen_bullets:
                break

            # Regenerate using skill-aware templates to avoid duplicate statements.
            candidate = _build_skill_bullet(skill_tokens or [], variant=idx + attempts + 1)
            candidate = _sanitize_percentage_range(candidate)
            candidate = _reduce_percent_symbol_density(candidate, max_percent_symbols=1)
            candidate = _remove_artificial_100_baseline(candidate)
            candidate = _cleanup_bullet_language(candidate)
            candidate = _ensure_priority_tags(candidate, priority_tags)
            candidate = _apply_bullet_min_chars(candidate, min_chars_required=min_chars_required)
            attempts += 1

        verb = _extract_first_word(candidate)
        key = _canonical_bullet_key(candidate)
        if verb:
            local_used_verbs.add(verb)
            external_used_verbs.add(verb)
        if key:
            external_seen_bullets.add(key)
        final.append(candidate)
    return final


def _collect_payload_bullets(ai_payload: dict):
    bullets = []
    if not isinstance(ai_payload, dict):
        return bullets
    for exp in ai_payload.get("experiences") or []:
        if isinstance(exp, dict):
            for line in exp.get("bullets") or []:
                text = _to_ats_friendly_text(str(line or "").strip())
                if text:
                    bullets.append(text)
    for proj in ai_payload.get("projects") or []:
        if isinstance(proj, dict):
            for line in proj.get("bullets") or []:
                text = _to_ats_friendly_text(str(line or "").strip())
                if text:
                    bullets.append(text)
    return bullets


def _validate_payload_bullet_rules(ai_payload: dict, model_override: str | None = None):
    all_bullets = _collect_payload_bullets(ai_payload)
    if not all_bullets:
        return False, ["No bullets returned."]

    issues = []
    min_chars_required = _bullet_min_required_for_model(model_override)
    seen_verbs = set()
    seen_keys = set()
    buzz_pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(BUZZWORDS, key=len, reverse=True)) + r")\b", flags=re.I)

    for idx, bullet in enumerate(all_bullets, start=1):
        bullet_len = len(str(bullet or ""))
        if min_chars_required and bullet_len < min_chars_required:
            issues.append(
                f"Bullet {idx} length must be >= {min_chars_required} chars; got {bullet_len}."
            )
        if bullet_len > BULLET_MAX_CHARS:
            issues.append(
                f"Bullet {idx} length must be <= {BULLET_MAX_CHARS} chars; got {bullet_len}."
            )
        has_baseline = _has_baseline_context(bullet)
        if not re.search(r"\d", bullet):
            issues.append(f"Bullet {idx} has no numeric metric.")
        percent_values = []
        for raw in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", bullet):
            try:
                percent_values.append(float(raw))
            except Exception:  # noqa: BLE001
                continue
        for value in percent_values:
            if value < PERCENT_MIN or value > PERCENT_MAX:
                issues.append(
                    f"Bullet {idx} has unrealistic percentage {value:g}% (allowed range {PERCENT_MIN}-{PERCENT_MAX}%)."
                )
        # % without baseline is allowed, but generator is guided to prefer clear baselines when available.
        if buzz_pattern.search(bullet):
            issues.append(f"Bullet {idx} contains buzzwords.")

        verb = _extract_first_word(bullet)
        if not verb:
            issues.append(f"Bullet {idx} has no clear action verb.")
        elif verb in seen_verbs:
            issues.append(f"Bullet {idx} repeats action verb '{verb}'.")
        else:
            seen_verbs.add(verb)

        key = _canonical_bullet_key(bullet)
        if key in seen_keys:
            issues.append(f"Bullet {idx} duplicates another bullet.")
        else:
            seen_keys.add(key)

    return len(issues) == 0, issues


def _validate_payload_bullet_count_limits(ai_payload: dict):
    issues = []
    if not isinstance(ai_payload, dict):
        return issues

    all_bullets = _collect_payload_bullets(ai_payload)

    experiences = [x for x in (ai_payload.get("experiences") or []) if isinstance(x, dict)]
    has_current = any(bool(x.get("isCurrent")) for x in experiences)
    for idx, exp in enumerate(experiences, start=1):
        bullets = [str(x or "").strip() for x in (exp.get("bullets") or []) if str(x or "").strip()]
        is_current = bool(exp.get("isCurrent"))
        if not has_current and idx == 1:
            is_current = True
        min_allowed = CURRENT_EXP_MIN_BULLETS if is_current else PAST_EXP_MIN_BULLETS
        max_allowed = CURRENT_EXP_MAX_BULLETS if is_current else PAST_EXP_MAX_BULLETS
        if len(bullets) < min_allowed:
            issues.append(
                f"Experience {idx} has {len(bullets)} bullets; min required is {min_allowed}."
            )
        if len(bullets) > max_allowed:
            issues.append(
                f"Experience {idx} has {len(bullets)} bullets; max allowed is {max_allowed}."
            )

    projects = [x for x in (ai_payload.get("projects") or []) if isinstance(x, dict)]
    for idx, proj in enumerate(projects, start=1):
        bullets = [str(x or "").strip() for x in (proj.get("bullets") or []) if str(x or "").strip()]
        if len(bullets) < PROJECT_MIN_BULLETS:
            issues.append(
                f"Project {idx} has {len(bullets)} bullets; min required is {PROJECT_MIN_BULLETS}."
            )
        if len(bullets) > PROJECT_MAX_BULLETS:
            issues.append(
                f"Project {idx} has {len(bullets)} bullets; max allowed is {PROJECT_MAX_BULLETS}."
            )

    return issues


def _normalize_ai_payload_before_validation(
    ai_payload: dict,
    require_summary: bool = False,
    model_override: str | None = None,
):
    if not isinstance(ai_payload, dict):
        return {}

    payload = dict(ai_payload)
    min_chars_required = _bullet_min_required_for_model(model_override)
    experiences = payload.get("experiences") if isinstance(payload.get("experiences"), list) else []
    projects = payload.get("projects") if isinstance(payload.get("projects"), list) else []

    normalized_exps = []
    used_verbs = set()
    seen_bullets = set()
    has_current = any(bool(item.get("isCurrent")) for item in experiences if isinstance(item, dict))
    for idx, exp in enumerate(experiences):
        if not isinstance(exp, dict):
            continue
        exp_item = dict(exp)
        is_current = bool(exp_item.get("isCurrent"))
        if not has_current and idx == 0:
            is_current = True
        min_required = CURRENT_EXP_MIN_BULLETS if is_current else PAST_EXP_MIN_BULLETS
        max_allowed = CURRENT_EXP_MAX_BULLETS if is_current else PAST_EXP_MAX_BULLETS
        raw = exp_item.get("bullets") if isinstance(exp_item.get("bullets"), list) else []
        cleaned = [_to_ats_friendly_text(str(x or "").strip()) for x in raw if _to_ats_friendly_text(str(x or "").strip())]
        normalized_bullets = enforce_bullet_rules(
            cleaned[:max_allowed],
            used_verbs=used_verbs,
            seen_bullets=seen_bullets,
            skill_tokens=[],
            min_chars_required=min_chars_required,
        )[:max_allowed]
        variant = 0
        while len(normalized_bullets) < min_required:
            seed = _build_skill_bullet([], variant=variant)
            extra = enforce_bullet_rules(
                [seed],
                used_verbs=used_verbs,
                seen_bullets=seen_bullets,
                skill_tokens=[],
                min_chars_required=min_chars_required,
            )
            if extra:
                normalized_bullets.append(extra[0])
            variant += 1
            if variant > 20:
                break
        exp_item["bullets"] = normalized_bullets[:max_allowed]
        normalized_exps.append(exp_item)
    payload["experiences"] = normalized_exps

    normalized_projects = []
    for proj in projects:
        if not isinstance(proj, dict):
            continue
        proj_item = dict(proj)
        raw = proj_item.get("bullets") if isinstance(proj_item.get("bullets"), list) else []
        cleaned = [_to_ats_friendly_text(str(x or "").strip()) for x in raw if _to_ats_friendly_text(str(x or "").strip())]
        normalized_bullets = enforce_bullet_rules(
            cleaned[:PROJECT_MAX_BULLETS],
            used_verbs=used_verbs,
            seen_bullets=seen_bullets,
            skill_tokens=[],
            min_chars_required=min_chars_required,
        )[:PROJECT_MAX_BULLETS]
        variant = 0
        while len(normalized_bullets) < PROJECT_MIN_BULLETS:
            seed = _build_skill_bullet([], variant=variant)
            extra = enforce_bullet_rules(
                [seed],
                used_verbs=used_verbs,
                seen_bullets=seen_bullets,
                skill_tokens=[],
                min_chars_required=min_chars_required,
            )
            if extra:
                normalized_bullets.append(extra[0])
            variant += 1
            if variant > 20:
                break
        proj_item["bullets"] = normalized_bullets[:PROJECT_MAX_BULLETS]
        normalized_projects.append(proj_item)
    payload["projects"] = normalized_projects

    if require_summary:
        summary = _to_ats_friendly_text(str(payload.get("summary") or "").strip())
        if summary:
            summary = _strip_buzzwords(summary)
            summary = _ensure_summary_three_plus(summary)
            summary = _fit_summary_length(summary)
            payload["summary"] = summary

    return payload

def _validate_payload_rules(
    ai_payload: dict,
    require_summary: bool = False,
    model_override: str | None = None,
):
    ok_bullets, bullet_issues = _validate_payload_bullet_rules(ai_payload, model_override=model_override)
    issues = [*bullet_issues, *_validate_payload_bullet_count_limits(ai_payload)]
    if require_summary:
        summary_text = plain_text_from_html((ai_payload or {}).get("summary") or "")
        if not summary_text:
            issues.append("Summary is missing.")
        else:
            if len(summary_text) < SUMMARY_MIN_CHARS or len(summary_text) > SUMMARY_MAX_CHARS:
                issues.append(
                    f"Summary length must be {SUMMARY_MIN_CHARS}-{SUMMARY_MAX_CHARS} chars; got {len(summary_text)}."
                )
            if any(re.search(rf"\b{re.escape(w)}\b", summary_text, flags=re.I) for w in BUZZWORDS):
                issues.append("Summary contains buzzwords.")
    return len(issues) == 0, issues


def _generate_validated_ai_payload(
    system_prompt: str,
    base_user_prompt: str,
    max_rounds: int = 4,
    require_summary: bool = False,
    model_override: str | None = None,
    user=None,
):
    prompt = base_user_prompt
    last_error = ""
    for round_idx in range(max_rounds):
        result, error = _openai_chat_json(system_prompt, prompt, model_override=model_override, user=user)
        if error or not isinstance(result, dict):
            last_error = error or "AI response was invalid"
            continue

        normalized_result = _normalize_ai_payload_before_validation(
            result,
            require_summary=require_summary,
            model_override=model_override,
        )
        ok, issues = _validate_payload_rules(
            normalized_result,
            require_summary=require_summary,
            model_override=model_override,
        )
        if ok:
            return normalized_result, True, ""

        issues_text = "\n- ".join(issues[:25])
        prompt = (
            f"{base_user_prompt}\n"
            f"Previous output (round {round_idx + 1}) failed strict validation.\n"
            f"Issues:\n- {issues_text}\n\n"
            "Regenerate a fully corrected JSON response that satisfies every rule."
        )
        last_error = "AI validation failed: " + "; ".join(issues[:10])

    return {}, False, last_error or "AI generation failed after retries"


def _repair_payload_with_ai(
    system_prompt: str,
    base_user_prompt: str,
    bad_payload: dict,
    issues,
    require_summary: bool = False,
    model_override: str | None = None,
    user=None,
):
    repair_prompt = (
        f"{base_user_prompt}\n\n"
        "You previously returned this JSON:\n"
        f"{json.dumps(bad_payload or {}, ensure_ascii=False)}\n\n"
        "It failed strict validation. Fix only the invalid bullets and return full corrected JSON.\n"
        "Validation issues:\n- "
        + "\n- ".join((issues or [])[:30])
    )
    repaired, error = _openai_chat_json(system_prompt, repair_prompt, model_override=model_override, user=user)
    if error or not isinstance(repaired, dict):
        return {}, False, error or "AI repair pass failed"
    normalized_repaired = _normalize_ai_payload_before_validation(
        repaired,
        require_summary=require_summary,
        model_override=model_override,
    )
    ok, new_issues = _validate_payload_rules(
        normalized_repaired,
        require_summary=require_summary,
        model_override=model_override,
    )
    if not ok:
        return {}, False, "AI repair pass failed validation: " + "; ".join(new_issues[:10])
    return normalized_repaired, True, ""


def build_tailored_builder(
    base_builder: dict,
    ai_payload: dict,
    keywords,
    jd_text: str = "",
    model_override: str | None = None,
):
    source = sanitize_builder_data(base_builder or {})
    summary = _to_ats_friendly_text(_strip_buzzwords(str(ai_payload.get("summary") or "").strip()))
    inferred_role = _infer_role_from_jd(jd_text)
    is_software_track = _is_software_track_role(inferred_role, jd_text)
    normalized_exp_role = _normalize_experience_role_title(inferred_role)
    if not summary:
        if is_software_track:
            summary = "Software Developer with 3+ years of experience delivering measurable impact across API reliability, speed, and scalability."
        else:
            role_label = inferred_role or "Professional"
            summary = f"{role_label} with 3+ years of experience delivering measurable outcomes aligned to job requirements."
    if inferred_role and inferred_role.lower() not in summary.lower():
        if is_software_track:
            summary = "Software Developer with 3+ years of experience delivering measurable impact across production systems."
        else:
            summary = f"{inferred_role} with 3+ years of experience delivering measurable outcomes aligned to job requirements."
    summary = _ensure_summary_three_plus(summary)

    normalized_keywords = _dedupe_keep_order(
        [
            _canonicalize_skill_token(k)
            for k in keywords
            if _canonicalize_skill_token(k) and _is_technical_skill_token(k)
        ]
    )[:40]
    jd_skill_set = set(normalized_keywords)
    required_tokens = []
    if is_software_track:
        required_tokens = [
            _canonicalize_skill_token(k)
            for k in REQUIRED_CORE_SKILLS
            if _canonicalize_skill_token(k) and _is_technical_skill_token(k) and _canonicalize_skill_token(k) in jd_skill_set
        ]
    # Strict mode: keep technical JD skills; add core tokens only for software-track roles.
    combined_skills = _ensure_non_negotiable_skills([*normalized_keywords, *required_tokens])
    focus = _infer_resume_focus(jd_text, combined_skills)
    if is_software_track:
        preferred_skills = _prioritize_skills_for_focus(combined_skills, focus.get("mode", "balanced"))
    else:
        preferred_skills = combined_skills

    if is_software_track:
        summary = _inject_skills_into_summary(summary, preferred_skills, focus.get("mode", "balanced"))
    if is_software_track:
        summary = _fit_summary_length(_ensure_summary_three_plus(summary))
    else:
        summary = _fit_summary_length_non_software(_ensure_summary_three_plus(summary))
    summary = _to_ats_friendly_text(_ensure_summary_three_plus(summary))
    if inferred_role:
        source["role"] = _to_ats_friendly_text(inferred_role)
    source["summaryEnabled"] = True
    source["summaryHeading"] = source.get("summaryHeading") or "Summary"
    source["summary"] = f"<p>{escape(summary)}</p>"

    if combined_skills:
        skills_html = _build_categorized_skills_html(combined_skills)
        if skills_html:
            source["skills"] = skills_html

    global_used_verbs = set()
    global_seen_bullets = set()
    min_chars_required = _bullet_min_required_for_model(model_override)

    ai_exps = ai_payload.get("experiences") or []
    if not isinstance(ai_exps, list):
        ai_exps = []
    base_exps = source.get("experiences") or []
    rewritten_exps = []

    def target_exp_bullets(is_current: bool):
        if is_current:
            return CURRENT_EXP_MIN_BULLETS, CURRENT_EXP_MAX_BULLETS
        return PAST_EXP_MIN_BULLETS, PAST_EXP_MAX_BULLETS

    def normalize_bullets(lines, min_count: int, max_count: int):
        normalized_lines = [_to_ats_friendly_text(str(x or "").strip()) for x in (lines or [])]
        normalized_lines = [x for x in normalized_lines if x]
        if is_software_track:
            return _ensure_skill_coverage_in_bullets(
                normalized_lines,
                preferred_skills,
                min_count=min_count,
                max_count=max_count,
                used_verbs=global_used_verbs,
                seen_bullets=global_seen_bullets,
                min_chars_required=min_chars_required,
            )
        return _ensure_jd_guided_bullets(
            normalized_lines,
            preferred_skills,
            min_count=min_count,
            max_count=max_count,
            used_verbs=global_used_verbs,
            seen_bullets=global_seen_bullets,
            min_chars_required=min_chars_required,
        )

    if not base_exps and ai_exps:
        has_ai_current = any(bool(item.get("isCurrent")) for item in ai_exps if isinstance(item, dict))
        for idx, item in enumerate(ai_exps[:3]):
            bullets = item.get("bullets") if isinstance(item, dict) and isinstance(item.get("bullets"), list) else []
            is_current = bool(item.get("isCurrent")) if isinstance(item, dict) else False
            if not has_ai_current and idx == 0:
                is_current = True
            bullet_min, bullet_max = target_exp_bullets(is_current)
            normalized = normalize_bullets(
                bullets if bullets else [],
                min_count=bullet_min,
                max_count=bullet_max,
            )
            rewritten_exps.append(
                {
                    "company": _to_ats_friendly_text(str(item.get("company") or "").strip()) if isinstance(item, dict) else "",
                    "title": normalized_exp_role
                    or (_to_ats_friendly_text(str(item.get("title") or "").strip()) if isinstance(item, dict) else ""),
                    "startDate": _to_ats_friendly_text(str(item.get("startDate") or "").strip()) if isinstance(item, dict) else "",
                    "endDate": _to_ats_friendly_text(str(item.get("endDate") or "").strip()) if isinstance(item, dict) else "",
                    "isCurrent": is_current,
                    "highlights": bullets_to_html(normalized),
                }
            )
    else:
        has_base_current = any(bool(exp.get("isCurrent")) for exp in base_exps if isinstance(exp, dict))
        for index, exp in enumerate(base_exps):
            item = ai_exps[index] if index < len(ai_exps) and isinstance(ai_exps[index], dict) else {}
            ai_bullets = item.get("bullets") if isinstance(item.get("bullets"), list) else []
            is_current = bool(exp.get("isCurrent"))
            if not has_base_current and index == 0:
                is_current = True
            bullet_min, bullet_max = target_exp_bullets(is_current)
            if ai_bullets:
                bullets = normalize_bullets(
                    ai_bullets,
                    min_count=bullet_min,
                    max_count=bullet_max,
                )
            else:
                current = extract_bullets_from_html(exp.get("highlights") or "")
                bullets = normalize_bullets(
                    current,
                    min_count=bullet_min,
                    max_count=bullet_max,
                )
            exp["isCurrent"] = is_current
            if normalized_exp_role:
                exp["title"] = normalized_exp_role
            exp["highlights"] = bullets_to_html(bullets)
            rewritten_exps.append(exp)
    source["experiences"] = rewritten_exps

    ai_projects = ai_payload.get("projects") or []
    if not isinstance(ai_projects, list):
        ai_projects = []
    base_projects = source.get("projects") or []
    rewritten_projects = []
    if not base_projects and ai_projects:
        for idx, item in enumerate(ai_projects[:3]):
            bullets = item.get("bullets") if isinstance(item, dict) and isinstance(item.get("bullets"), list) else []
            normalized = normalize_bullets(
                bullets if bullets else [],
                min_count=PROJECT_MIN_BULLETS,
                max_count=PROJECT_MAX_BULLETS,
            )
            rewritten_projects.append(
                {
                    "name": _to_ats_friendly_text(str(item.get("name") or "").strip()) if isinstance(item, dict) else f"Project {idx + 1}",
                    "url": "",
                    "highlights": bullets_to_html(normalized),
                }
            )
    else:
        for index, project in enumerate(base_projects):
            item = ai_projects[index] if index < len(ai_projects) and isinstance(ai_projects[index], dict) else {}
            ai_bullets = item.get("bullets") if isinstance(item.get("bullets"), list) else []
            if ai_bullets:
                bullets = normalize_bullets(
                    ai_bullets,
                    min_count=PROJECT_MIN_BULLETS,
                    max_count=PROJECT_MAX_BULLETS,
                )
            else:
                current = extract_bullets_from_html(project.get("highlights") or "")
                bullets = normalize_bullets(
                    current,
                    min_count=PROJECT_MIN_BULLETS,
                    max_count=PROJECT_MAX_BULLETS,
                )
            current_name = str(project.get("name") or "").strip()
            incoming_name = _to_ats_friendly_text(str(item.get("name") or "").strip()) if isinstance(item, dict) else ""
            project["name"] = current_name or incoming_name
            project["url"] = ""
            project["highlights"] = bullets_to_html(bullets)
            rewritten_projects.append(project)
    source["projects"] = rewritten_projects
    source["projects"] = _ensure_second_project_mcp_if_agentic(source.get("projects") or [])
    source["projects"] = _ensure_second_project_mcp_if_agentic(
        source.get("projects") or [],
        used_verbs=global_used_verbs,
        seen_bullets=global_seen_bullets,
    )

    return source


def optimize_existing_resume_quality_ai(base_builder: dict, model_override: str | None = None, user=None):
    source = sanitize_builder_data(base_builder or {})
    locked = {
        "experiences": [
            {
                "company": str(exp.get("company") or "").strip(),
                "title": str(exp.get("title") or "").strip(),
                "startDate": str(exp.get("startDate") or "").strip(),
                "endDate": str(exp.get("endDate") or "").strip(),
                "isCurrent": bool(exp.get("isCurrent")),
                "bullets": extract_bullets_from_html(exp.get("highlights") or ""),
            }
            for exp in (source.get("experiences") or [])
            if isinstance(exp, dict)
        ],
        "projects": [
            {
                "name": str(proj.get("name") or "").strip(),
                "bullets": extract_bullets_from_html(proj.get("highlights") or ""),
            }
            for proj in (source.get("projects") or [])
            if isinstance(proj, dict)
        ],
    }

    system = (
        "You are an ATS resume quality optimizer. Return strict JSON only. "
        "Rewrite only experience/project bullets for quality improvement. "
        "Do NOT change company names, titles, dates, or project names. "
        "Assume candidate profile is 3+ years only and avoid senior/staff/principal scope claims. "
        f"{_bullet_count_rules_text()}"
        f"{_common_bullet_rules_text()}"
        "If the second project is agentic AI based, MCP is mandatory in that project's bullets. "
        "Keep each bullet concise and meaningful; preserve original accomplishments and avoid adding fake claims. "
        "Write in confident, human style and avoid AI-sounding repetitive phrasing. "
        "Use ATS-friendly plain characters only (ASCII). "
        "Before finalizing, run a self-check to ensure: every bullet has a digit and no starting verb repeats anywhere."
    )
    user_prompt = (
        "Optimize this resume structure:\n"
        f"{json.dumps(locked, ensure_ascii=False)}\n\n"
        "Return JSON object:\n"
        "{\n"
        "  \"experiences\": [{\"bullets\": [\"...\"]}],\n"
        "  \"projects\": [{\"bullets\": [\"...\"]}]\n"
        "}\n"
    )
    # Fast but more reliable: initial pass + up to 2 correction passes.
    result, ok, note = _generate_validated_ai_payload(
        system,
        user_prompt,
        max_rounds=3,
        require_summary=False,
        model_override=model_override,
        user=user,
    )
    if ok:
        return result, True, ""

    # Final targeted repair pass for stubborn violations.
    fallback_result, error = _openai_chat_json(system, user_prompt, model_override=model_override, user=user)
    if not error and isinstance(fallback_result, dict):
        normalized_fallback = _normalize_ai_payload_before_validation(
            fallback_result,
            require_summary=False,
            model_override=model_override,
        )
        valid, issues = _validate_payload_rules(
            normalized_fallback,
            require_summary=False,
            model_override=model_override,
        )
        if valid:
            return normalized_fallback, True, ""
        repaired, repaired_ok, repaired_note = _repair_payload_with_ai(
            system,
            user_prompt,
            normalized_fallback,
            issues,
            require_summary=False,
            model_override=model_override,
            user=user,
        )
        if repaired_ok:
            return repaired, True, ""
        return {}, False, repaired_note or note
    return {}, False, note


def build_quality_optimized_builder(
    base_builder: dict,
    ai_payload: dict,
    model_override: str | None = None,
):
    source = sanitize_builder_data(base_builder or {})
    existing_summary = plain_text_from_html(source.get("summary") or "")
    if existing_summary:
        summary = _to_ats_friendly_text(_strip_buzzwords(existing_summary))
        summary = _ensure_summary_three_plus(summary)
        source["summaryEnabled"] = True
        source["summaryHeading"] = source.get("summaryHeading") or "Summary"
        source["summary"] = f"<p>{escape(summary)}</p>"
    min_chars_required = _bullet_min_required_for_model(model_override)
    used_verbs = set()
    seen_bullets = set()

    ai_exps = ai_payload.get("experiences") if isinstance(ai_payload, dict) else []
    if not isinstance(ai_exps, list):
        ai_exps = []
    rewritten_exps = []
    for idx, exp in enumerate(source.get("experiences") or []):
        if not isinstance(exp, dict):
            continue
        item = ai_exps[idx] if idx < len(ai_exps) and isinstance(ai_exps[idx], dict) else {}
        ai_bullets = item.get("bullets") if isinstance(item.get("bullets"), list) else []
        if ai_bullets:
            normalized = enforce_bullet_rules(
                [_to_ats_friendly_text(str(x).strip()) for x in ai_bullets if _to_ats_friendly_text(str(x).strip())],
                used_verbs=used_verbs,
                seen_bullets=seen_bullets,
                skill_tokens=[],
                min_chars_required=min_chars_required,
            )
            exp["highlights"] = bullets_to_html(
                normalized
            )
        rewritten_exps.append(exp)
    source["experiences"] = rewritten_exps

    ai_projects = ai_payload.get("projects") if isinstance(ai_payload, dict) else []
    if not isinstance(ai_projects, list):
        ai_projects = []
    rewritten_projects = []
    for idx, proj in enumerate(source.get("projects") or []):
        if not isinstance(proj, dict):
            continue
        item = ai_projects[idx] if idx < len(ai_projects) and isinstance(ai_projects[idx], dict) else {}
        ai_bullets = item.get("bullets") if isinstance(item.get("bullets"), list) else []
        if ai_bullets:
            normalized = enforce_bullet_rules(
                [_to_ats_friendly_text(str(x).strip()) for x in ai_bullets if _to_ats_friendly_text(str(x).strip())],
                used_verbs=used_verbs,
                seen_bullets=seen_bullets,
                skill_tokens=[],
                min_chars_required=min_chars_required,
            )
            proj["highlights"] = bullets_to_html(
                normalized
            )
        rewritten_projects.append(proj)
    source["projects"] = rewritten_projects

    # Optimize skills too: refresh from existing skills + rewritten bullet content.
    base_skill_tokens = _extract_skill_tokens_from_html(source.get("skills") or "")
    content_parts = []
    for exp in rewritten_exps:
        content_parts.append(plain_text_from_html(exp.get("highlights") or ""))
    for proj in rewritten_projects:
        content_parts.append(plain_text_from_html(proj.get("highlights") or ""))
    inferred_tokens = extract_keywords_heuristic("\n".join(content_parts))
    optimized_skill_tokens = _dedupe_keep_order(
        [
            _canonicalize_skill_token(x)
            for x in [*base_skill_tokens, *inferred_tokens]
            if _canonicalize_skill_token(x) and _is_technical_skill_token(x)
        ]
    )
    optimized_skill_tokens = _ensure_non_negotiable_skills(optimized_skill_tokens)
    skills_html = _build_categorized_skills_html(optimized_skill_tokens)
    if skills_html:
        source["skills"] = skills_html

    return source


def _fallback_ai_payload(base_builder, keywords):
    base_builder = sanitize_builder_data(base_builder or {})
    experiences = []
    projects = []
    global_used_verbs = set()
    global_seen_bullets = set()

    for index, exp in enumerate((base_builder or {}).get("experiences") or []):
        base = extract_bullets_from_html(exp.get("highlights") or "")
        base = base[:3] if base else ["Improved delivery speed for API workflows by 25%."]
        experiences.append(
            {
                "bullets": enforce_bullet_rules(
                    base,
                    used_verbs=global_used_verbs,
                    seen_bullets=global_seen_bullets,
                    skill_tokens=keywords,
                )
            }
        )

    if not experiences:
        experiences.append(
            {
                "bullets": enforce_bullet_rules(
                    ["Improved delivery speed for API workflows by 25%."],
                    used_verbs=global_used_verbs,
                    seen_bullets=global_seen_bullets,
                    skill_tokens=keywords,
                )
            }
        )

    for index, proj in enumerate((base_builder or {}).get("projects") or []):
        base = extract_bullets_from_html(proj.get("highlights") or "")
        base = base[:3] if base else ["Delivered project outcomes improving process time by 20%."]
        projects.append(
            {
                "name": str(proj.get("name") or "").strip(),
                "bullets": enforce_bullet_rules(
                    base,
                    used_verbs=global_used_verbs,
                    seen_bullets=global_seen_bullets,
                    skill_tokens=keywords,
                ),
            }
        )

    summary = (
        "Backend engineer aligning APIs and services to job requirements with measurable improvements "
        "in reliability, latency, and delivery speed."
    )
    summary = _fit_summary_length(summary)
    return {"summary": summary, "experiences": experiences, "projects": projects, "keywords": keywords}


def tailor_resume_with_ai(
    base_builder: dict,
    jd_text: str,
    jd_keywords,
    job_role: str = "",
    model_override: str | None = None,
    user=None,
):
    base_builder = sanitize_builder_data(base_builder or {})
    inferred_role = _infer_role_from_jd(jd_text)
    is_software_track = _is_software_track_role(job_role or inferred_role, jd_text)
    focus = _infer_resume_focus(jd_text, jd_keywords or [])
    focus_mode = focus.get("mode", "balanced")
    if focus_mode == "backend_heavy":
        focus_instruction = (
            "Make resume backend-heavy with light frontend signals where relevant "
            "so it can still read as practical full-stack."
        )
    elif focus_mode == "frontend_heavy":
        focus_instruction = (
            "Make resume frontend-heavy with light backend signals where relevant "
            "so it can still read as practical full-stack."
        )
    elif focus_mode == "balanced":
        focus_instruction = "Keep backend and frontend emphasis balanced (roughly 50/50) when both are required."
    else:
        focus_instruction = "Infer emphasis from JD language and prioritize the most demanded capabilities."

    if not is_software_track:
        focus_instruction = (
            "Treat this as a non-software-track role (Data Scientist/Data Analyst/ML/AI or similar); "
            "derive summary and bullets strictly from JD requirements and JD language."
        )

    name_locked_structure = {
        "experiences": [
            {
                "company": str(exp.get("company") or "").strip(),
                "title": str(exp.get("title") or "").strip(),
                "startDate": str(exp.get("startDate") or "").strip(),
                "endDate": str(exp.get("endDate") or "").strip(),
                "isCurrent": bool(exp.get("isCurrent")),
            }
            for exp in (base_builder.get("experiences") or [])
            if isinstance(exp, dict)
        ],
        "projects": [
            {"name": str(proj.get("name") or "").strip()}
            for proj in (base_builder.get("projects") or [])
            if isinstance(proj, dict)
        ],
    }

    system = (
        "You are an ATS resume tailoring assistant. Return strict JSON only. "
        "Rewrite summary, experience bullets, and project bullets for JD alignment. "
        "Use relevant JD skills naturally across summary, experiences, and projects. "
        "Summary must explicitly include '3+ years'. "
        f"{_bullet_count_rules_text()}"
        "Summary must be between 150 and 250 characters. "
        f"{_common_bullet_rules_text()}"
        "If the second project is agentic AI based, MCP is mandatory in that project's bullets. "
        "Never return placeholders, template instructions, or generic filler. "
        "Preserve company names and project names exactly as provided in the locked structure. "
        "Write with confident, human tone; avoid robotic or repetitive phrasing. "
        "Use ATS-friendly plain characters only (ASCII)."
    )

    user_prompt = (
        f"Target job role: {job_role or 'Not provided'}\n\n"
        "Job description:\n"
        f"{jd_text}\n\n"
        "Locked experience/project names (do not rename):\n"
        f"{json.dumps(name_locked_structure, ensure_ascii=False)}\n\n"
        "JD keywords:\n"
        f"{json.dumps(jd_keywords or [], ensure_ascii=False)}\n\n"
        "Focus guidance:\n"
        f"{focus_instruction}\n\n"
        "For non-software-track roles, do not reuse previous resume phrasing and do not rely on external source docs; "
        "frame all bullets directly from JD scope and expected outcomes.\n\n"
        "Return JSON object with keys:\n"
        "{\n"
        "  \"summary\": \"...\",\n"
        "  \"experiences\": [\n"
        "    {\n"
        "      \"company\": \"optional\",\n"
        "      \"title\": \"optional\",\n"
        "      \"startDate\": \"optional\",\n"
        "      \"endDate\": \"optional\",\n"
        "      \"isCurrent\": false,\n"
        "      \"bullets\": [\"...\", \"...\", \"...\"]\n"
        "    }\n"
        "  ],\n"
        "  \"projects\": [\n"
        "    {\n"
        "      \"name\": \"optional\",\n"
        "      \"bullets\": [\"...\", \"...\", \"...\"]\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
    result, ok, note = _generate_validated_ai_payload(
        system,
        user_prompt,
        max_rounds=4,
        require_summary=True,
        model_override=model_override,
        user=user,
    )
    if ok:
        return result, True, ""

    fallback_result, error = _openai_chat_json(system, user_prompt, model_override=model_override, user=user)
    if not error and isinstance(fallback_result, dict):
        normalized_fallback = _normalize_ai_payload_before_validation(
            fallback_result,
            require_summary=True,
            model_override=model_override,
        )
        valid, issues = _validate_payload_rules(
            normalized_fallback,
            require_summary=True,
            model_override=model_override,
        )
        if valid:
            return normalized_fallback, True, ""
        repaired, repaired_ok, repaired_note = _repair_payload_with_ai(
            system,
            user_prompt,
            normalized_fallback,
            issues,
            require_summary=True,
            model_override=model_override,
            user=user,
        )
        if repaired_ok:
            return repaired, True, ""
        return {}, False, repaired_note or note
    return {}, False, note


@dataclass
class MatchResult:
    score: float
    matched_keywords: list
    resume: object


def find_best_resume_match(jd_keywords, resumes):
    best = MatchResult(score=0.0, matched_keywords=[], resume=None)
    for resume in resumes:
        text = str(getattr(resume, "original_text", "") or "").strip()
        if not text:
            text = builder_data_to_text(getattr(resume, "builder_data", {}) or {})
        score, matched = score_resume_keyword_match(jd_keywords, text)
        if score > best.score:
            best = MatchResult(score=score, matched_keywords=matched, resume=resume)
    return best
