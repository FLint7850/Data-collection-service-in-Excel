import unittest

from app import normalize_url


class NormalizeUrlTest(unittest.TestCase):
    def test_opencart_product_parameters_are_preserved(self):
        url = (
            "https://kaiser.ru/index.php?route=product/product&path=171_175_178"
            "&product_id=843"
        )

        self.assertEqual(normalize_url(url, url), url)

    def test_opencart_product_keeps_only_required_parameters(self):
        url = (
            "https://kaiser.ru/index.php?route=product/product&path=171_175_178"
            "&product_id=843&utm_source=test&sort=price"
        )

        self.assertEqual(
            normalize_url(url, url),
            (
                "https://kaiser.ru/index.php?route=product/product&path=171_175_178"
                "&product_id=843"
            ),
        )

    def test_pagination_is_still_preserved(self):
        url = "https://kaiser.ru/catalog/?page=2&utm_source=test"

        self.assertEqual(
            normalize_url(url, url),
            "https://kaiser.ru/catalog/?page=2",
        )

    def test_non_product_query_parameters_are_removed(self):
        url = "https://example.com/catalog/?sort=price&utm_source=test"

        self.assertEqual(
            normalize_url(url, url),
            "https://example.com/catalog/",
        )


if __name__ == "__main__":
    unittest.main()
