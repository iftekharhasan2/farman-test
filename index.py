import os
import secrets
import logging
import datetime
import signal
import sys
import re
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson.objectid import ObjectId
from gridfs import GridFS
import bcrypt
from dotenv import load_dotenv
from flask import Flask, jsonify, request, redirect, url_for, flash, render_template, make_response
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, set_access_cookies, unset_jwt_cookies, get_jwt
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'super-secret-key')
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_SECURE'] = False  # Set True if using HTTPS in production
app.config['JWT_COOKIE_CSRF_PROTECT'] = False  # Enable in production for CSRF protection

jwt = JWTManager(app)

mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
db = mongo["mydatabase"]
users_col = db["users"]
proj_col = db["projects"]
fs = GridFS(db)

ALLOWED_EXT = {"png", "jpg", "jpeg", "gif"}
PHONE_RE = re.compile(r'^\+?[0-9]{11,15}$')

def valid_phone(p):
    return PHONE_RE.fullmatch(p) is not None

def allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def days_since(d):
    if isinstance(d, str):
        d = datetime.datetime.fromisoformat(d).date()
    elif isinstance(d, datetime.datetime):
        d = d.date()
    return (datetime.date.today() - d).days + 1

def feed_level(weight, animal):
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

def Grass(weight, animal):
    if animal == "goat":
        return 2.5
    else:
        if weight < 150:
            return 5
        elif weight < 250:
            return 7.5
        if weight < 400:
            return 12.5
        elif weight < 500:
            return 17.5
        return 17.5

