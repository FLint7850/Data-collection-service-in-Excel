"""Load service modules, resolve cross-service references and expose Flask app."""

from importlib import import_module
from types import ModuleType

from parser_app import runtime

MODULE_NAMES: tuple[str, ...] = (
    "parser_app.services.lifecycle",
    "parser_app.services.common",
    "parser_app.services.projects",
    "parser_app.services.logging_service",
    "parser_app.services.news_settings",
    "parser_app.services.normalization",
    "parser_app.services.extraction",
    "parser_app.services.fetching",
    "parser_app.services.crawler",
    "parser_app.services.file_import",
    "parser_app.services.feeds",
    "parser_app.services.news_scan",
    "parser_app.services.scheduling",
    "parser_app.routes.core",
    "parser_app.routes.news",
    "parser_app.routes.file_import",
    "parser_app.routes.projects",
    "parser_app.routes.legacy",
)


def public_namespace(module: ModuleType) -> dict[str, object]:
    return {key: value for key, value in vars(module).items() if not key.startswith("_")}


def load_modules() -> tuple[ModuleType, ...]:
    """Import modules in dependency order and publish each module immediately.

    Immediate publishing lets later modules inherit classes used at definition time
    (for example CollectOnlyCrawler inherits ProductSiteCrawler) without circular imports.
    """
    loaded: list[ModuleType] = []
    for module_name in MODULE_NAMES:
        module = import_module(module_name)
        loaded.append(module)
        vars(runtime).update(public_namespace(module))
    return tuple(loaded)


def bind_runtime_namespace(modules: tuple[ModuleType, ...]) -> None:
    """Give every module the final shared namespace before the first request."""
    namespace = public_namespace(runtime)
    for module in modules:
        namespace.update(public_namespace(module))

    vars(runtime).update(namespace)
    for module in modules:
        vars(module).update(namespace)


MODULES = load_modules()
bind_runtime_namespace(MODULES)

app = runtime.app
