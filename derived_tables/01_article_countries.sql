INSERT INTO dataset_countries
  SELECT DISTINCT
    iso.dataset_name,
    iso.country_code
  FROM
    isolates iso
  ORDER BY
    iso.dataset_name,
    iso.country_code;
