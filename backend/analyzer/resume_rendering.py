import io
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from pypdf import PdfReader
except Exception:  # noqa: BLE001
    PdfReader = None


def builder_data_hash(builder_data) -> str:
    if not isinstance(builder_data, dict):
        builder_data = {}
    payload = json.dumps(builder_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sanitize_pdf_filename_stem(raw: str) -> str:
    value = str(raw or "").strip()
    value = " ".join(value.split())
    value = "".join(ch for ch in value if ch.isalnum() or ch in {" ", "_", "-"})
    value = value.strip("._- ")
    value = value.replace("-", " ")
    value = "_".join(part for part in value.split(" ") if part).strip("._-").lower()
    return value or "resume"


def default_pdf_filename(builder_data: dict, resume=None) -> str:
    data = builder_data if isinstance(builder_data, dict) else {}
    full_name = str(data.get("fullName") or "").strip()
    parts = []
    if full_name:
        parts.append(full_name)
    elif str(getattr(resume, "title", "") or "").strip():
        parts.append(str(getattr(resume, "title", "") or "").strip())

    resume_job = getattr(resume, "job", None) if resume else None
    company_name = ""
    job_code = ""
    if resume_job:
        job_code = str(getattr(resume_job, "job_id", "") or "").strip()
        company = getattr(resume_job, "company", None)
        company_name = str(getattr(company, "name", "") or "").strip()

    if company_name:
        parts.append(company_name)
    if job_code:
        parts.append(job_code)
    if not company_name:
        parts.append("3 YOE")

    stem = sanitize_pdf_filename_stem(" - ".join([part for part in parts if part]) or "Resume")
    return f"{stem}.pdf"


def pick_local_pdf_path(file_name: str, resume_id: int | None = None) -> Path:
    target_dir = Path(__file__).resolve().parents[1] / "storage" / "ats_pdfs"
    target_dir.mkdir(parents=True, exist_ok=True)
    if resume_id:
        return target_dir / f"resume_{int(resume_id)}.pdf"
    stem = sanitize_pdf_filename_stem(Path(str(file_name or "")).stem)
    return target_dir / f"{stem}.pdf"


def available_browser_binaries():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    return [path for path in candidates if Path(path).exists()]


def render_pdf_from_html(html_text: str, output_pdf: Path):
    browser_bins = available_browser_binaries()
    if not browser_bins:
        return False, "Chrome/Brave not found on this machine."

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(str(html_text or ""))
        tmp_html_path = Path(tmp.name)

    html_url = tmp_html_path.as_uri()
    errors = []
    try:
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        for browser_bin in browser_bins:
            cmd = [
                browser_bin,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--no-pdf-header-footer",
                f"--print-to-pdf={str(output_pdf)}",
                html_url,
            ]
            try:
                run = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
                if run.returncode == 0 and output_pdf.exists() and output_pdf.stat().st_size > 0:
                    return True, ""
                stderr = (run.stderr or "").strip()
                stdout = (run.stdout or "").strip()
                snippet = stderr or stdout or f"exit code {run.returncode}"
                errors.append(f"{Path(browser_bin).name}: {snippet[:220]}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{Path(browser_bin).name}: {exc}")
        return False, "; ".join(errors) or "PDF generation failed."
    finally:
        try:
            tmp_html_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def render_pdf_bytes_from_html(html_text: str):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        output_pdf = Path(tmp_pdf.name)
    try:
        ok, _note = render_pdf_from_html(html_text, output_pdf)
        if ok and output_pdf.exists() and output_pdf.stat().st_size > 0:
            return output_pdf.read_bytes()
        return None
    finally:
        try:
            output_pdf.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def pdf_page_count(pdf_bytes):
    if not pdf_bytes or PdfReader is None:
        return 0
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return len(reader.pages or [])
    except Exception:
        return 0


def build_frontend_ats_pdf_html(builder_data, preserve_highlights=False):
    if not isinstance(builder_data, dict) or not builder_data:
        return ""
    node_bin = shutil.which("node")
    if not node_bin:
        return ""

    project_root = Path(__file__).resolve().parents[2]
    module_path = project_root / "frontend" / "src" / "utils" / "resumeExport.js"
    if not module_path.exists():
        return ""

    function_name = "buildAtsPdfHtmlPreserveHighlights" if preserve_highlights else "buildAtsPdfHtml"
    script = (
        "import fs from 'node:fs';"
        "import { %s } from 'file://%s';"
        "const raw = fs.readFileSync(process.argv[1], 'utf8');"
        "const form = JSON.parse(raw || '{}');"
        "process.stdout.write(%s(form));"
    ) % (function_name, str(module_path).replace("\\", "/"), function_name)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp_json:
        json.dump(builder_data, tmp_json)
        tmp_json_path = Path(tmp_json.name)

    try:
        run = subprocess.run(
            [node_bin, "--experimental-specifier-resolution=node", "--input-type=module", "-e", script, str(tmp_json_path)],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            cwd=str(project_root),
        )
        if run.returncode == 0:
            return str(run.stdout or "").strip()
        return ""
    except Exception:
        return ""
    finally:
        tmp_json_path.unlink(missing_ok=True)


def build_builder_pdf_bytes(builder_data, preserve_highlights=False):
    html_text = build_frontend_ats_pdf_html(builder_data, preserve_highlights=preserve_highlights)
    if not html_text:
        return None
    return render_pdf_bytes_from_html(html_text)
