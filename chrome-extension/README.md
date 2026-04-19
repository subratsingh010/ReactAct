# ApplyPilot Companion Chrome Extension

This extension helps save job and employee data into ReactAct while browsing supported pages.

## What It Solves

Manual job tracking is slow and error-prone. People usually copy:

- company name
- job title
- job link
- recruiter or employee details
- notes from the page

This extension reduces that manual work by capturing data directly and sending it into the app.

## Main Features

- side panel interface
- backend login with username and password
- JWT-based API access
- save jobs into the app
- save employee details into the app
- fetch form metadata from backend
- request permission dynamically for the API host you enter

## Important

- this extension does not use Django admin login
- it does not reuse web app session cookies
- it logs in through `/api/token/`

## Load The Extension

1. Open `chrome://extensions/`
2. Turn on `Developer mode`
3. Click `Load unpacked`
4. Select the `chrome-extension` folder

## API Base

Use one of these:

- local: `http://127.0.0.1:8000/api`
- server with IP: `http://YOUR_SERVER_IP/api`
- server with domain: `https://YOUR_DOMAIN/api`

Do not use:

- `http://YOUR_SERVER_IP/admin`
- the bare site URL without the `/api` base

## Login Flow

1. Open the side panel
2. Enter API base
3. Enter backend username
4. Enter backend password
5. Click `Login`
6. Accept the permission prompt if Chrome shows it

## Backend Requirements

The backend must expose:

- `POST /api/token/`
- `POST /api/token/refresh/`
- `GET /api/extension/form-meta/`
- `POST /api/extension/jobs/`
- `POST /api/extension/employees/`

## Common Problems

### Login fails

- confirm the API base ends with `/api`
- reload the extension
- check that the backend user exists
- verify backend CORS if using a remote host

### Admin works but extension does not

- admin auth and extension auth are different
- admin success does not prove extension permission or CORS is correct

### Host changed

- enter the new API base
- allow the new origin when Chrome asks

## Screenshot

Add extension screenshots in `docs/screenshots/`.

Recommended image:

- Chrome extension side panel after login