def build_schedule(day, weight, animal):
    if animal == "cow":
        return [
            {
                "phase": "সকাল",
                "tasks": [
                    {"description": "গোয়াল ঘর পরিষ্কার করুন, চারি পরিষ্কার করুন, গরুর পা হাঁটু পর্যন্ত ধুয়ে দিন", "time_range": "সকাল ৬ঃ০০ - ৭ঃ০০"},
                    {"description": f"সবুজ ঘাস খাওয়ান ({Grass(weight, animal)} কেজি)", "time_range": "সকাল ৭ঃ০০ - ৮ঃ০০"},
                    {"description": f"দানাদার খাদ্য {feed_level(weight, animal)} কেজি + চিটাগুড় মিশ্রিত পানি খাওয়ান (৫ গ্রাম / ৫ লিটার)", "time_range": "সকাল ৮ঃ০০ - ৯ঃ০০"},
                    {"description": "খড় খাওয়ান (চিটাগুড় মিশ্রিত পানি খড়ের উপর ছিটিয়ে দিন)", "time_range": "সকাল ৯ঃ০০ - ১০ঃ০০"},
                    {"description": "প্রয়োজন অনুযায়ী সবুজ ঘাস প্রদান করুন", "time_range": "সকাল ১০ঃ০০ - ১১ঃ০০"},
                ]
            },
            {
                "phase": "দুপুর",
                "tasks": [
                    {"description": "পানি দিয়ে চারি ধুয়ে দিন, গোয়াল ঘর পরিষ্কার করুন", "time_range": "সকাল ১১ঃ০০ - ১২ঃ০০"},
                    {"description": "গরুকে গোসল করিয়ে দিন (গরমে প্রতিদিন, শীতে ২ দিনে একবার)", "time_range": "দুপুর ১২ঃ০০ - ১ঃ০০"},
                    {"description": "চারিতে পরিষ্কার পানি দিন এবং গরুকে বিশ্রাম নিতে দিন", "time_range": "দুপুর ১ঃ০০ - ৩ঃ০০"},
                ]
            },
            {
                "phase": "বিকাল",
                "tasks": [
                    {"description": f"সবুজ ঘাস খাওয়ান ({Grass(weight, animal)} কেজি)", "time_range": "বিকাল ৩ঃ০০ - ৪ঃ০০"},
                    {"description": f"দানাদার খাদ্য খাওয়ান {feed_level(weight, animal)} কেজি", "time_range": "বিকাল ৪ঃ০০ - ৫ঃ০০"},
                    {"description": "খড় খাওয়ান (চিটাগুড় মিশ্রিত পানি খড়ের উপর ছিটিয়ে দিন)", "time_range": "বিকাল ৫ঃ০০ - ৬ঃ০০"},
                    {"description": "প্রয়োজন অনুযায়ী সবুজ ঘাস প্রদান করুন", "time_range": "বিকাল ৬ঃ০০ - সন্ধ্যা ৬ঃ৪৫"},
                ]
            },
            {
                "phase": "সন্ধ্যা",
                "tasks": [
                    {"description": "গোয়াল ঘর পরিষ্কার করুন, রাতের জন্য কয়েল জ্বালিয়ে দিন, চারি পরিষ্কার করে পানি দিন", "time_range": "সন্ধ্যা ৭ঃ০০ - ৮ঃ০০"}
                ]
            }
        ]

    elif animal == "goat":
        return [
            {
                "phase": "সকাল",
                "tasks": [
                    {"description": "ছাগলের ঘর পরিষ্কার করুন, চারি পরিষ্কার করুন, ছাগলের পা হাঁটু পর্যন্ত ধুয়ে দিন", "time_range": "সকাল ৬ঃ০০ - ৭ঃ০০"},
                    {"description": f"সবুজ ঘাস খাওয়ান {Grass(weight, animal)} কেজি", "time_range": "সকাল ৭ঃ০০ - ৮ঃ০০"},
                    {"description": f"দানাদার খাদ্য {feed_level(weight, animal)} গ্রাম(একটি বাটিতে পরিমাপ করে দিন) + চিটাগুড় মিশ্রিত পানি (৫ গ্রাম / ৫ লিটার)", "time_range": "সকাল ৮ঃ০০ - ৯ঃ০০"},
                    {"description": "খড় খাওয়ান (চিটাগুড় মিশ্রিত পানি খড়ের উপর ছিটিয়ে দিন)", "time_range": "সকাল ৯ঃ০০ - ১০ঃ০০"},
                    {"description": "প্রয়োজন অনুযায়ী সবুজ ঘাস প্রদান করুন", "time_range": "সকাল ১০ঃ০০ - ১১ঃ০০"},
                    {"description": "পানি দিয়ে চারি ধুয়ে দিন, ছাগলের ঘর পরিষ্কার করুন", "time_range": "সকাল ১১ঃ০০ - ১২ঃ০০"},
                ]
            },
            {
                "phase": "দুপুর",
                "tasks": [
                    {"description": "চারিতে পরিষ্কার পানি দিন এবং ছাগলকে বিশ্রাম নিতে দিন", "time_range": "দুপুর ১ঃ০০ - ৩ঃ০০"},
                    {"description": f"সবুজ ঘাস খাওয়ান ({Grass(weight, animal)} কেজি", "time_range": "দুপুর ৩ঃ০০ - ৪ঃ০০"},
                    {"description": f"দানাদার খাদ্য {feed_level(weight, animal)} গ্রাম", "time_range": "বিকাল ৪ঃ০০ - ৫ঃ০০"},
                    {"description": "খড় খাওয়ান (চিটাগুড় মিশ্রিত পানি খড়ের উপর ছিটিয়ে দিন)", "time_range": "বিকাল ৫ঃ০০ - ৬ঃ০০"},
                    {"description": "প্রয়োজন অনুযায়ী সবুজ ঘাস দিন", "time_range": "বিকাল ৬ঃ০০ - সন্ধ্যা ৬ঃ৪৫"},
                ]
            },
            {
                "phase": "বিকাল",
                "tasks": [
                    {"description": "ছাগলের ঘর পরিষ্কার করুন, রাতের জন্য কয়েল জ্বালিয়ে দিন, চারি পরিষ্কার করে পানি দিন", "time_range": "সন্ধ্যা ৭ঃ০০ - ৮ঃ০০"},
                ]
            }
        ]

    else:
        return [
            {
                "phase": "default",
                "tasks": [
                    {"description": f"{animal} এর জন্য সাধারণ কাজ", "time_range": "–"}
                ]
            }
        ]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()

        if not valid_phone(phone):
            flash("সঠিক ফোন নম্বর দিন!", "warning")
            return redirect(url_for("register"))

        if users_col.find_one({"phone": phone}):
            flash("এই ফোন নম্বর আগে ব্যবহার হেছে!", "warning")
            return redirect(url_for("register"))

        pw_hash = bcrypt.hashpw(request.form["password"].encode(), bcrypt.gensalt())
        user_id = users_col.insert_one({
            "name": name,
            "phone": phone,
            "password": pw_hash
        }).inserted_id

        access_token = create_access_token(identity=str(user_id))

        resp = make_response(redirect(url_for("projects")))
        set_access_cookies(resp, access_token)

        flash("অ্যাকাউন্ট তৈরি হেছে!", "success")
        return resp

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form["phone"].strip()
        pwd = request.form["password"]
        user = users_col.find_one({"phone": phone})

        if user and bcrypt.checkpw(pwd.encode(), user["password"]):
            user_id = str(user["_id"])
            role = user.get("role", "user")

            access_token = create_access_token(identity=user_id, additional_claims={"role": role})

            resp = make_response(redirect(url_for("projects")))
            set_access_cookies(resp, access_token)

            flash("স্বাগতম!", "success")
            return resp

        flash("ফোন নম্বর অথবা পাসওয়ার্ড ভুল!", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    resp = make_response(redirect(url_for("login")))
    unset_jwt_cookies(resp)
    flash("Logged out!", "info")
    return resp

@app.route("/projects")
@jwt_required()
def projects():
    user_id = get_jwt_identity()
    projs = list(proj_col.find({"owner": user_id}))
    days_map = {str(p["_id"]): days_since(p["purchase_date"]) for p in projs}
    return render_template("projects.html", projects=projs, days=days_map, str=str)

@app.route("/projects/new", methods=["GET", "POST"])
@jwt_required()
def new_project():
    if request.method == "POST":
        user_id = get_jwt_identity()
        doc = {
            "owner": user_id,
            "name": request.form["name"].strip(),
            "type": request.form["type"],
            "purchase_date": request.form["purchase_date"],
            "weight": float(request.form["weight"]),
            "feed_level": feed_level(float(request.form["weight"]), request.form["type"]),
            "target": float(request.form["weight"])+10 if request.form["type"] == "goat" else float(request.form["weight"])+120,
            "check_period": 30,
            "task_done": {},
            "task_photo": {},
        }
        proj_col.insert_one(doc)
        flash("Project created!", "success")
        return redirect(url_for("projects"))
    return render_template("new_project.html")

@app.route("/projects/<pid>/dashboard")
@jwt_required()
def dashboard(pid):
    user_id = get_jwt_identity()
    proj = proj_col.find_one({"_id": ObjectId(pid), "owner": user_id})
    if not proj:
        flash("Not found!", "danger")
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
    if "task_done" not in proj:
        proj["task_done"] = {}
    if "task_photo" not in proj:
        proj["task_photo"] = {}

    return render_template(
        "dashboard02.html",
        project=proj,
        schedule=schedule,
        days=days,
        show_weight_input=show_weight,
        days_left=days_left
    )

# @app.route("/projects/<pid>/delete", methods=["POST"])
# @jwt_required()
# def delete_project(pid):
#     user_id = get_jwt_identity()
#     proj = proj_col.find_one({"_id": ObjectId(pid), "owner": user_id})
#     if not proj:
#         flash("Project not found!", "danger")
#         return redirect(url_for("projects"))

#     for photo_ids in proj.get("task_photo", {}).values():
#         for photo_id in photo_ids:
#             try:
#                 fs.delete(ObjectId(photo_id))
#             except Exception:
#                 pass  # ignore if photo missing

#     proj_col.delete_one({"_id": ObjectId(pid)})
#     flash("Project and associated photos deleted!", "success")
#     return redirect(url_for("projects"))


@app.route("/projects/<pid>/weight", methods=["POST"])
@jwt_required()
def update_weight(pid):
    user_id = get_jwt_identity()
    weight = float(request.form["weight"])
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
@jwt_required()
def save_tasks(pid):
    user_id = get_jwt_identity()
    proj = proj_col.find_one({"_id": ObjectId(pid), "owner": user_id})
    if not proj:
        flash("Project not found!", "danger")
        return redirect(url_for("projects"))

    done_dict = {}
    schedule = build_schedule(days_since(proj["purchase_date"]), proj.get("weight", 0), proj["type"])
    for phase_dict in schedule:
        phase = phase_dict["phase"]
        for i in range(len(phase_dict["tasks"])):
            key = f"{phase}.{i}"
            done_dict[key] = (request.form.get(f"done_{key}") == "yes")

    proj_col.update_one({"_id": proj["_id"]}, {"$set": {"task_done": done_dict}})
    flash("Tasks updated!", "success")
    return redirect(url_for("dashboard", pid=pid))


@app.route("/projects/<pid>/photos/upload", methods=["POST"])
@jwt_required()
def upload_photos(pid):
    user_id = get_jwt_identity()
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

    saved = []
    for file in files:
        if file and allowed(file.filename):
            filename = f"{ObjectId()}_{secure_filename(file.filename)}"
            fs_id = fs.put(file, filename=filename, content_type=file.content_type)
            saved.append(str(fs_id))
        else:
            flash(f"Invalid file skipped: {file.filename}", "warning")

    phase_photos.extend(saved)
    proj_col.update_one({"_id": proj["_id"]}, {"$set": {f"task_photo.{phase}": phase_photos}})
    flash(f"Uploaded {len(saved)} photo(s) to phase '{phase}'!", "success")
    return redirect(url_for("dashboard", pid=pid))


@app.route("/photos/<photo_id>")
@jwt_required()
def serve_photo(photo_id):
    try:
        file = fs.get(ObjectId(photo_id))
        return app.response_class(file.read(), mimetype=file.content_type)
    except Exception:
        return "File not found", 404
@app.route("/projects/<pid>/delete", methods=["POST"])
@jwt_required()
def delete_project(pid):
    user_id = get_jwt_identity()
    proj = proj_col.find_one({"_id": ObjectId(pid), "owner": user_id})
    if not proj:
        flash("Project not found!", "danger")
        return redirect(url_for("projects"))

    for photo_ids in proj.get("task_photo", {}).values():
        for photo_id in photo_ids:
            try:
                fs.delete(ObjectId(photo_id))
            except Exception:
                pass

    proj_col.delete_one({"_id": ObjectId(pid)})
    flash("Project and associated photos deleted!", "success")
    return redirect(url_for("projects"))

# Similarly, implement other project related POST routes with JWT auth.




def shutdown(signum, frame):
    logging.info("Shutting down …")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    logging.info("Starting app on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
