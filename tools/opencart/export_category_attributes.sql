- Attribut&co: category-to-attribute links and raw duty fields.
-- Target: testfortrainvt only, Attribut&co 3.2.7; oc_ prefix from COLUMNS (1).csv.
-- Run on the same server/account that produced that report.
-- One result set; export the complete result to CSV.
-- SELECT only. Includes all languages and enabled/disabled linked categories.
-- LEFT JOIN preserves links even when a referenced record/translation is absent.
-- duty_raw is deliberately not split or interpreted as a list of allowed values.

SELECT
    'testfortrainvt' AS source_database,
    ca.category_id,
    c.parent_id AS parent_category_id,
    cd.name AS category_name,
    c.status AS category_enabled,
    c.sort_order AS category_sort_order,
    ad.language_id,
    l.code AS language_code,
    a.attribute_group_id,
    agd.name AS attribute_group_name,
    ag.sort_order AS group_sort_order,
    ca.attribute_id,
    ad.name AS attribute_name,
    a.sort_order AS attribute_sort_order,
    ad.duty AS duty_raw
FROM testfortrainvt.oc_category_attribute AS ca
LEFT JOIN testfortrainvt.oc_category AS c
    ON c.category_id = ca.category_id
LEFT JOIN testfortrainvt.oc_attribute AS a
    ON a.attribute_id = ca.attribute_id
LEFT JOIN testfortrainvt.oc_attribute_description AS ad
    ON ad.attribute_id = ca.attribute_id
LEFT JOIN testfortrainvt.oc_category_description AS cd
    ON cd.category_id = ca.category_id AND cd.language_id = ad.language_id
LEFT JOIN testfortrainvt.oc_attribute_group AS ag
    ON ag.attribute_group_id = a.attribute_group_id
LEFT JOIN testfortrainvt.oc_attribute_group_description AS agd
    ON agd.attribute_group_id = a.attribute_group_id
    AND agd.language_id = ad.language_id
LEFT JOIN testfortrainvt.oc_language AS l
    ON l.language_id = ad.language_id

ORDER BY source_database, category_id, language_id,
         group_sort_order, attribute_group_id, attribute_sort_order, attribute_id;
