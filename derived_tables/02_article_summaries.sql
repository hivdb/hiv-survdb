INSERT INTO article_summaries
  SELECT
    ref_name,
    (
      SELECT COUNT(DISTINCT isolate_name)
      FROM isolates iso
      WHERE iso.ref_name = r.ref_name
    ) AS num_isolates
  FROM articles r;
