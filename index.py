import os
import secrets
import logging
import datetime
import signal
import sys
import re
from werkzeug.utils import secure_filename
from flask import Flask, request, session, redirect, url_for, render_template, flash
from pymongo import MongoClient
from bson.objectid import ObjectId
from gridfs import GridFS
import bcrypt
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# MongoDB setup
mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
db = mongo["mydatabase"]
users_col = db["users"]
proj_col = db["projects"]
fs = GridFS(db)

# File upload config
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB max upload
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

PHONE_RE = re.compile(r'^\+?[0-9]{11,15}$')

# Utilities

def valid_phone(phone: str) -> bool:
    return PHONE_RE.fullmatch(phone) is not None

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def days_since(date_val) -> int:
    if isinstance(date_val, str):
        date_val = datetime.datetime.fromisoformat(date_val).date()
    elif isinstance(date_val, datetime.datetime):
        date_val = date_val.date()
    return (datetime.date.today() - date_val).days + 1

def feed_level(weight: float, animal: str) -> int:
    if animal == "goat":
        if weight < 10:
            return 100
        elif weight <= 15:
            return 150
        elif weight < 20:
            return 200
        return 200
    else:
        if weight < 150:
            return 1
        elif weight < 280:
            return 2
        return 3

def grass_amount(weight: float, animal: str) -> float:
    if animal == "goat":
        return 2.5
    else:
        if weight < 150:
            return 5
        elif weight < 250:
            return 7.5
        elif weight < 400:
            return 12.5
        elif weight < 500:
            return 17.5
        return 17.5

def build_schedule(day: int, weight: float, animal: str):
    # (same schedule as your original function, omitted here for brevity)
    # Copy your existing build_schedule logic exactly here
    # It returns a list of dicts with phases and tasks
    # ... (copy your build_schedule code here exactly) ...
    pass


