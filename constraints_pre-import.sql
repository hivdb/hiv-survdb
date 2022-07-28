CREATE FUNCTION checkRefAnnotUniqRefNameOrigContName(
  rname VARCHAR,
  cname continent_enum
) RETURNS BOOLEAN
AS $$
  SELECT NOT EXISTS (
    SELECT 1 FROM article_annotations
      WHERE (
        rname = ref_name AND (
          cname = original_continent_name OR
          (
            cname IS NULL AND
            original_continent_name IS NULL
          )
        )
      )
  )
$$ LANGUAGE SQL;

ALTER TABLE article_annotations
  ADD CONSTRAINT chk_ref_annot_ref_name_orig_cont_name CHECK (checkRefAnnotUniqRefNameOrigContName(ref_name, original_continent_name));


CREATE FUNCTION checkCPRURLUniqRefNameOrigContName(
  rname VARCHAR,
  cname continent_enum
) RETURNS BOOLEAN
AS $$
  SELECT NOT EXISTS (
    SELECT 1 FROM dataset_cpr_urls
      WHERE (
        rname = ref_name AND (
          cname = continent_name OR
          (
            cname IS NULL AND
            continent_name IS NULL
          )
        )
      )
  )
$$ LANGUAGE SQL;

ALTER TABLE dataset_cpr_urls
  ADD CONSTRAINT chk_cpr_url_ref_name_orig_cont_name CHECK (checkCPRURLUniqRefNameOrigContName(ref_name, continent_name));
