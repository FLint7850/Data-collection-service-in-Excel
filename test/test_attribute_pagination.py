import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.orm import Session, raiseload

from models import Base, AttributeBatch, AttributeProduct, AttributeProductValue, AttributeTemplate
from services import attribute_assistant as svc
from services.attribute_listing import batch_summary, product_page


class AttributePaginationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.engine = create_engine("sqlite:///" + str(Path(cls.temp.name) / "products.db"))
        Base.metadata.create_all(cls.engine)
        cls.peak_objects = 0
        with Session(cls.engine, autoflush=False) as db, patch.object(svc, "ATTRIBUTE_ASSISTANT_DIR", Path(cls.temp.name)):
            template = svc.import_template_csv(
                db, "Цвет (Основные);Мощность (Основные);Комплектация (Основные)\nБелый;1000;Кабель\n".encode('utf-8'),
                name="Большой шаблон", category="Техника",
            )
            csv_text = io.StringIO()
            writer = csv.writer(csv_text, delimiter=';')
            writer.writerow(['_MODEL_', '_NAME_', '_BRAND_', '_ATTRIBUTES_'])
            for index in range(4000):
                writer.writerow([f'WM-{index:04}', f'Машина {index}', 'БРЕНД',
                                 'Основные|Цвет|Белый\nОсновные|Мощность|1000\nПрочее|Дополнение|Текст'])
            def objects(session, *_args):
                cls.peak_objects = max(cls.peak_objects, len(session.identity_map) + len(session.new))
            event.listen(db, 'after_flush', objects)
            with patch.object(svc, '_allowed_match', wraps=svc._allowed_match) as matches:
                batch = svc.create_batch_from_csv(db, template, csv_text.getvalue().encode('utf-8'), filename='4000.csv')
                cls.match_calls = matches.call_count
            cls.batch_id = batch.id
            cls.template_id = template.id
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.temp.cleanup()

    def setUp(self):
        self.db = Session(self.engine, autoflush=False)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_import_retains_all_rows_with_bounded_memory_and_matching(self):
        summary = batch_summary(self.db, self.batch_id)
        self.assertEqual(summary, {'products': 4000, 'ready': 0, 'needs_review': 4000,
                                   'filled': 8000, 'missing': 4000, 'conflicts': 0, 'suggestions': 0})
        self.assertEqual(self.match_calls, 2)
        self.assertLess(self.peak_objects, 1500)

    def test_pages_have_stable_order_and_no_attribute_objects_or_payloads(self):
        queries = []
        def query(_conn, _cursor, statement, *_args):
            queries.append(statement)
        event.listen(self.engine, 'before_cursor_execute', query)
        try:
            first = product_page(self.db, self.batch_id)
        finally:
            event.remove(self.engine, 'before_cursor_execute', query)
        second = product_page(self.db, self.batch_id, offset=80)
        self.assertEqual(len(first['items']), 80)
        self.assertEqual(first['total'], 4000)
        self.assertTrue(first['has_more'])
        self.assertEqual(second['items'][0]['model'], 'WM-0080')
        self.assertFalse({item['id'] for item in first['items']} & {item['id'] for item in second['items']})
        self.assertEqual(first['items'][0]['counts'], {'missing': 1, 'conflicts': 0, 'suggestions': 0, 'outside_template': 1})
        self.assertEqual(len(queries), 2)
        self.assertEqual(len(self.db.identity_map), 0)
        self.assertNotIn('values', first['items'][0])
        self.assertNotIn('source_details', ' '.join(queries))

    def test_unicode_search_and_filters_cover_other_pages(self):
        page = product_page(self.db, self.batch_id, query='мАшИнА 3999')
        self.assertEqual(page['matched'], 1)
        self.assertEqual(page['items'][0]['model'], 'WM-3999')
        self.assertEqual(product_page(self.db, self.batch_id, query='бренд')['matched'], 4000)
        self.assertEqual(product_page(self.db, self.batch_id, query='%')['matched'], 0)
        self.assertEqual(product_page(self.db, self.batch_id, status='outside_template')['matched'], 4000)
        self.assertEqual(product_page(self.db, self.batch_id, status='ready')['matched'], 0)
        last = product_page(self.db, self.batch_id, offset=5000)
        self.assertEqual(last['offset'], 3920)
        self.assertFalse(last['has_more'])
        self.assertLessEqual(len(product_page(self.db, self.batch_id, limit=5000)['items']), 200)

    def test_batch_metadata_and_summary_never_open_product_relationships(self):
        batch = self.db.scalar(select(AttributeBatch).where(AttributeBatch.id == self.batch_id)
                               .options(raiseload(AttributeBatch.products)))
        payload = svc.serialize_batch(batch)
        self.assertNotIn('products', payload)
        self.assertEqual(svc.refresh_batch_summary(batch)['products'], 4000)
        self.assertFalse(any(isinstance(item, AttributeProductValue) for item in self.db.identity_map.values()))

    def test_edit_updates_summary_and_counters_without_loading_siblings(self):
        product = self.db.scalar(select(AttributeProduct).where(AttributeProduct.batch_id == self.batch_id)
                                 .order_by(AttributeProduct.id).limit(1))
        batch = self.db.scalar(select(AttributeBatch).where(AttributeBatch.id == self.batch_id)
                               .options(raiseload(AttributeBatch.products)))
        value = next(item for item in product.values if not item.final_value)
        svc.update_product_value(value, action='accept', manual_value='Кабель')
        self.assertEqual(batch.summary['ready'], 1)
        self.assertEqual(batch.summary['missing'], 3999)
        page = product_page(self.db, self.batch_id, status='ready')
        self.assertEqual(page['matched'], 1)
        self.assertEqual(page['items'][0]['counts']['missing'], 0)
        detailed = svc.serialize_product(product, detailed=True)
        self.assertEqual(len(detailed['values']), 4)
        self.assertEqual(detailed['batch_id'], batch.id)
        self.assertEqual(sum(isinstance(item, AttributeProduct) for item in self.db.identity_map.values()), 1)

    def test_batch_api_is_metadata_only_and_product_list_is_paged(self):
        from flask import g
        from app import app
        from routes import attribute_assistant as routes

        with app.test_request_context(f'/api/attribute-assistant/batches/{self.batch_id}'), patch.object(routes, 'ensure_storage'):
            g.db = self.db
            self.assertNotIn('products', routes.api_attribute_batch(self.batch_id).get_json())
        with app.test_request_context(f'/api/attribute-assistant/batches/{self.batch_id}/products?offset=3920'), patch.object(routes, 'ensure_storage'):
            g.db = self.db
            response = routes.api_attribute_batch_products(self.batch_id).get_json()
            self.assertEqual(response['items'][0]['model'], 'WM-3920')
            self.assertEqual(response['total'], 4000)
            self.assertNotIn('values', response['items'][0])

    def test_export_streams_all_pages_without_loading_product_objects(self):
        batch = self.db.scalar(select(AttributeBatch).where(AttributeBatch.id == self.batch_id)
                               .options(raiseload(AttributeBatch.products)))
        with patch.object(svc, 'ATTRIBUTE_ASSISTANT_DIR', Path(self.temp.name)):
            path = svc.export_batch_csv(batch)
            with path.open(encoding='cp1251', newline='') as stream:
                rows = list(csv.DictReader(stream, delimiter=';'))
            self.assertEqual(len(rows), 4000)
            self.assertEqual(rows[0]['_MODEL_'], 'WM-0000')
            self.assertEqual(rows[-1]['_MODEL_'], 'WM-3999')
            self.assertIn('Прочее|Дополнение|Текст', rows[-1]['_ATTRIBUTES_'])
            self.assertFalse(any(isinstance(item, (AttributeProduct, AttributeProductValue))
                                 for item in self.db.identity_map.values()))
            with self.assertRaisesRegex(ValueError, 'Нет готовых'):
                svc.export_batch_csv(batch, ready_only=True)
            product = self.db.scalar(select(AttributeProduct).where(AttributeProduct.batch_id == batch.id)
                                     .order_by(AttributeProduct.id.desc()).limit(1))
            value = next(item for item in product.values if not item.final_value)
            svc.update_product_value(value, action='accept', manual_value='Кабель')
            with svc.export_batch_csv(batch, ready_only=True).open(encoding='cp1251', newline='') as stream:
                ready = list(csv.DictReader(stream, delimiter=';'))
            self.assertEqual([row['_MODEL_'] for row in ready], ['WM-3999'])

    def test_existing_database_gets_listing_indexes_idempotently(self):
        from database.session import migrate_attribute_assistant_tables

        engine = create_engine('sqlite://')
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(text('DROP INDEX ix_attribute_products_batch_sort'))
                connection.execute(text('DROP INDEX ix_attribute_product_values_product_id'))
                migrate_attribute_assistant_tables(connection)
                migrate_attribute_assistant_tables(connection)
            for table, name, columns in (
                ('attribute_products', 'ix_attribute_products_batch_sort', ['batch_id', 'sort_order', 'id']),
                ('attribute_product_values', 'ix_attribute_product_values_product_id', ['product_id']),
            ):
                index = next(item for item in inspect(engine).get_indexes(table) if item['name'] == name)
                self.assertEqual(index['column_names'], columns)
        finally:
            engine.dispose()

    def test_import_failure_rolls_back_completed_chunks(self):
        db = self.db
        template = db.get(AttributeTemplate, self.template_id)
        data = '_MODEL_;_ATTRIBUTES_\n' + ''.join(f'X-{i};"Основные|Цвет|Белый"\n' for i in range(120))
        real_make = svc._make_product_values
        calls = 0
        def fail_late(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 115:
                raise ValueError('Ошибка после первого блока')
            return real_make(*args, **kwargs)
        with patch.object(svc, 'ATTRIBUTE_ASSISTANT_DIR', Path(self.temp.name)), patch.object(svc, '_make_product_values', side_effect=fail_late):
            with self.assertRaises(ValueError):
                svc.create_batch_from_csv(db, template, data.encode('utf-8'), filename='failed.csv')
        db.rollback()
        self.assertEqual(db.scalar(select(func.count()).select_from(AttributeBatch)), 1)
