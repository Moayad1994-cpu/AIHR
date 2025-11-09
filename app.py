
import os
import sqlite3
from datetime import datetime, timedelta
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, send_from_directory, jsonify
)
from werkzeug.utils import secure_filename

# ---- Optional: load .env (GROQ_API_KEY, GROQ_MODEL_ID) ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ===================== Basic Config =====================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "app.db")
DEFAULT_UPLOADS = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "xlsx", "xls", "zip"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", DEFAULT_UPLOADS)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ===================== Helpers =====================
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def _bootstrap_default_settings_table():
    with sqlite3.connect(DEFAULT_DB) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS settings(
                 id INTEGER PRIMARY KEY,
                 company_name TEXT,
                 company_db_path TEXT,
                 upload_folder TEXT
            )"""
        )
        cur = con.execute("SELECT id FROM settings WHERE id=1")
        if not cur.fetchone():
            con.execute(
                "INSERT INTO settings (id, company_name, company_db_path, upload_folder) VALUES (1, ?, ?, ?)",
                ("My Company", "", app.config["UPLOAD_FOLDER"]),
            )

def get_db_path() -> str:
    """Reads the active company DB path from DEFAULT_DB; falls back to DEFAULT_DB."""
    _bootstrap_default_settings_table()
    with sqlite3.connect(DEFAULT_DB) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT company_db_path FROM settings WHERE id=1").fetchone()
        if row and row["company_db_path"]:
            path = row["company_db_path"]
            # ensure directory exists if a full path was provided
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            return path
    return DEFAULT_DB

def init_schema(db_path: str):
    """Create necessary tables if they don't exist."""
    with sqlite3.connect(db_path) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS requests(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 request_no TEXT,
                 employee_id TEXT,
                 employee_name TEXT,
                 cluster TEXT,
                 department TEXT,
                 category TEXT,
                 request_type TEXT,
                 details TEXT,
                 status TEXT,
                 assignee TEXT,
                 duration_days INTEGER,
                 created_at TEXT,
                 updated_at TEXT
            )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS attachments(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 request_id INTEGER,
                 filename TEXT,
                 path TEXT,
                 uploaded_at TEXT
            )"""
        )

# ensure schemas exist for default bootstrap DB
init_schema(get_db_path())
_bootstrap_default_settings_table()

# ===================== Simple Automation =====================
AUTO_ASSIGN = {
    "Documents & Letters": "HRSS-Docs Team",
    "Personal Data Updates": "HRSS-Personnel Team",
    "Attendance & Schedule": "HRSS-Attendance Team",
    "IT Requests": "IT Support",
    "Card Issue / Replacement": "Admin Services",
    "Health Insurance": "Benefits Team",
    "Other HR Support": "HRSS-General",
}
SLA_DAYS = {
    "Documents & Letters": 2,
    "Personal Data Updates": 3,
    "Attendance & Schedule": 2,
    "IT Requests": 1,
    "Card Issue / Replacement": 2,
    "Health Insurance": 3,
    "Other HR Support": 3,
}

def gen_request_no() -> str:
    return datetime.utcnow().strftime("%y%m%d%H%M%S")

# ===================== Routes: UI =====================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        company_db_path = request.form.get("company_db_path", "").strip()
        upload_folder = request.form.get("upload_folder", "").strip()

        if upload_folder:
            os.makedirs(upload_folder, exist_ok=True)
            app.config["UPLOAD_FOLDER"] = upload_folder

        with sqlite3.connect(DEFAULT_DB) as con:
            con.execute(
                """INSERT INTO settings (id, company_name, company_db_path, upload_folder)
                   VALUES (1, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     company_name=excluded.company_name,
                     company_db_path=excluded.company_db_path,
                     upload_folder=excluded.upload_folder
                """,
                (company_name, company_db_path, app.config["UPLOAD_FOLDER"]),
            )

        # Ensure target DB has the schema
        init_schema(get_db_path())
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))

    with sqlite3.connect(DEFAULT_DB) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM settings WHERE id=1").fetchone()
    return render_template("settings.html", settings=row)

@app.route("/requests/new", methods=["GET", "POST"])
def new_request():
    if request.method == "POST":
        data = {
            "employee_id": request.form.get("employee_id", "").strip(),
            "employee_name": request.form.get("employee_name", "").strip(),
            "cluster": request.form.get("cluster", "").strip(),
            "department": request.form.get("department", "").strip(),
            "category": request.form.get("category", "").strip(),
            "request_type": request.form.get("request_type", "").strip(),
            "details": request.form.get("details", "").strip(),
        }
        data["status"] = "Submitted"
        data["assignee"] = AUTO_ASSIGN.get(data["category"], "HRSS-General")
        data["duration_days"] = SLA_DAYS.get(data["category"], 3)
        data["request_no"] = gen_request_no()
        now = datetime.utcnow().isoformat()

        db_path = get_db_path()
        init_schema(db_path)
        with sqlite3.connect(db_path) as con:
            con.execute(
                """INSERT INTO requests
                   (request_no, employee_id, employee_name, cluster, department, category, request_type, details, status, assignee, duration_days, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["request_no"], data["employee_id"], data["employee_name"],
                    data["cluster"], data["department"], data["category"], data["request_type"],
                    data["details"], data["status"], data["assignee"], data["duration_days"], now, now,
                ),
            )
            req_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # attachments
        for f in request.files.getlist("attachments"):
            if f and allowed_file(f.filename):
                filename = secure_filename(f.filename)
                savepath = os.path.join(app.config["UPLOAD_FOLDER"], f"{data['request_no']}_{filename}")
                f.save(savepath)
                with sqlite3.connect(db_path) as con:
                    con.execute(
                        "INSERT INTO attachments (request_id, filename, path, uploaded_at) VALUES (?, ?, ?, ?)",
                        (req_id, filename, savepath, now),
                    )

        flash("Request submitted successfully.", "success")
        return redirect(url_for("view_request", request_no=data["request_no"]))

    return render_template("new_request.html", categories=list(AUTO_ASSIGN.keys()))

