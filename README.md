# Absher Platform (Flask + HTML/CSS/JS)

Bilingual HR Shared Services request platform with:
- Modern UI (HTML/CSS/JS), Arabic & English UI toggle
- Flask backend (SQLite), file uploads, status workflow, SLA, auto-routing
- Admin settings: company DB path & uploads folder
- AI chatbot via Google Gemini (set GEMINI_API_KEY)

## Quick Start

```bash
python -m venv .venv && . .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install flask google-generativeai
export GEMINI_API_KEY=your_key_here           # Windows PowerShell: $env:GEMINI_API_KEY="..."
export FLASK_ENV=development
python app.py
```

Open http://localhost:5000

## Configure Company DB Path
Go to **Settings** and set the SQLite path for company DB (e.g., `/absolute/path/company.db`). The app will create required tables and store requests there.

## Folders
- `templates/` Jinja2 templates
- `static/css/` styles
- `static/js/` JavaScript
- `uploads/` saved attachments

## Notes
- Allowed file types can be edited in `ALLOWED_EXTENSIONS` in `app.py`
- Simple automation: auto-assign assignee and SLA based on category
- Status flow: Submitted → Under Review → Processing → Completed
- Chatbot replies in Arabic or English depending on user input language
