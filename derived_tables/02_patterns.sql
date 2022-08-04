SELECT
  dataset_name,
  isolate_name,
  (SELECT
    STRING_AGG(
      mutation,
      ','
      ORDER BY gene, position, amino_acid
    ) AS pattern
    FROM surv_mutations sdrm
    WHERE
      EXISTS (
        SELECT 1 FROM isolate_mutations isomut
        WHERE
          iso.dataset_name = isomut.dataset_name AND
          iso.isolate_name = isomut.isolate_name AND
          isomut.mutation = sdrm.mutation
      ) AND
      NOT EXISTS (
        SELECT 1 FROM isolate_excluded_surv_mutations exsdrm
        WHERE
          iso.dataset_name = exsdrm.dataset_name AND
          iso.isolate_name = exsdrm.isolate_name AND
          sdrm.mutation = exsdrm.mutation
      )
  ) AS pattern,
  genes,
  year,
  -- subtype,
  country_code
INTO TABLE isolate_patterns
FROM (
  SELECT
    dataset_name,
    isolate_name,
    STRING_AGG(gene::text, ',' ORDER BY gene) AS genes,
    EXTRACT(YEAR FROM isolate_date) AS year,
    -- STRING_AGG(DISTINCT subtype, ',' ORDER BY subtype) AS subtype,
    country_code
  FROM isolates
  WHERE cpr_excluded IS FALSE
  GROUP BY dataset_name, isolate_name, year, country_code
) iso;

UPDATE isolate_patterns
  SET pattern = ''
  WHERE pattern IS NULL;

SELECT
  ROW_NUMBER() OVER () AS pattern_id,
  pattern,
  genes,
  year,
  -- subtype,
  country_code
INTO TABLE tmp_patterns
FROM (
  SELECT
    DISTINCT
    pattern,
    genes,
    year,
    -- subtype,
    country_code
  FROM isolate_patterns
) tmp;

INSERT INTO patterns (
  SELECT
    pattern_id,
    year,
    -- subtype,
    country_code
  FROM tmp_patterns
);

INSERT INTO pattern_surv_mutations (
  SELECT pattern_id, mutation
  FROM tmp_patterns, UNNEST(STRING_TO_ARRAY(pattern, ',')) mutation
);

INSERT INTO pattern_genes (
  SELECT pattern_id, gene::gene_enum
  FROM tmp_patterns, UNNEST(STRING_TO_ARRAY(genes, ',')) gene
);

DELETE FROM pattern_surv_mutations
  WHERE mutation = '';

INSERT INTO dataset_patterns (
  SELECT
    dataset_name,
    pattern_id,
    COUNT(*) AS num_isolates
  FROM isolate_patterns ip, tmp_patterns p
  WHERE
    ip.pattern = p.pattern AND
    ip.year = p.year AND
    -- ip.subtype = p.subtype AND
    ip.country_code = p.country_code
  GROUP BY dataset_name, pattern_id
);

DROP TABLE isolate_patterns;
DROP TABLE tmp_patterns;
