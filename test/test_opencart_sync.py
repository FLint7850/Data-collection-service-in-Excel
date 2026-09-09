import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from models import (
    Base, AttributeShopTemplateLink, AttributeTemplate,
    AttributeTemplateRevision, utc_now,
)
from services import opencart_sync as svc


def snapshot():
    return recount({
        "schema": "attributico-category-snapshot", "version": 1, "source_id": "a" * 32,
        "language": {"id": 1, "code": "ru-ru"}, "values_origin": "product_attribute",
        "values_scope": "database_attributes_linked_to_categories",
        "categories": [
            {"id": 10, "parent_id": 0, "name": "Техника", "enabled": True, "sort_order": 0, "attribute_ids": []},
            {"id": 199, "parent_id": 10, "name": "Кофемашины", "enabled": True, "sort_order": 1, "attribute_ids": [18]},
            {"id": 204, "parent_id": 10, "name": "Кофемашины", "enabled": True, "sort_order": 2, "attribute_ids": [18]},
        ],
        "attributes": [{"id": 18, "name": "Цвет", "group_id": 8, "group_name": "Внешний вид",
                        "group_sort_order": 1, "sort_order": 4, "duty_raw": "",
                        "values": ["Белый", "белый", " красный ", "чёрный/серый"]}],
    })


def recount(data):
    data["counts"] = {"categories": len(data["categories"]), "attributes": len(data["attributes"]),
                      "links": sum(len(c["attribute_ids"]) for c in data["categories"]),
                      "values": sum(len(a["values"]) for a in data["attributes"])}
    return data


class OpenCartSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "db.sqlite"))
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False, autoflush=False)
        self.shop = svc.configure_shop(self.db, {
            "name": "Магазин", "endpoint": "https://shop.example/index.php?route=extension/module/attribute_bridge",
            "api_key": "b" * 64,
        })
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def templates(self):
        return list(self.db.scalars(select(AttributeTemplate).order_by(AttributeTemplate.id)))

    def test_import_distinguishes_same_name_ids_and_preserves_slashes(self):
        report = svc.import_snapshot(self.db, self.shop, snapshot())
        self.db.commit()
        templates = self.templates()
        self.assertEqual(report["created"], 2)
        self.assertNotEqual(templates[0].category_id, templates[1].category_id)
        self.assertEqual({t.name for t in templates}, {"Кофемашины"})
        field = templates[0].fields[0]
        self.assertFalse(field.is_composite)
        self.assertIn("чёрный/серый", [v.value for v in field.allowed_values])
        self.assertEqual(len(field.allowed_values), 4)
        links = list(self.db.scalars(select(AttributeShopTemplateLink)))
        self.assertIn(" красный ", links[0].state["source"]["attributes"][0]["values"])


    def test_punctuation_variants_are_imported_separately(self):
        data = snapshot()
        data["attributes"][0]["values"] = ["A", "A+", "A++", "60/65", "60-65", "60 65"]
        svc.import_snapshot(self.db, self.shop, recount(data))
        self.db.commit()
        field = self.templates()[0].fields[0]
        self.assertEqual(field.value_type, "select")
        self.assertEqual([v.value for v in field.allowed_values], data["attributes"][0]["values"])
        self.assertEqual(len({v.normalized_value for v in field.allowed_values}), 6)
        result = svc.import_snapshot(self.db, self.shop, data)
        self.assertEqual(result["unchanged"], 2)

    def test_next_sync_repairs_old_import_without_recreating_manual_deletion(self):
        data = snapshot()
        data["attributes"][0]["values"] = ["A", "A+", "A++", "Удалено вручную"]
        svc.import_snapshot(self.db, self.shop, recount(data))
        self.db.commit()
        for template in self.templates():
            field = template.fields[0]
            for allowed in list(field.allowed_values):
                if allowed.value != "A":
                    self.db.delete(allowed)
            field.value_type = "select"
        for link in self.db.scalars(select(AttributeShopTemplateLink)):
            state = dict(link.state)
            state.pop("dictionary_version")
            link.state = state
        self.db.commit()
        self.db.expire_all()
        report = svc.import_snapshot(self.db, self.shop, data)
        self.db.commit()
        for template in self.templates():
            field = template.fields[0]
            self.assertEqual(field.value_type, "select")
            self.assertEqual([v.value for v in field.allowed_values], ["A", "A+", "A++"])
        self.assertEqual(report["values_added"], 4)
        self.assertEqual(svc.import_snapshot(self.db, self.shop, data)["unchanged"], 2)


    def test_second_import_is_idempotent_and_does_not_add_revisions(self):
        svc.import_snapshot(self.db, self.shop, snapshot())
        self.db.commit()
        ids = [(t.id, t.fields[0].id, t.version) for t in self.templates()]
        revisions = self.db.scalar(select(func.count()).select_from(AttributeTemplateRevision))
        report = svc.import_snapshot(self.db, self.shop, snapshot())
        self.db.commit()
        self.assertEqual(report["unchanged"], 2)
        self.assertEqual(report["values_added"], 0)
        self.assertEqual(ids, [(t.id, t.fields[0].id, t.version) for t in self.templates()])
        self.assertEqual(revisions, self.db.scalar(select(func.count()).select_from(AttributeTemplateRevision)))

    def test_source_rename_updates_existing_ids(self):
        data = snapshot()
        svc.import_snapshot(self.db, self.shop, data)
        self.db.commit()
        tid, fid = self.templates()[0].id, self.templates()[0].fields[0].id
        data["categories"][1]["name"] = "Кофейные машины"
        data["attributes"][0]["name"] = "Цвет корпуса"
        data["attributes"][0]["values"].append("синий")
        svc.import_snapshot(self.db, self.shop, recount(data))
        self.db.commit()
        template = self.templates()[0]
        self.assertEqual((template.id, template.fields[0].id), (tid, fid))
        self.assertEqual(template.name, "Кофейные машины")
        self.assertEqual(template.fields[0].name, "Цвет корпуса")
        self.assertIn("синий", [v.value for v in template.fields[0].allowed_values])

    def test_local_names_rules_and_removed_values_survive_source_update(self):
        data = snapshot()
        svc.import_snapshot(self.db, self.shop, data)
        self.db.commit()
        field = self.templates()[0].fields[0]
        field.name = "Наш цвет"
        field.synonyms = ["Окраска"]
        field.conversion_rules = [{"kind": "custom"}]
        value = next(v for v in field.allowed_values if v.value == "Белый")
        self.db.delete(value)
        self.db.commit()
        self.db.expire(field, ["allowed_values"])
        data["attributes"][0]["name"] = "Цвет корпуса"
        data["attributes"][0]["values"].append("синий")
        report = svc.import_snapshot(self.db, self.shop, recount(data))
        self.db.commit()
        self.assertEqual(field.name, "Наш цвет")
        self.assertEqual(field.synonyms, ["Окраска"])
        self.assertEqual(field.conversion_rules, [{"kind": "custom"}])
        self.assertNotIn("Белый", [v.value for v in field.allowed_values])
        self.assertGreater(report["local_changes_preserved"], 0)

    def test_source_removals_are_reported_without_deleting_local_data(self):
        data = snapshot()
        svc.import_snapshot(self.db, self.shop, data)
        self.db.commit()
        data["categories"][2]["attribute_ids"] = []
        data["attributes"][0]["values"] = ["Белый"]
        report = svc.import_snapshot(self.db, self.shop, recount(data))
        self.db.commit()
        self.assertEqual(report["categories_missing"], 1)
        self.assertEqual(len(self.templates()), 2)
        self.assertEqual(len(self.templates()[0].fields[0].allowed_values), 4)
        self.assertGreater(report["values_missing"], 0)

    def test_two_shops_and_languages_do_not_share_templates(self):
        svc.import_snapshot(self.db, self.shop, snapshot())
        other = svc.configure_shop(self.db, {"name": "Другой", "endpoint":
            "https://other.example/index.php?route=extension/module/attribute_bridge", "api_key": "c" * 64})
        self.db.flush()
        svc.import_snapshot(self.db, other, snapshot())
        self.shop.language_code = "en-gb"
        data = snapshot()
        data["language"] = {"id": 2, "code": "en-gb"}
        svc.import_snapshot(self.db, self.shop, data)
        self.db.commit()
        self.assertEqual(len(self.templates()), 6)

    def test_other_remote_installation_is_rejected(self):
        svc.import_snapshot(self.db, self.shop, snapshot())
        self.db.commit()
        data = snapshot()
        data["source_id"] = "d" * 32
        with self.assertRaisesRegex(ValueError, "другой установки"):
            svc.import_snapshot(self.db, self.shop, data)

    def test_failed_import_rolls_back_all_changes_and_releases_lease(self):
        data = snapshot()
        parent = 0
        for index in range(6):
            cid = 300 + index
            data["categories"].append({"id": cid, "parent_id": parent, "name": "x" * 220,
                "enabled": True, "sort_order": 0, "attribute_ids": [18] if index == 5 else []})
            parent = cid
        with patch.object(svc, "fetch_snapshot", return_value=recount(data)):
            with self.assertRaisesRegex(ValueError, "Путь"):
                svc.sync_shop(self.db, self.shop)
        self.assertEqual(self.templates(), [])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AttributeShopTemplateLink)), 0)
        self.db.refresh(self.shop)
        self.assertEqual(self.shop.sync_token, "")
        self.assertIn("Путь", self.shop.last_error)

    def test_concurrent_sync_is_rejected_but_stale_lease_can_be_recovered(self):
        self.shop.sync_token, self.shop.sync_started_at = "f" * 32, utc_now()
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "уже синхронизируется"):
            svc.sync_shop(self.db, self.shop)
        self.shop.sync_started_at = utc_now() - timedelta(minutes=11)
        self.db.commit()
        with patch.object(svc, "fetch_snapshot", return_value=snapshot()):
            result = svc.sync_shop(self.db, self.shop)
        self.assertEqual(result["created"], 2)
        self.assertEqual(self.shop.sync_token, "")

    def test_missing_links_counts_and_cycles_are_rejected(self):
        for change in ("counts", "missing", "cycle"):
            with self.subTest(change=change):
                data = snapshot()
                if change == "counts":
                    data["counts"]["values"] = 1
                elif change == "missing":
                    data["categories"][1]["attribute_ids"] = [999]
                else:
                    data["categories"][0]["parent_id"] = 199
                with self.assertRaises(ValueError):
                    svc.validate_snapshot(data, "ru-ru")

    def test_credentials_never_returned_and_blank_edit_preserves_key(self):
        original = self.shop.api_key
        saved = svc.configure_shop(self.db, {"name": self.shop.name, "endpoint": self.shop.endpoint, "api_key": ""}, self.shop)
        self.assertEqual(saved.api_key, original)
        self.assertNotIn(original, json.dumps(svc.serialize_shop(saved)))
        self.assertNotIn("api_key", svc.serialize_shop(saved))

    def test_private_addresses_and_non_https_endpoints_rejected(self):
        for url in ("http://shop.example/index.php?route=extension/module/attribute_bridge",
                    "https://user:pass@shop.example/index.php?route=extension/module/attribute_bridge",
                    "https://shop.example/index.php?route=other"):
            with self.assertRaises(ValueError):
                svc.endpoint_url(url)
        with patch.object(svc.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with patch.object(svc.urllib3, "HTTPSConnectionPool") as pool:
                with self.assertRaisesRegex(ValueError, "публичному"):
                    svc.fetch_snapshot(self.shop)
                pool.assert_not_called()

    def test_transport_pins_public_address_checks_tls_and_rejects_redirect(self):
        response = MagicMock(status=302)
        pool = MagicMock()
        pool.urlopen.return_value = response
        with patch.object(svc.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
            with patch.object(svc.urllib3, "HTTPSConnectionPool", return_value=pool) as factory:
                with self.assertRaisesRegex(ValueError, "302"):
                    svc.fetch_snapshot(self.shop)
        self.assertEqual(factory.call_args.args[0], "93.184.216.34")
        self.assertEqual(factory.call_args.kwargs["server_hostname"], "shop.example")
        self.assertEqual(factory.call_args.kwargs["cert_reqs"], "CERT_REQUIRED")
        self.assertFalse(pool.urlopen.call_args.kwargs["redirect"])
        self.assertNotIn(self.shop.api_key, pool.urlopen.call_args.args[1])

    def test_successful_transport_reads_snapshot(self):
        response = MagicMock(status=200)
        response.stream.return_value = [json.dumps(snapshot()).encode()]
        pool = MagicMock()
        pool.urlopen.return_value = response
        with patch.object(svc.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
            with patch.object(svc.urllib3, "HTTPSConnectionPool", return_value=pool):
                self.assertEqual(svc.fetch_snapshot(self.shop), snapshot())
        headers = pool.urlopen.call_args.kwargs["headers"]
        self.assertEqual(headers["User-Agent"], "AttributeBridge/1.0")
        self.assertEqual(headers["X-Attribute-Bridge-Key"], self.shop.api_key)
        response.close.assert_called_once()
        pool.close.assert_called_once()

    def test_routes_require_login_and_mask_key(self):
        from app import create_app
        with patch("services.application.SessionLocal", side_effect=lambda: Session(self.engine, expire_on_commit=False)):
            with patch("routes.opencart.ensure_storage"):
                app = create_app()
                app.config["TESTING"] = True
                client = app.test_client()
                self.assertEqual(client.get("/api/attribute-assistant/shops").status_code, 401)
                with client.session_transaction() as session:
                    session["user_id"] = 1
                response = client.get("/api/attribute-assistant/shops")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(self.shop.api_key, response.get_data(as_text=True))
                with patch.object(svc, "fetch_snapshot", return_value=snapshot()):
                    result = client.post("/api/attribute-assistant/shops/" + str(self.shop.id) + "/sync")
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json["report"]["created"], 2)


if __name__ == "__main__":
    unittest.main()
