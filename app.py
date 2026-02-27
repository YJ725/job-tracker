import json
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "job-tracker-practice-key"

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")


def load_jobs():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_jobs(jobs):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)


def next_id(jobs):
    if not jobs:
        return 1
    return max(j["id"] for j in jobs) + 1


@app.route("/")
def index():
    jobs = load_jobs()
    status_filter = request.args.get("status", "")
    if status_filter:
        jobs = [j for j in jobs if j["status"] == status_filter]
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return render_template("index.html", jobs=jobs, current_filter=status_filter)


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        jobs = load_jobs()
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
        jobs.append(job)
        save_jobs(jobs)
        flash("공고가 추가되었습니다!")
        return redirect(url_for("index"))
    return render_template("add.html")


@app.route("/edit/<int:job_id>", methods=["GET", "POST"])
def edit(job_id):
    jobs = load_jobs()
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
        save_jobs(jobs)
        flash("공고가 수정되었습니다!")
        return redirect(url_for("index"))
    return render_template("edit.html", job=job)


@app.route("/delete/<int:job_id>", methods=["POST"])
def delete(job_id):
    jobs = load_jobs()
    jobs = [j for j in jobs if j["id"] != job_id]
    save_jobs(jobs)
    flash("공고가 삭제되었습니다.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
