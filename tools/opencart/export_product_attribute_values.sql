-- Raw product attribute values for attributes linked to at least one category.
-- Target: testfortrainvt only, Attribut&co 3.2.7; oc_ prefix from COLUMNS (1).csv.
-- Run on the same server/account that produced that report.
-- One result set; export the complete result to CSV.
-- SELECT only. These are observed product values, not a verified Attribut&co
-- dictionary. Scope: all products for the attribute/language in each database,
-- not just products belonging to a particular category. Includes all stores.
-- product_count counts source product_attribute rows for each exact value.
-- HEX grouping preserves case/whitespace differences regardless of collation;
-- MIN returns the original text, not its hexadecimal representation.
-- Empty strings are omitted; punctuation and separators remain unchanged.

SELECT
    'testfortrainvt' AS source_database,
    'product_attribute' AS value_source,
    pa.attribute_id,
    pa.language_id,
    MIN(pa.text) AS value_raw,
    COUNT(*) AS product_count
FROM testfortrainvt.oc_product_attribute AS pa
WHERE CHAR_LENGTH(pa.text) > 0
  AND EXISTS (
      SELECT 1
      FROM testfortrainvt.oc_category_attribute AS ca
      WHERE ca.attribute_id = pa.attribute_id
  )
GROUP BY pa.attribute_id, pa.language_id, HEX(pa.text)

ORDER BY source_database, attribute_id, language_id, value_raw;
