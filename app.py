from flask import Flask, request, jsonify, render_template, send_from_directory
import sqlite3
import json
import os
import re
from datetime import datetime, date

app = Flask(__name__)
# On Render, use /data for persistent storage if available, else local directory
_data_dir = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_data_dir, "tiktok_organizer.db")

CATEGORIES = [
    "Unsorted",
    "Credit Repair",
    "Fashion",
    "Skincare",
    "Makeup",
    "Funny",
    "Conspiracy",
    "Recipe/Food",
    "Places To Go",
    "International Travel",
    "Financial Advice",
    "Money Saving Hacks",
    "Life Advice",
    "Bible/Jesus/God",
    "Relationship Advice",
    "Marketing & AI",
    "Business",
    "Gym/Fitness/Health",
    "Life Hacks",
    "Music",
    "Hair",
    "Home",
    "DIY Art",
    "Wishlist",
    "Perfumes",
    "Car Accessories/Car Hacks",
    "Cars",
    "Tutorials",
    "Birthday",
    "Rhinoplasty",
    "Science",
    "iPhone Hacks",
    "Books",
    "Politics",
    "Magic Tricks",
]

SUBFOLDERS = {
    "Marketing & AI": [
        "TikTok Marketing",
        "Pinterest Marketing",
        "Marketing Tools",
        "Marketing Techniques",
        "AI Tools",
    ]
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            caption TEXT DEFAULT '',
            creator TEXT DEFAULT '',
            date_saved TEXT DEFAULT '',
            category TEXT DEFAULT 'Unsorted',
            subfolder TEXT DEFAULT '',
            date_added TEXT DEFAULT '',
            UNIQUE(url)
        )
    """)
    conn.commit()
    conn.close()


def normalize_url(url):
    url = url.strip()
    # Strip query params for deduplication key but keep original
    return url


@app.route("/")
def index():
    return render_template("index.html", categories=CATEGORIES, subfolders=SUBFOLDERS)


@app.route("/api/categories")
def api_categories():
    return jsonify({"categories": CATEGORIES, "subfolders": SUBFOLDERS})


@app.route("/api/counts")
def api_counts():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT category, subfolder, COUNT(*) as cnt FROM videos GROUP BY category, subfolder")
    rows = c.fetchall()
    conn.close()
    counts = {}
    for row in rows:
        cat = row["category"]
        sub = row["subfolder"] or ""
        cnt = row["cnt"]
        if cat not in counts:
            counts[cat] = {"total": 0, "subfolders": {}}
        counts[cat]["total"] += cnt
        if sub:
            counts[cat]["subfolders"][sub] = counts[cat]["subfolders"].get(sub, 0) + cnt
    return jsonify(counts)


@app.route("/api/videos")
def api_videos():
    category = request.args.get("category", "Unsorted")
    subfolder = request.args.get("subfolder", "")
    search = request.args.get("search", "").strip()
    page = int(request.args.get("page", 1))
    per_page = 50
    offset = (page - 1) * per_page

    conn = get_db()
    c = conn.cursor()

    conditions = ["category = ?"]
    params = [category]

    if subfolder:
        conditions.append("subfolder = ?")
        params.append(subfolder)

    if search:
        conditions.append("(caption LIKE ? OR creator LIKE ? OR url LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])

    where = " AND ".join(conditions)

    c.execute(f"SELECT COUNT(*) as cnt FROM videos WHERE {where}", params)
    total = c.fetchone()["cnt"]

    c.execute(
        f"SELECT * FROM videos WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    )
    rows = c.fetchall()
    conn.close()

    videos = [dict(r) for r in rows]
    return jsonify({"videos": videos, "total": total, "page": page, "per_page": per_page})


@app.route("/api/search")
def api_search():
    search = request.args.get("q", "").strip()
    page = int(request.args.get("page", 1))
    per_page = 50
    offset = (page - 1) * per_page

    if not search:
        return jsonify({"videos": [], "total": 0, "page": 1, "per_page": per_page})

    conn = get_db()
    c = conn.cursor()
    like = f"%{search}%"
    c.execute(
        "SELECT COUNT(*) as cnt FROM videos WHERE caption LIKE ? OR creator LIKE ? OR url LIKE ?",
        [like, like, like],
    )
    total = c.fetchone()["cnt"]
    c.execute(
        "SELECT * FROM videos WHERE caption LIKE ? OR creator LIKE ? OR url LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
        [like, like, like, per_page, offset],
    )
    rows = c.fetchall()
    conn.close()
    return jsonify({"videos": [dict(r) for r in rows], "total": total, "page": page, "per_page": per_page})


@app.route("/api/videos/move", methods=["POST"])
def move_video():
    data = request.json
    video_id = data.get("id")
    category = data.get("category", "Unsorted")
    subfolder = data.get("subfolder", "")

    if category not in CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400
    if subfolder and category in SUBFOLDERS and subfolder not in SUBFOLDERS[category]:
        return jsonify({"error": "Invalid subfolder"}), 400
    if subfolder and category not in SUBFOLDERS:
        subfolder = ""

    conn = get_db()
    conn.execute(
        "UPDATE videos SET category=?, subfolder=? WHERE id=?",
        [category, subfolder, video_id],
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/videos/move_bulk", methods=["POST"])
def move_bulk():
    data = request.json
    ids = data.get("ids", [])
    category = data.get("category", "Unsorted")
    subfolder = data.get("subfolder", "")

    if category not in CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400

    conn = get_db()
    for vid_id in ids:
        conn.execute(
            "UPDATE videos SET category=?, subfolder=? WHERE id=?",
            [category, subfolder, vid_id],
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "moved": len(ids)})


@app.route("/api/videos/add", methods=["POST"])
def add_video():
    data = request.json
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400

    caption = (data.get("caption") or "").strip()
    creator = (data.get("creator") or "").strip()
    date_saved = (data.get("date_saved") or "").strip()
    category = data.get("category", "Unsorted")
    subfolder = data.get("subfolder", "")
    date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO videos (url, caption, creator, date_saved, category, subfolder, date_added) VALUES (?,?,?,?,?,?,?)",
            [url, caption, creator, date_saved, category, subfolder, date_added],
        )
        conn.commit()
        c = conn.cursor()
        c.execute("SELECT * FROM videos WHERE url=?", [url])
        row = dict(c.fetchone())
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Video already exists"}), 409
    conn.close()
    return jsonify({"ok": True, "video": row})


@app.route("/api/videos/<int:video_id>", methods=["DELETE"])
def delete_video(video_id):
    conn = get_db()
    conn.execute("DELETE FROM videos WHERE id=?", [video_id])
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/import", methods=["POST"])
def import_json():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    try:
        raw = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Invalid JSON: {e}"}), 400

    videos = []

    # TikTok export formats vary — try multiple known structures
    # Format 1: Activity.Favorite Videos.FavoriteVideoList
    try:
        fav_list = raw["Activity"]["Favorite Videos"]["FavoriteVideoList"]
        for item in fav_list:
            url = item.get("Link", "") or item.get("link", "") or item.get("VideoLink", "")
            date_saved = item.get("Date", "") or item.get("date", "")
            videos.append({"url": url, "date_saved": date_saved, "caption": "", "creator": ""})
    except (KeyError, TypeError):
        pass

    # Format 2: flat list under "Favorite Video List"
    if not videos:
        try:
            fav_list = raw["Favorite Video List"]
            for item in fav_list:
                url = item.get("Link", "") or item.get("VideoLink", "") or item.get("url", "")
                date_saved = item.get("Date", "") or item.get("date", "")
                videos.append({"url": url, "date_saved": date_saved, "caption": "", "creator": ""})
        except (KeyError, TypeError):
            pass

    # Format 3: Activity > Browsing History or Video Browsing History
    if not videos:
        try:
            hist = raw["Activity"]["Video Browsing History"]["VideoList"]
            for item in hist:
                url = item.get("VideoLink", "") or item.get("Link", "")
                date_saved = item.get("Date", "")
                videos.append({"url": url, "date_saved": date_saved, "caption": "", "creator": ""})
        except (KeyError, TypeError):
            pass

    # Format 4: look for any list containing objects with Link/VideoLink
    if not videos:
        def find_video_lists(obj, depth=0):
            found = []
            if depth > 6:
                return found
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        url = item.get("Link") or item.get("VideoLink") or item.get("link") or item.get("url", "")
                        if url and "tiktok" in url.lower():
                            found.append({
                                "url": url,
                                "date_saved": item.get("Date") or item.get("date", ""),
                                "caption": item.get("Caption") or item.get("caption", ""),
                                "creator": item.get("Creator") or item.get("author", ""),
                            })
            elif isinstance(obj, dict):
                for v in obj.values():
                    found.extend(find_video_lists(v, depth + 1))
            return found

        videos = find_video_lists(raw)

    if not videos:
        return jsonify({"error": "Could not find saved videos in this JSON. Try the format from TikTok's data export."}), 400

    date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    skipped = 0
    conn = get_db()
    for v in videos:
        url = (v.get("url") or "").strip()
        if not url:
            continue
        try:
            conn.execute(
                "INSERT INTO videos (url, caption, creator, date_saved, category, subfolder, date_added) VALUES (?,?,?,?,?,?,?)",
                [url, v.get("caption", ""), v.get("creator", ""), v.get("date_saved", ""), "Unsorted", "", date_added],
            )
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "imported": inserted, "skipped": skipped, "total_found": len(videos)})


@app.route("/ping")
def ping():
    return "pong", 200


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    print(f"TikTok Organizer running at http://localhost:{port}")
    app.run(debug=debug, host="0.0.0.0", port=port)
