"""Authentication, index and common API endpoints."""



from parser_app.runtime import *  # noqa: F401,F403



@app.route("/login", methods=["GET", "POST"])
def login() -> str | Response:
    ensure_default_user()
    if session.get("user_id"):
        return redirect(url_for("index"))
    error = ""
    if request.method == "POST":
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        user = g.db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = int(user.id)
            session["username"] = user.username
            return redirect(url_for("index"))
        error = "Неверный логин или пароль"
    return render_template("login.html", error=error)

@app.get("/api/health")
def healthcheck():
    ensure_storage()
    return jsonify({"ok": True})

@app.post("/logout")
def logout() -> Response:
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def index() -> str:
    ensure_storage()
    static_files = [BASE_DIR / "static" / "css" / "styles.css", *sorted((BASE_DIR / "static" / "js").rglob("*.js"))]
    static_version = max((int(path.stat().st_mtime) for path in static_files if path.exists()), default=0)
    return render_template("index.html", default_start_url=DEFAULT_START_URL, static_version=static_version)

@app.get("/api/state")
def api_state():
    return jsonify(snapshot_state())

@app.get("/api/connection-methods")
def api_connection_methods():
    ensure_storage()
    return jsonify({"connection_methods": public_connection_methods()})

@app.get("/api/news")
def api_news():
    ensure_storage()
    return jsonify(public_news_settings())
