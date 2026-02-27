import json
import os
import secrets
import string
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session

from crawler import crawl_job, search_all

app = Flask(__name__)
app.secret_key = "job-tracker-practice-key"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")

DETAIL_FIELDS = ("deadline", "experience", "education", "salary", "location", "requirements")


# ── User management ──────────────────────────────────────────────

def load_users():
    path = os.path.join(DATA_DIR, "users.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "users.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def generate_code():
    chars = string.ascii_uppercase + string.digits
    return "TRACK-" + "".join(secrets.choice(chars) for _ in range(4))


def generate_user_id():
    return secrets.token_hex(3)


# ── Job data (per-user) ─────────────────────────────────────────

def load_jobs(user_id):
    path = os.path.join(DATA_DIR, f"jobs_{user_id}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_jobs(jobs, user_id):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"jobs_{user_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)


def next_id(jobs):
    if not jobs:
        return 1
    return max(j["id"] for j in jobs) + 1


# ── Auth decorators ──────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ── Migration: existing data.json → first user ──────────────────

def migrate_old_data():
    old_path = os.path.join(os.path.dirname(__file__), "data.json")
    if not os.path.exists(old_path):
        return
    with open(old_path, "r", encoding="utf-8") as f:
        old_jobs = json.load(f)
    if not old_jobs:
        return
    users = load_users()
    if not users:
        return
    first_user_id = users[0]["id"]
    new_path = os.path.join(DATA_DIR, f"jobs_{first_user_id}.json")
    if os.path.exists(new_path):
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(old_jobs, f, ensure_ascii=False, indent=2)


# ── Auth routes ──────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        users = load_users()
        user = next((u for u in users if u["code"] == code), None)
        if user:
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("index"))
        flash("유효하지 않은 초대 코드입니다.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_panel"))
        flash("비밀번호가 올바르지 않습니다.")
    return render_template("admin.html", mode="login")


@app.route("/admin/panel")
@admin_required
def admin_panel():
    users = load_users()
    return render_template("admin.html", mode="panel", users=users)


