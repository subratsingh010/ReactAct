import io
import json
import shutil
import subprocess
import tempfile
import os
from pathlib import Path

try:
    from pypdf import PdfReader
except Exception:  # noqa: BLE001
    PdfReader = None


def available_browser_binaries():
    candidates = [
        str(os.getenv("CHROME_BIN") or "").strip(),
        str(os.getenv("GOOGLE_CHROME_BIN") or "").strip(),
        str(os.getenv("CHROMIUM_BIN") or "").strip(),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]
    for command_name in [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "brave-browser",
    ]:
        resolved = shutil.which(command_name)
        if resolved:
            candidates.append(resolved)

    seen = set()
    binaries = []
    for path in candidates:
        normalized = str(path or "").strip()
        if not normalized or normalized in seen:
            continue
        if Path(normalized).exists():
            binaries.append(normalized)
            seen.add(normalized)
    return binaries


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
