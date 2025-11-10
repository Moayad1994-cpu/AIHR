import os
import sqlite3
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from sqlite3 import IntegrityError

# ---- Optional: load .env ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "absher.db")
DEFAULT_UPLOADS = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "xlsx", "xls", "zip"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", DEFAULT_UPLOADS)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ===================== Helpers & Bootstrapping =====================
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def _bootstrap_default_settings_table():
    with sqlite3.connect(DEFAULT_DB) as con:
        cur = con.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY)""")
        cur.execute("PRAGMA table_info(settings)")
        cols = {row[1] for row in cur.fetchall()}
        if "company_name" not in cols:   cur.execute("ALTER TABLE settings ADD COLUMN company_name TEXT")
        if "company_db_path" not in cols:cur.execute("ALTER TABLE settings ADD COLUMN company_db_path TEXT")
        if "upload_folder" not in cols:  cur.execute("ALTER TABLE settings ADD COLUMN upload_folder TEXT")
        cur.execute("SELECT id FROM settings WHERE id=1")
        if not cur.fetchone():
            cur.execute("INSERT INTO settings (id, company_name, company_db_path, upload_folder) VALUES (1, ?, ?, ?)",
                        ("My Company", "", app.config["UPLOAD_FOLDER"]))
        else:
            cur.execute("""UPDATE settings
                           SET company_name=COALESCE(company_name,'My Company'),
                               company_db_path=COALESCE(company_db_path,''),
                               upload_folder=COALESCE(upload_folder,?)
                           WHERE id=1""", (app.config["UPLOAD_FOLDER"],))
        con.commit()

def get_db_path() -> str:
    _bootstrap_default_settings_table()
    with sqlite3.connect(DEFAULT_DB) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT company_db_path FROM settings WHERE id=1").fetchone()
        if row and row["company_db_path"]:
            path = row["company_db_path"]
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            return path
    return DEFAULT_DB

def init_schema(db_path: str):
    with sqlite3.connect(db_path) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS requests(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 request_no TEXT UNIQUE,
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
                 uploaded_at TEXT,
                 FOREIGN KEY(request_id) REFERENCES requests(id)
            )"""
        )

def _ensure_column(con, table, col, ddl_type):
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = {r[1] for r in cur.fetchall()}
    if col not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl_type}")

def ensure_schema_compat(db_path: str):
    """ترقيات آمنة لأي قاعدة قديمة (بدون فقد بيانات)."""
    with sqlite3.connect(db_path) as con:
        for name, t in [
            ("request_no","TEXT"),("employee_id","TEXT"),("employee_name","TEXT"),
            ("cluster","TEXT"),("department","TEXT"),("category","TEXT"),
            ("request_type","TEXT"),("details","TEXT"),("status","TEXT"),
            ("assignee","TEXT"),("duration_days","INTEGER"),
            ("created_at","TEXT"),("updated_at","TEXT")
        ]:
            _ensure_column(con, "requests", name, t)

        cur = con.cursor()
        cur.execute("PRAGMA table_info(attachments)")
        rows = cur.fetchall()
        acols = {r[1] for r in rows}
        if "path" not in acols and "filepath" not in acols:
            cur.execute("ALTER TABLE attachments ADD COLUMN path TEXT")
        if "filename" not in acols:
            cur.execute("ALTER TABLE attachments ADD COLUMN filename TEXT")
        if "request_id" not in acols:
            cur.execute("ALTER TABLE attachments ADD COLUMN request_id INTEGER")
        if "uploaded_at" not in acols:
            cur.execute("ALTER TABLE attachments ADD COLUMN uploaded_at TEXT")

        # املأ filepath من path لو كان NOT NULL
        notnull_map = {r[1]: bool(r[3]) for r in rows}
        if "filepath" in acols and notnull_map.get("filepath", False):
            cur.execute("UPDATE attachments SET filepath = COALESCE(filepath, path) WHERE filepath IS NULL AND path IS NOT NULL")

        con.commit()

def discover_attachment_cols(db_path: str):
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("PRAGMA table_info(attachments)")
        rows = cur.fetchall()
    cols = {r[1] for r in rows}
    notnull = {r[1]: bool(r[3]) for r in rows}
    return {
        "has_path": "path" in cols,
        "has_filepath": "filepath" in cols,
        "filepath_notnull": notnull.get("filepath", False)
    }

