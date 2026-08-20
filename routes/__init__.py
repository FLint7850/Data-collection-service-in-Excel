"""Flask blueprints."""

from routes.attribute_assistant import bp as routes_attribute_assistant_bp
from routes.auth import bp as routes_auth_bp
from routes.feeds import bp as routes_feeds_bp
from routes.file_import import bp as routes_file_import_bp
from routes.logs import bp as routes_logs_bp
from routes.news import bp as routes_news_bp
from routes.price_converter import bp as routes_price_converter_bp
from routes.progress import bp as routes_progress_bp
from routes.projects import bp as routes_projects_bp
from routes.settings import bp as routes_settings_bp

BLUEPRINTS = [
    routes_attribute_assistant_bp,
    routes_auth_bp,
    routes_feeds_bp,
    routes_file_import_bp,
    routes_logs_bp,
    routes_news_bp,
    routes_price_converter_bp,
    routes_progress_bp,
    routes_projects_bp,
    routes_settings_bp,
]
