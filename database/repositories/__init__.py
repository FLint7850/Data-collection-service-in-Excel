"""Targeted persistence operations for application entities."""

from database.repositories.news import delete_brand, delete_donor, update_brand, update_donor
from database.repositories.projects import delete_project, update_project

__all__ = [
    "delete_brand",
    "delete_donor",
    "delete_project",
    "update_brand",
    "update_donor",
    "update_project",
]
