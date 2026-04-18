# Resume Tailor + AutoFill Chrome Extension

## Features
- Fetch JD from current web page.
- Upload reference resume PDF.
- Tailor resume via backend and save in DB.
- Store job metadata (company, title, job id, URL) with tailored run.
- Auto-fill forms using predefined answers.
- AI fallback for unanswered form questions.
- Attempts resume upload on file inputs (`resume`, `cv`, `upload` labels).

## Setup
1. Start backend at `http://127.0.0.1:8000`.
2. Ensure backend env has:
   - `OPENAI_API_KEY`
   - `OPENAI_MODEL=gpt-4o`
3. Run migrations:
   - `python manage.py migrate`
4. Open Chrome: `chrome://extensions`
5. Enable **Developer mode**
6. Click **Load unpacked**
7. Select folder: `chrome-extension`

## How to use
Apollo-like side panel is enabled.

1. Click extension icon.
2. Side panel opens with:
   - Job Create form
   - Employee Create form
3. Fetch job data from page and save via extension APIs.

For autofill:
1. Add predefined answers JSON.
2. Optionally keep `Use AI` enabled.
3. Click `Scan Questions`.
4. Click `AutoFill Form`.
