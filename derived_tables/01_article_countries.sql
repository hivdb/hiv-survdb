INSERT INTO article_countries
  SELECT DISTINCT
    refiso.ref_name,
    iso.country_code
  FROM
    article_isolates refiso,
    isolates iso
  WHERE
    refiso.isolate_id = iso.isolate_id
  ORDER BY
    refiso.ref_name,
    iso.country_code;