@app.route("/admin/add-user", methods=["POST"])
@admin_required
def admin_add_user():
    name = request.form.get("name", "").strip()
    if not name:
        flash("사용자 이름을 입력해주세요.")
        return redirect(url_for("admin_panel"))

    users = load_users()

    # Ensure unique code
    existing_codes = {u["code"] for u in users}
    code = generate_code()
    while code in existing_codes:
        code = generate_code()

    user = {
        "id": generate_user_id(),
        "name": name,
        "code": code,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    users.append(user)
    save_users(users)

    # Run migration after first user is created
    migrate_old_data()

    flash(f"사용자 '{name}' 추가 완료! 초대 코드: {code}")
    return redirect(url_for("admin_panel"))


@app.route("/admin/delete-user/<user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    users = load_users()
    user = next((u for u in users if u["id"] == user_id), None)
    if not user:
        flash("사용자를 찾을 수 없습니다.")
        return redirect(url_for("admin_panel"))

    users = [u for u in users if u["id"] != user_id]
    save_users(users)

    # Delete user's job data file
    jobs_path = os.path.join(DATA_DIR, f"jobs_{user_id}.json")
    if os.path.exists(jobs_path):
        os.remove(jobs_path)

    flash(f"사용자 '{user['name']}' 삭제 완료.")
    return redirect(url_for("admin_panel"))


# ── Existing routes (with @login_required) ───────────────────────

@app.route("/")
@login_required
def index():
    user_id = session["user_id"]
    jobs = load_jobs(user_id)
    status_filter = request.args.get("status", "")
    if status_filter:
        jobs = [j for j in jobs if j["status"] == status_filter]
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return render_template("index.html", jobs=jobs, current_filter=status_filter)


@app.route("/crawl", methods=["GET", "POST"])
@login_required
def crawl():
    if request.method == "POST":
        url = request.form.get("url", "").strip()
        if not url:
            flash("URL을 입력해주세요.")
            return redirect(url_for("crawl"))
        try:
            result = crawl_job(url)
            session["crawled"] = result
            flash("크롤링 완료! 정보를 확인하고 저장해주세요.")
            return redirect(url_for("add"))
        except ValueError as e:
            flash(str(e))
            return redirect(url_for("crawl"))
    return render_template("crawl.html")


@app.route("/add", methods=["GET", "POST"])
@login_required
def add():
    user_id = session["user_id"]
    if request.method == "POST":
        jobs = load_jobs(user_id)
        job = {
            "id": next_id(jobs),
            "title": request.form["title"].strip(),
            "company": request.form["company"].strip(),
            "url": request.form.get("url", "").strip(),
            "description": request.form.get("description", "").strip(),
            "memo": request.form.get("memo", "").strip(),
            "status": "관심",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        for field in DETAIL_FIELDS:
            job[field] = request.form.get(field, "").strip()
        job["source"] = request.form.get("source", "").strip()
        jobs.append(job)
        save_jobs(jobs, user_id)
        flash("공고가 추가되었습니다!")
        return redirect(url_for("index"))
    crawled = session.pop("crawled", None)
    return render_template("add.html", crawled=crawled)


@app.route("/edit/<int:job_id>", methods=["GET", "POST"])
@login_required
def edit(job_id):
    user_id = session["user_id"]
    jobs = load_jobs(user_id)
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        flash("공고를 찾을 수 없습니다.")
        return redirect(url_for("index"))

    if request.method == "POST":
        job["title"] = request.form["title"].strip()
        job["company"] = request.form["company"].strip()
        job["url"] = request.form.get("url", "").strip()
        job["description"] = request.form.get("description", "").strip()
        job["memo"] = request.form.get("memo", "").strip()
        job["status"] = request.form["status"]
        for field in DETAIL_FIELDS:
            job[field] = request.form.get(field, "").strip()
        save_jobs(jobs, user_id)
        flash("공고가 수정되었습니다!")
        return redirect(url_for("index"))
    return render_template("edit.html", job=job)


@app.route("/delete/<int:job_id>", methods=["POST"])
@login_required
def delete(job_id):
    user_id = session["user_id"]
    jobs = load_jobs(user_id)
    jobs = [j for j in jobs if j["id"] != job_id]
    save_jobs(jobs, user_id)
    flash("공고가 삭제되었습니다.")
    return redirect(url_for("index"))


@app.route("/search", methods=["GET", "POST"])
@login_required
def search():
    if request.method == "POST":
        keyword = request.form.get("keyword", "").strip()
        if not keyword:
            flash("검색 키워드를 입력해주세요.")
            return redirect(url_for("search"))

        sites = []
        if request.form.get("site_saramin"):
            sites.append("사람인")
        if request.form.get("site_jobkorea"):
            sites.append("잡코리아")
        if request.form.get("site_wanted"):
            sites.append("원티드")
        if not sites:
            flash("검색할 사이트를 하나 이상 선택해주세요.")
            return redirect(url_for("search"))

        try:
            start_page = int(request.form.get("start_page", 1))
            if start_page < 1:
                start_page = 1
        except (ValueError, TypeError):
            start_page = 1

        crawl_all = request.form.get("crawl_all") == "on"
        if crawl_all:
            end_page = None
        else:
            try:
                end_page = int(request.form.get("end_page", 5))
                if end_page < start_page:
                    end_page = start_page
            except (ValueError, TypeError):
                end_page = 5

        data = search_all(keyword, start_page=start_page, end_page=end_page, sites=sites)
        results = data["results"]
        site_info = data["site_info"]

        if not results:
            flash("검색 결과가 없습니다.")
            return redirect(url_for("search"))

        user_id = session["user_id"]
        jobs = load_jobs(user_id)
        existing_urls = {j["url"] for j in jobs if j.get("url")}

        return render_template(
            "search_results.html",
            results=results,
            keyword=keyword,
            existing_urls=existing_urls,
            total=len(results),
            site_info=site_info,
        )

    return render_template("search.html")


@app.route("/search/save", methods=["POST"])
@login_required
def search_save():
    """선택된 검색 결과를 저장."""
    selected = request.form.getlist("selected")
    if not selected:
        flash("저장할 공고를 선택해주세요.")
        return redirect(url_for("search"))

    user_id = session["user_id"]
    jobs = load_jobs(user_id)
    existing_urls = {j["url"] for j in jobs if j.get("url")}
    new_count = 0

    for idx in selected:
        title = request.form.get(f"title_{idx}", "").strip()
        company = request.form.get(f"company_{idx}", "").strip()
        url = request.form.get(f"url_{idx}", "").strip()
        source = request.form.get(f"source_{idx}", "").strip()

        if not title or not url or url in existing_urls:
            continue

        job = {
            "id": next_id(jobs),
            "title": title,
            "company": company,
            "url": url,
            "description": "",
            "memo": "",
            "status": "관심",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": source,
        }
        for field in DETAIL_FIELDS:
            job[field] = request.form.get(f"{field}_{idx}", "").strip()

        jobs.append(job)
        existing_urls.add(url)
        new_count += 1

    if new_count > 0:
        save_jobs(jobs, user_id)
        flash(f"{new_count}개 공고가 저장되었습니다!")
    else:
        flash("새로 저장된 공고가 없습니다 (이미 저장된 공고일 수 있습니다).")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