# Auth check decorator for admin pages
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            flash("Admin login required", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# Routes

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        pwd = request.form.get("password", "")
        user = users_col.find_one({"phone": phone})
        if user and bcrypt.checkpw(pwd.encode(), user["password"]):
            session["user_id"] = str(user["_id"])
            if user.get("role") == "admin":
                session["admin"] = True
                return redirect(url_for("admin_dashboard"))
            flash("স্বাগতম!", "success")
            return redirect(url_for("projects"))
        flash("ফোন নম্বর অথবা পাসওয়ার্ড ভুল!", "danger")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not valid_phone(phone):
            flash("সঠিক ফোন নম্বর দিন!", "warning")
            return redirect(url_for("register"))
        if users_col.find_one({"phone": phone}):
            flash("এই ফোন নম্বর আগে ব্যবহার হেছে!", "warning")
            return redirect(url_for("register"))
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        user_id = users_col.insert_one({"name": name, "phone": phone, "password": pw_hash}).inserted_id
        session["user_id"] = str(user_id)
        flash("অ্যাকাউন্ট তৈরি হেছে!", "success")
        return redirect(url_for("projects"))
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out!", "info")
    return redirect(url_for("login"))

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Admin logged out.", "info")
    return redirect(url_for("login"))

@app.route("/admin/dashboard", methods=["GET"])
@admin_required
def admin_dashboard():
    projects = list(proj_col.find())
    for p in projects:
        p["days"] = days_since(p["purchase_date"])
        p["schedule"] = build_schedule(p["days"], p["weight"], p["type"])
    return render_template("admin02.html", zip=zip, projects=projects)

@app.route("/admin/users")
@admin_required
def admin_users():
    users = list(users_col.find({}, {"password": 0}))
    return render_template("admin_users.html", users=users)

@app.route("/admin/user/<uid>")
@admin_required
def admin_user_detail(uid):
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        flash("User not found", "danger")
        return redirect(url_for("admin_users"))
    projects = list(proj_col.find({"owner": uid}))
    for p in projects:
        p["days"] = days_since(p["purchase_date"])
        p["schedule"] = build_schedule(p["days"], p["weight"], p["type"])
    return render_template("admin_user_detail.html", user=user, projects=projects)

@app.route("/projects")
def projects():
    user_id = session.get("user_id")
    if not user_id:
        flash("Please login first.", "warning")
        return redirect(url_for("login"))
    projs = list(proj_col.find({"owner": user_id}))
    days_map = {str(p["_id"]): days_since(p["purchase_date"]) for p in projs}
    return render_template("projects.html", projects=projs, days=days_map, str=str)

@app.route("/projects/new", methods=["GET", "POST"])
def new_project():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        animal_type = request.form.get("type")
        purchase_date = request.form.get("purchase_date")
        weight = float(request.form.get("weight", 0))
        doc = {
            "owner": session["user_id"],
            "name": name,
            "type": animal_type,
            "purchase_date": purchase_date,
            "weight": weight,
            "feed_level": feed_level(weight, animal_type),
            "target": 24 if animal_type == "goat" else 350,
            "check_period": 30 if animal_type == "cow" else 1,
            "task_done": {},
            "task_photo": {},
        }
        proj_col.insert_one(doc)
        flash("Project created!", "success")
        return redirect(url_for("projects"))
    return render_template("new_project.html")

@app.route("/projects/<pid>/dashboard")
def dashboard(pid):
    user_id = session.get("user_id")
    proj = proj_col.find_one({"_id": ObjectId(pid), "owner": user_id})
    if not proj:
        flash("Project not found!", "danger")
        return redirect(url_for("projects"))

    days = days_since(proj["purchase_date"])
    period = proj["check_period"]
    show_weight = (days % period == 0 and days != 0) or proj["type"] == "goat"
    days_left = (period - (days % period)) % period

    if days % period == 0 and days != 0 and proj.get("last_check") != days:
        new_level = feed_level(proj["weight"] + (30 if proj["type"] == "cow" else 0), proj["type"])
        proj_col.update_one({"_id": proj["_id"]}, {"$set": {"feed_level": new_level, "last_check": days}})
        proj["feed_level"] = new_level
        proj["last_check"] = days

    schedule = build_schedule(days, proj["weight"], proj["type"])

    # Ensure keys exist
    proj.setdefault("task_done", {})
    proj.setdefault("task_photo", {})

    return render_template(
        "dashboard02.html",
        project=proj,
        schedule=schedule,
        days=days,
        show_weight_input=show_weight,
        days_left=days_left
    )

@app.route("/projects/<pid>/delete", methods=["POST"])
def delete_project(pid):
    user_id = session.get("user_id")
    if not user_id:
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    proj = proj_col.find_one({"_id": ObjectId(pid), "owner": user_id})
    if not proj:
        flash("Project not found!", "danger")
        return redirect(url_for("projects"))

    for photo_list in proj.get("task_photo", {}).values():
        for photo_id in photo_list:
            try:
                fs.delete(ObjectId(photo_id))
            except Exception:
                pass

    proj_col.delete_one({"_id": ObjectId(pid)})
    flash("Project and associated photos deleted!", "success")
    return redirect(url_for("projects"))

@app.route("/projects/<pid>/weight", methods=["POST"])
def update_weight(pid):
    user_id = session.get("user_id")
    if not user_id:
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    weight = float(request.form.get("weight", 0))
    proj = proj_col.find_one({"_id": ObjectId(pid), "owner": user_id})
    if not proj:
        flash("Project not found!", "danger")
        return redirect(url_for("projects"))

    proj_col.update_one({"_id": ObjectId(pid)}, {"$set": {"weight": weight}})
    new_level = feed_level(weight, proj["type"])
    proj_col.update_one({"_id": ObjectId(pid)}, {"$set": {"feed_level": new_level}})

    flash("Weight & feed level updated!", "success")
    return redirect(url_for("dashboard", pid=pid))

@app.route("/projects/<pid>/tasks/save", methods=["POST"])
def save_tasks(pid):
    user_id = session.get("user_id")
    if not user_id:
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    proj = proj_col.find_one({"_id": ObjectId(pid), "owner": user_id})
    if not proj:
        flash("Project not found!", "danger")
        return redirect(url_for("projects"))

    done_dict = {}
    schedule = build_schedule(days_since(proj["purchase_date"]), proj.get("weight", 0), proj["type"])

    for phase_info in schedule:
        phase = phase_info["phase"]
        for idx, _ in enumerate(phase_info["tasks"]):
            key = f"{phase}.{idx}"
            done_dict[key] = request.form.get(f"done_{key}") == "yes"

    proj_col.update_one({"_id": proj["_id"]}, {"$set": {"task_done": done_dict}})
    flash("Tasks updated!", "success")
    return redirect(url_for("dashboard", pid=pid))

@app.route("/projects/<pid>/photos/upload", methods=["POST"])
def upload_photos(pid):
    user_id = session.get("user_id")
    if not user_id:
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    proj = proj_col.find_one({"_id": ObjectId(pid), "owner": user_id})
    if not proj:
        flash("Project not found!", "danger")
        return redirect(url_for("projects"))

    phase = request.form.get("phase")
    if not phase:
        flash("Phase not specified.", "warning")
        return redirect(url_for("dashboard", pid=pid))

    files = request.files.getlist("photos")
    if not files or all(f.filename == '' for f in files):
        flash("No photos selected.", "warning")
        return redirect(url_for("dashboard", pid=pid))

    phase_photos = proj.get("task_photo", {}).get(phase, [])
    if isinstance(phase_photos, str):
        phase_photos = [phase_photos]

    saved_files = []
    for file in files:
        if file and allowed_file(file.filename):
            filename = f"{ObjectId()}_{secure_filename(file.filename)}"
            fs_id = fs.put(file, filename=filename, content_type=file.content_type)
            saved_files.append(str(fs_id))
        else:
            flash(f"Invalid file skipped: {file.filename}", "warning")

    phase_photos.extend(saved_files)
    proj_col.update_one({"_id": proj["_id"]}, {"$set": {f"task_photo.{phase}": phase_photos}})
    flash(f"Uploaded {len(saved_files)} photo(s) to phase '{phase}'!", "success")
    return redirect(url_for("dashboard", pid=pid))

@app.route("/photos/<photo_id>")
def serve_photo(photo_id):
    try:
        file = fs.get(ObjectId(photo_id))
        return app.response_class(file.read(), mimetype=file.content_type)
    except Exception:
        return "File not found", 404

# Graceful shutdown

def shutdown(signum, frame):
    logging.info("Shutting down …")
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)

if __name__ == "__main__":
    logging.info("Starting app on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