def generate_unique_request_no(con, desired: str) -> str:
    cur = con.cursor()
    if not desired:
        cur.execute("SELECT request_no FROM requests")
        nums = []
        for (rn,) in cur.fetchall():
            if rn is None: continue
            s = str(rn)
            num = ""
            for ch in s:
                if ch.isdigit(): num += ch
                else: break
            if num: nums.append(int(num))
        next_no = (max(nums) + 1) if nums else 1
        return str(next_no)
    cur.execute("SELECT 1 FROM requests WHERE request_no=?", (desired,))
    if not cur.fetchone():
        return desired
    i = 1
    while True:
        candidate = f"{desired}-{i}"
        cur.execute("SELECT 1 FROM requests WHERE request_no=?", (candidate,))
        if not cur.fetchone():
            return candidate
        i += 1

def migrate_old_requests_if_empty(active_db: str):
    """
    لو القاعدة النشطة فاضية والافتراضية فيها بيانات، ننقل الطلبات + المرفقات مرة واحدة.
    """
    old_db = DEFAULT_DB
    if os.path.abspath(active_db) == os.path.abspath(old_db):
        return

    def count(db):
        try:
            with sqlite3.connect(db) as con:
                cur = con.execute("SELECT COUNT(*) FROM requests")
                return cur.fetchone()[0]
        except sqlite3.Error:
            return 0

    new_count = count(active_db)
    old_count = count(old_db)
    if new_count > 0 or old_count == 0:
        return

    init_schema(active_db); ensure_schema_compat(active_db)
    init_schema(old_db);    ensure_schema_compat(old_db)

    with sqlite3.connect(old_db) as src, sqlite3.connect(active_db) as dst:
        src.row_factory = sqlite3.Row
        rows = src.execute("SELECT * FROM requests").fetchall()
        for r in rows:
            dst.execute(
                """INSERT OR IGNORE INTO requests
                   (request_no, employee_id, employee_name, cluster, department, category, request_type,
                    details, status, assignee, duration_days, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r["request_no"], r["employee_id"], r["employee_name"], r["cluster"], r["department"],
                    r["category"], r["request_type"], r["details"], r["status"], r["assignee"],
                    r["duration_days"], r["created_at"], r["updated_at"]
                )
            )
        def att_col(db):
            with sqlite3.connect(db) as con2:
                cur = con2.execute("PRAGMA table_info(attachments)")
                cols = {row[1] for row in cur.fetchall()}
                return "filepath" if "filepath" in cols else "path"
        src_path_col = att_col(old_db)
        dst_path_col = att_col(active_db)

        atts = src.execute("SELECT * FROM attachments").fetchall()
        for a in atts:
            dst.execute(
                f"INSERT OR IGNORE INTO attachments (request_id, filename, {dst_path_col}, uploaded_at) VALUES (?,?,?,?)",
                (a["request_id"], a["filename"], a[src_path_col], a["uploaded_at"])
            )
        dst.commit()

# bootstrap
db_path_boot = get_db_path()
init_schema(db_path_boot)
ensure_schema_compat(db_path_boot)
migrate_old_requests_if_empty(db_path_boot)

# ===================== Routes =====================
@app.route("/")
def index():
    return render_template("index.html")

# alias لتوافق url_for('home') في القوالب
@app.route("/home", endpoint="home")
def _home_alias():
    return index()

@app.route("/dashboard")
def dashboard():
    db_path = get_db_path()
    ensure_schema_compat(db_path)
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM requests ORDER BY datetime(COALESCE(updated_at, created_at)) DESC").fetchall()

    def g(r, k, default=None):
        try: return r[k]
        except Exception: return default

    total = len(rows)
    status_counts = {"Submitted":0, "In Progress":0, "Completed":0, "Rejected":0}
    cat_counts, team_counts = {}, {}
    last7 = [(date.today()-timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6,-1,-1)]
    timeline_counts = {d:0 for d in last7}

    for r in rows:
        st = (g(r,"status") or "Submitted").strip()
        status_counts[st] = status_counts.get(st,0)+1
        cat = (g(r,"category") or "Other").strip() or "Other"
        cat_counts[cat] = cat_counts.get(cat,0)+1
        team = (g(r,"assignee") or "Unassigned").strip() or "Unassigned"
        team_counts[team] = team_counts.get(team,0)+1
        created = (g(r,"created_at") or "")[:10]
        if created in timeline_counts: timeline_counts[created]+=1

    stats = {
        "total": total,
        "submitted": status_counts.get("Submitted",0),
        "in_progress": status_counts.get("In Progress",0),
        "completed": status_counts.get("Completed",0),
        "rejected": status_counts.get("Rejected",0),
        "category_labels": list(cat_counts.keys()),
        "category_values": list(cat_counts.values()),
        "by_team": team_counts,
        "timeline_labels": last7,
        "timeline_values": [timeline_counts[d] for d in last7],
    }
    recent_requests = rows[:10]
    return render_template("dashboard.html", stats=stats, recent_requests=recent_requests)

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
        init_schema(get_db_path())
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))
    with sqlite3.connect(DEFAULT_DB) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM settings WHERE id=1").fetchone()
    return render_template("settings.html", settings=row)

AUTO_ASSIGN = {
    "شؤون الموظفين": {"أنواع": ["اجازة", "شهادة تعريف", "تحديث بيانات"], "مسؤول": "HR Team"},
    "الدعم التقني": {"أنواع": ["صلاحيات نظام", "بلاغ تقني", "حاسوب"], "مسؤول": "IT Team"},
    "اللوجستيات": {"أنواع": ["سيارة", "معدات", "مخزن"], "مسؤول": "Logistics Team"},
}

@app.route("/requests/new", methods=["GET", "POST"])
def new_request():
    if request.method == "POST":
        raw_request_no = (request.form.get("request_no") or "").strip()
        data = {
            "employee_id": request.form.get("employee_id", "").strip(),
            "employee_name": request.form.get("employee_name", "").strip(),
            "cluster": request.form.get("cluster", "").strip(),
            "department": request.form.get("department", "").strip(),
            "category": request.form.get("category", "").strip(),
            "request_type": request.form.get("request_type", "").strip(),
            "details": request.form.get("details", "").strip(),
            "duration_days": int(request.form.get("duration_days") or 0),
        }

        auto = AUTO_ASSIGN.get(data["category"], {})
        assignee = auto.get("مسؤول", "")
        status = "Submitted"
        now = datetime.utcnow().isoformat()

        db_path = get_db_path()
        init_schema(db_path)
        ensure_schema_compat(db_path)

        with sqlite3.connect(db_path) as con:
            request_no = generate_unique_request_no(con, raw_request_no)

        try:
            with sqlite3.connect(db_path) as con:
                con.execute(
                    """INSERT INTO requests
                       (request_no, employee_id, employee_name, cluster, department,
                        category, request_type, details, status, assignee, duration_days, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        request_no, data["employee_id"], data["employee_name"],
                        data["cluster"], data["department"], data["category"], data["request_type"],
                        data["details"], status, assignee, data["duration_days"], now, now,
                    ),
                )
                req_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        except IntegrityError:
            with sqlite3.connect(db_path) as con:
                request_no = generate_unique_request_no(con, request_no)
                con.execute(
                    """INSERT INTO requests
                       (request_no, employee_id, employee_name, cluster, department,
                        category, request_type, details, status, assignee, duration_days, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        request_no, data["employee_id"], data["employee_name"],
                        data["cluster"], data["department"], data["category"], data["request_type"],
                        data["details"], status, assignee, data["duration_days"], now, now,
                    ),
                )
                req_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        ac = discover_attachment_cols(db_path)
        for f in request.files.getlist("attachments"):
            if f and allowed_file(f.filename):
                filename = secure_filename(f.filename)
                savepath = os.path.join(app.config["UPLOAD_FOLDER"], f"{request_no}_{filename}")
                f.save(savepath)
                with sqlite3.connect(db_path) as con:
                    if ac["has_path"] and ac["has_filepath"]:
                        con.execute(
                            "INSERT INTO attachments (request_id, filename, path, filepath, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                            (req_id, filename, savepath, savepath, now),
                        )
                    elif ac["has_filepath"]:
                        con.execute(
                            "INSERT INTO attachments (request_id, filename, filepath, uploaded_at) VALUES (?, ?, ?, ?)",
                            (req_id, filename, savepath, now),
                        )
                    else:
                        con.execute(
                            "INSERT INTO attachments (request_id, filename, path, uploaded_at) VALUES (?, ?, ?, ?)",
                            (req_id, filename, savepath, now),
                        )

        if raw_request_no and raw_request_no != request_no:
            flash(f"رقم الطلب '{raw_request_no}' كان مستخدمًا؛ تم حفظ الطلب بالرقم: {request_no}", "warning")
        else:
            flash("Request submitted successfully.", "success")

        return redirect(url_for("view_request", request_no=request_no))

    return render_template("new_request.html", categories=list(AUTO_ASSIGN.keys()))

@app.route("/requests")
def list_requests():
    """تعرض كل الطلبات بترتيب الأحدث أولًا."""
    db_path = get_db_path()
    ensure_schema_compat(db_path)
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM requests ORDER BY datetime(created_at) DESC").fetchall()
    # 🔧 المهم: القالب يتوقع المتغيّر 'rows'
    return render_template("list_requests.html", rows=rows)

@app.route("/requests/<request_no>")
def view_request(request_no):
    db_path = get_db_path()
    ensure_schema_compat(db_path)
    ac = discover_attachment_cols(db_path)
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        req = con.execute("SELECT * FROM requests WHERE request_no=?", (request_no,)).fetchone()
        att_rows = con.execute(
            """SELECT * FROM attachments WHERE request_id = (
                   SELECT id FROM requests WHERE request_no = ?
               )""",
            (request_no,),
        ).fetchall()
    if not req:
        flash("Request not found.", "danger")
        return redirect(url_for("list_requests"))

    import os as _os
    attachments = []
    for r in att_rows:
        if ac["has_filepath"] and ("filepath" in r.keys()) and r["filepath"]:
            disk_path = r["filepath"]
        else:
            disk_path = r["path"] if "path" in r.keys() else ""
        serve_name = _os.path.basename(disk_path or r["filename"])
        attachments.append({
            "id": r["id"],
            "filename": r["filename"],
            "serve_name": serve_name,
            "uploaded_at": r["uploaded_at"],
        })

    created = datetime.fromisoformat((req["created_at"] or datetime.utcnow().isoformat()))
    eta = created + timedelta(days=req["duration_days"] or 0)
    return render_template("view_request.html", req=req, attachments=attachments, eta=eta.strftime("%Y-%m-%d"))

@app.route("/requests/<request_no>/update", methods=["POST"])
def update_status(request_no):
    new_status = request.form.get("status")
    assignee = request.form.get("assignee")
    db_path = get_db_path()
    ensure_schema_compat(db_path)
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

@app.route("/view/<path:filename>")
def view_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

# ===================== Groq Chatbot (اختياري) =====================
def _pick_groq_model(client, override: str = "") -> str:
    preferred = [
        "llama-3.1-8b-instant","llama-3.1-70b-versatile",
        "llama-3.2-90b-vision-preview","llama-3.2-11b-vision-preview",
        "llama-guard-3-8b",
    ]
    if override: return override
    try:
        models = client.models.list()
        ids = [m.id for m in getattr(models, "data", [])]
        for m in preferred:
            if m in ids: return m
    except Exception:
        pass
    return preferred[0]

@app.route("/api/chat", methods=["POST"])
def chat_api():
    try:
        from groq import Groq
        client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
        payload = request.get_json(force=True) or {}
        user_message = (payload.get("message") or "").strip()
        override_model = (payload.get("model") or "").strip()
        model_id = _pick_groq_model(client, override_model)

        db_path = get_db_path()
        ensure_schema_compat(db_path)
        request_info = ""

        import re
        request_match = re.search(r'(?:طلب|request|#)\s*(\d+)', user_message, re.IGNORECASE)
        if request_match:
            request_no = request_match.group(1)
            with sqlite3.connect(db_path) as con:
                con.row_factory = sqlite3.Row
                req = con.execute("SELECT * FROM requests WHERE request_no=?", (request_no,)).fetchone()
                if req:
                    request_info = f"""

معلومات الطلب #{request_no}:
- رقم الموظف: {req['employee_id']}
- اسم الموظف: {req['employee_name']}
- القسم: {req['department'] or 'غير محدد'}
- الفئة: {req['category']}
- نوع الطلب: {req['request_type']}
- الحالة: {req['status']}
- المسؤول: {req['assignee'] or 'غير محدد'}
- المدة المتوقعة: {req['duration_days']} أيام
- تاريخ التقديم: {req['created_at'][:10]}
- التفاصيل: {req['details']}
                    """

        system_prompt = "أنت مساعد لمنصة طلبات داخلية. أجب باختصار وبالعربية الافتراضية إلا إذا طُلب غير ذلك."
        if request_info:
            user_message += f"\n\n{request_info}"

        resp = client.chat.completions.create(
            messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_message}],
            model=model_id,
            max_tokens=512,
        )
        text = (resp.choices[0].message.content if resp and getattr(resp,"choices",None) else "") or ""
        if not text: text = f"(No text returned from {model_id})"
        return jsonify({"reply": text, "model": model_id})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

# ===================== Main =====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
