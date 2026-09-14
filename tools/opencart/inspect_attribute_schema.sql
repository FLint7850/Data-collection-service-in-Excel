-- Attribut&co: preliminary schema report for an OpenCart / ocStore connector.
-- Run in phpMyAdmin on each shop's database server.
-- Searches all accessible non-system databases, regardless of the selected tab.
-- database_name identifies the database for each returned table.
-- If several databases appear, keep the rows for the shop being connected.
-- Export the complete relevant result as CSV, keeping the shops separate.
-- This SELECT reads table/column metadata only; it does not read shop records
-- or change the database. No table prefix needs to be entered.
-- If empty, check that this phpMyAdmin account can see the shop database.
-- The filter is a discovery aid, not a verified Attribut&co schema definition.

SELECT
    c.TABLE_SCHEMA AS database_name,
    c.TABLE_NAME AS table_name,
    c.ORDINAL_POSITION AS column_position,
    c.COLUMN_NAME AS column_name,
    c.COLUMN_TYPE AS column_type,
    c.IS_NULLABLE AS is_nullable,
    c.COLUMN_KEY AS column_key
FROM INFORMATION_SCHEMA.COLUMNS AS c
WHERE LOWER(c.TABLE_SCHEMA) NOT IN (
    'information_schema', 'mysql', 'performance_schema', 'sys', 'ndbinfo'
)
  AND (
      LOWER(c.TABLE_NAME) LIKE '%attribut%'
      OR LOWER(c.TABLE_NAME) LIKE '%category%'
      OR LOWER(c.TABLE_NAME) REGEXP '(^|_)(language|store|setting)$'
      OR c.TABLE_NAME IN (
          SELECT related.TABLE_NAME
          FROM INFORMATION_SCHEMA.COLUMNS AS related
          WHERE related.TABLE_SCHEMA = c.TABLE_SCHEMA
            AND LOWER(related.COLUMN_NAME) IN (
                'attribute_id', 'attribute_group_id', 'category_id'
            )
      )
  )
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION;
