INSERT INTO article_summaries
  SELECT
    ref_name,
    (
      SELECT COUNT(DISTINCT patient_id)
      FROM article_isolates refiso, isolates iso
      WHERE
        refiso.ref_name = r.ref_name AND
        refiso.isolate_id = iso.isolate_id
    ) AS num_patients,
    (
      SELECT COUNT(isolate_id)
      FROM article_isolates refiso
      WHERE
        refiso.ref_name = r.ref_name
    ) AS num_isolates
  FROM articles r;
