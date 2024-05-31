-- Find delivery orders longer than 2 days
SELECT
  "DocNum",
  "DocDate",
  "CardCode",
  "CardName",
  "Address"
FROM
  ODLN
WHERE
  "DocStatus" = 'O'
  AND "DocDate" < ADD_DAYS (CURRENT_DATE, -2)