@app.route("/requests")
def list_requests():
    db_path = get_db_path()
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM requests ORDER BY created_at DESC").fetchall()
    return render_template("list_requests.html", rows=rows)

@app.route("/requests/<request_no>")
def view_request(request_no):
    db_path = get_db_path()
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        req = con.execute("SELECT * FROM requests WHERE request_no=?", (request_no,)).fetchone()
        att = con.execute(
            """SELECT * FROM attachments WHERE request_id = (
                   SELECT id FROM requests WHERE request_no = ?
               )""",
            (request_no,),
        ).fetchall()
    if not req:
        flash("Request not found.", "danger")
        return redirect(url_for("list_requests"))

    created = datetime.fromisoformat(req["created_at"])
    eta = created + timedelta(days=req["duration_days"] or 0)
    return render_template("view_request.html", req=req, attachments=att, eta=eta.strftime("%Y-%m-%d"))

@app.route("/requests/<request_no>/update", methods=["POST"])
def update_status(request_no):
    new_status = request.form.get("status")
    assignee = request.form.get("assignee")
    db_path = get_db_path()
    with sqlite3.connect(db_path) as con:
        con.execute(
            "UPDATE requests SET status=?, assignee=?, updated_at=? WHERE request_no=?",
            (new_status, assignee, datetime.utcnow().isoformat(), request_no),
        )
    flash("Request updated.", "success")
    return redirect(url_for("view_request", request_no=request_no))

@app.route("/download/<path:filename>")
def download_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)

# ===================== Groq Chatbot =====================
# Uses GROQ_API_KEY; tries to pick a currently available model automatically.
# You can force a model via env GROQ_MODEL_ID.
def _pick_groq_model(client, override: str = "") -> str:
    """
    Pick a supported Groq chat model.
    Strategy:
      1) If override is provided and available -> use it.
      2) Else list models and choose from a preferred order.
      3) Else pick the first model that starts with 'llama'.
      4) Fallback to a safe default name.
    """
    preferred = [
        # Commonly available, low-latency options first:
        "llama-3.1-8b-instant",
        "llama-3.2-3b-preview",
        "llama-3.2-11b-text-preview",
        "llama-3.1-70b-instant",
        "llama-3.1-8b-instant-fp16",
    ]
    try:
        models_obj = client.models.list()  # returns object with .data
        available = {m.id for m in getattr(models_obj, "data", []) if getattr(m, "id", None)}
        if override and override in available:
            return override
        for m in preferred:
            if m in available:
                return m
        for mid in available:
            if str(mid).startswith("llama"):
                return mid
    except Exception:
        # If listing fails (network/permission), still try override or default
        if override:
            return override
    return "llama-3.1-8b-instant"

@app.route("/api/chat", methods=["POST"])
def api_chat():
    try:
        payload = request.get_json(silent=True) or {}
        user_message = (payload.get("message") or "")[:4000]
        if not user_message:
            return jsonify({"error": "Empty message"}), 400

        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            return jsonify({"error": "GROQ_API_KEY not set"}), 400

        from groq import Groq
        client = Groq(api_key=api_key)

        override_model = os.environ.get("GROQ_MODEL_ID", "").strip()
        model_id = _pick_groq_model(client, override_model)

        system_prompt = (
            "You are Absher HR Assistant, a helpful, factual HR expert with 20 years of experience "
            "in HR operations, shared services, policies, payroll, benefits, attendance rules, and employee relations. "
            "Answer briefly and clearly in the language of the user's message (Arabic or English). "
            "If the user asks about a specific company policy that you don't know, ask clarifying questions."
            "also any user ask you about anything realted platform like request number you should give him all detilas about this based on Req #	Employee	Category	Type	Status	Assignee	Created"
        )

        resp = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            top_p=0.9,
            max_tokens=512,
        )

        text = (resp.choices[0].message.content if resp and getattr(resp, "choices", None) else "") or ""
        if not text:
            text = f"(No text returned from {model_id})"

        return jsonify({"reply": text, "model": model_id})
    except Exception as e:
        # Provide concise error back to the widget
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

# ===================== Main =====================
if __name__ == "__main__":
    # Flask dev server
    app.run(host="0.0.0.0", port=5000, debug=True)
