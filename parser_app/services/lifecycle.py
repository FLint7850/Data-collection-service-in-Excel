"""Flask lifecycle, authentication checks and request database sessions."""



from parser_app.runtime import *  # noqa: F401,F403



@app.errorhandler(Exception)
def log_unhandled_exception(error: Exception):
    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / "flask-error.log").open("a", encoding="utf-8") as error_file:
        error_file.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {request.method} {request.path}\n")
        error_file.write("".join(traceback.format_exception(type(error), error, error.__traceback__)))
    raise error

@app.before_request
def open_request_db_session() -> None:
    g.db = SessionLocal()

def ensure_default_user() -> None:
    init_db()
    with session_scope() as db_session:
        existing_user = db_session.scalar(select(User.id).limit(1))
        if existing_user:
            return
        username = env_str("AUTH_DEFAULT_USERNAME", "admin")
        password = env_str("AUTH_DEFAULT_PASSWORD", "admin")
        db_session.add(
            User(
                username=username,
                password_hash=generate_password_hash(password),
                is_active=True,
            )
        )

def is_public_endpoint() -> bool:
    endpoint = request.endpoint or ""
    return endpoint in {"healthcheck", "login", "static"} or request.path.startswith("/static/")

@app.before_request
def require_login() -> Optional[Response]:
    if is_public_endpoint():
        return None
    if session.get("user_id"):
        return None
    return redirect(url_for("login"))

@app.teardown_request
def close_request_db_session(error: Optional[BaseException] = None) -> None:
    db = g.pop("db", None)
    if db is None:
        return
    if error is None:
        db.commit()
    else:
        db.rollback()
    db.close()
