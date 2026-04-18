# ReactAct (React + Django/DRF)

Resume Builder + ATS Analyzer.

## Project Structure

- `frontend/` React (Vite)
- `backend/` Django + DRF (SQLite by default)

## Prerequisites

- Node.js + npm
- Miniconda/Conda (you are using `agent`)

## Backend (Django)

```bash
cd backend

# activate conda env
source ./etc/profile.d/conda.sh
conda activate agent

# install deps
pip install -r requirements.txt

# migrate + run
python manage.py migrate
python manage.py runserver 8000
```

API health: `http://127.0.0.1:8000/api/health/`

## Frontend (React)

```bash
cd frontend

# install deps
npm install

# run dev server
npm run dev
```

App: `http://localhost:5173/`

## Run Both Together (2 terminals)

Terminal A:

```bash
cd backend
source ./etc/profile.d/conda.sh
conda activate agent
python manage.py runserver 8000
```

Terminal B:

```bash
cd frontend
npm run dev
```

## Auth + Pages

- Public: `/login`, `/register`
- Auth required: `/`, `/dashboard`, `/builder`, `/preview/:id`

## Notes

- Resumes: backend keeps the latest **6** resumes per user (older resumes are deleted when you save a new one beyond the limit).
- Analyses: analyses are kept long-term even if an old resume record is deleted (analysis stores a snapshot title).
