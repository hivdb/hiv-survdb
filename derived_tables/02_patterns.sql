SELECT
  iso.dataset_name,
  iso.isolate_name,
  iso.gene,
  iso.gene || ':' ||
  STRING_AGG(
    SPLIT_PART(isomut.mutation, ':', 2),
    '+'
    ORDER BY isomut.position, isomut.amino_acid
  ) AS pattern,
  EXTRACT(YEAR FROM isolate_date) AS year,
  subtype,
  source,
  seq_method,
  country_code,
  cpr_excluded
INTO TABLE isolate_patterns
FROM isolates iso
LEFT JOIN isolate_mutations isomut ON
  iso.dataset_name = isomut.dataset_name AND
  iso.isolate_name = isomut.isolate_name AND
  iso.gene = isomut.gene AND
  EXISTS (
    SELECT 1 FROM surv_mutations sdrm WHERE
      isomut.mutation = sdrm.mutation
  ) AND
  NOT EXISTS (
    SELECT 1 FROM isolate_excluded_surv_mutations exsdrm
    WHERE
      isomut.dataset_name = exsdrm.dataset_name AND
      isomut.isolate_name = exsdrm.isolate_name AND
      isomut.mutation = exsdrm.mutation
  )
GROUP BY
  iso.dataset_name, iso.isolate_name, iso.gene, year,
  subtype, source, seq_method, country_code, cpr_excluded;

UPDATE isolate_patterns
  SET pattern = gene || ':'
  WHERE pattern IS NULL;

INSERT INTO patterns (
  gene,
  pattern,
  year,
  subtype,
  source,
  seq_method,
  country_code,
  cpr_excluded
) (
  SELECT
    DISTINCT
    gene,
    pattern,
    year,
    subtype,
    source,
    seq_method,
    country_code,
    cpr_excluded
  FROM isolate_patterns
);

INSERT INTO dataset_patterns (
  SELECT
    dataset_name,
    pattern_id,
    COUNT(*) AS num_isolates
  FROM isolate_patterns ip, patterns p
  WHERE
    ip.gene = p.gene AND
    ip.pattern = p.pattern AND
    ip.year = p.year AND
    ip.subtype = p.subtype AND
    ip.source = p.source AND
    ip.seq_method = p.seq_method AND
    ip.country_code = p.country_code AND
    ip.cpr_excluded = p.cpr_excluded
  GROUP BY dataset_name, pattern_id
);

DROP TABLE isolate_patterns;
