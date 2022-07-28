INSERT INTO article_countries
  SELECT DISTINCT
    iso.ref_name,
    iso.country_code
  FROM
    isolates iso
  ORDER BY
    iso.ref_name,
    iso.country_code;
