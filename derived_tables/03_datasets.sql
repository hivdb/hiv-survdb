SELECT
  dataset_name,
  country_code,
  isolate_name,
  patient_id,
  gene,
  EXTRACT(YEAR FROM isolate_date) AS year,
  subtype,
  source,
  seq_method,
  cpr_excluded
INTO TABLE dataset_isolates
FROM isolates iso;

CREATE INDEX ON dataset_isolates (dataset_name, gene);
CREATE INDEX ON dataset_isolates (subtype);
CREATE INDEX ON dataset_isolates (isolate_name);

INSERT INTO dataset_summaries
  SELECT DISTINCT
    d.dataset_name,
    (
      SELECT MIN(year) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name
    ) AS isolate_year_begin,
    (
      SELECT MAX(year) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name
    ) AS isolate_year_end,
    (
      SELECT STRING_AGG(source::TEXT, ',' ORDER BY source) FROM (
        SELECT DISTINCT source FROM dataset_isolates diso
        WHERE
          diso.dataset_name = d.dataset_name
      ) AS t1
    ) AS isolate_sources,
    (
      SELECT STRING_AGG(seq_method::TEXT, ',' ORDER BY seq_method) FROM (
        SELECT DISTINCT seq_method FROM dataset_isolates diso
        WHERE
          diso.dataset_name = d.dataset_name
      ) AS t2
    ) AS isolate_seq_methods,
    (
      SELECT STRING_AGG(country_code, ',' ORDER BY country_code) FROM (
        SELECT DISTINCT country_code FROM dataset_isolates diso
        WHERE
          diso.dataset_name = d.dataset_name
      ) AS t2
    ) AS isolate_country_codes,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name
    ) AS num_isolates,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        cpr_excluded IS NOT TRUE
    ) AS num_isolates_accepted,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            isomut.mutation = sdrm.mutation AND
            NOT EXISTS (
              SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
                exsdrm.dataset_name = isomut.dataset_name AND
                exsdrm.isolate_name = isomut.isolate_name AND
                exsdrm.mutation = sdrm.mutation
            )
        )
    ) AS num_sdrm_isolates,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        cpr_excluded IS NOT TRUE AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            isomut.mutation = sdrm.mutation AND
            NOT EXISTS (
              SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
                exsdrm.dataset_name = isomut.dataset_name AND
                exsdrm.isolate_name = isomut.isolate_name AND
                exsdrm.mutation = sdrm.mutation
            )
        )
    ) AS num_sdrm_isolates_accepted,
    0 AS pcnt_sdrm_isolates,
    NULL::FLOAT AS pcnt_sdrm_isolates_accepted
  FROM datasets d
  WHERE status NOT IN ('EX', 'New');

UPDATE dataset_summaries
  SET pcnt_sdrm_isolates = 100.0 * num_sdrm_isolates / num_isolates;

UPDATE dataset_summaries
  SET pcnt_sdrm_isolates_accepted = CASE
    WHEN num_isolates_accepted = 0 THEN NULL::FLOAT
    ELSE 100.0 * num_sdrm_isolates_accepted / num_isolates_accepted
  END;

INSERT INTO dataset_gene_summaries
  SELECT DISTINCT
    d.dataset_name,
    g.gene,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = g.gene
    ) AS num_isolates,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = g.gene AND
        cpr_excluded IS NOT TRUE
    ) AS num_isolates_accepted,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = g.gene AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            isomut.mutation = sdrm.mutation AND
            NOT EXISTS (
              SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
                exsdrm.dataset_name = isomut.dataset_name AND
                exsdrm.isolate_name = isomut.isolate_name AND
                exsdrm.mutation = sdrm.mutation
            )
        )
    ) AS num_sdrm_isolates,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = g.gene AND
        cpr_excluded IS NOT TRUE AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            isomut.mutation = sdrm.mutation AND
            NOT EXISTS (
              SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
                exsdrm.dataset_name = isomut.dataset_name AND
                exsdrm.isolate_name = isomut.isolate_name AND
                exsdrm.mutation = sdrm.mutation
            )
        )
    ) AS num_sdrm_isolates_accepted,
    0 AS pcnt_sdrm_isolates,
    NULL::FLOAT AS pcnt_sdrm_isolates_accpeted
  FROM datasets d, (SELECT unnest(enum_range(NULL::gene_enum)) AS gene) g
  WHERE status NOT IN ('EX', 'New');

DELETE FROM dataset_gene_summaries WHERE num_isolates = 0;

UPDATE dataset_gene_summaries dcSum
  SET pcnt_sdrm_isolates = 100.0 * num_sdrm_isolates / num_isolates;

UPDATE dataset_gene_summaries dcSum
  SET pcnt_sdrm_isolates_accepted = CASE
    WHEN num_isolates_accepted = 0 THEN NULL::FLOAT
    ELSE 100.0 * num_sdrm_isolates_accepted / num_isolates_accepted
  END;

INSERT INTO dataset_drug_class_summaries
  SELECT DISTINCT
    d.dataset_name,
    dc.gene,
    dc.drug_class,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = dc.gene AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            dc.drug_class = sdrm.drug_class AND
            isomut.mutation = sdrm.mutation AND
            NOT EXISTS (
              SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
                exsdrm.dataset_name = isomut.dataset_name AND
                exsdrm.isolate_name = isomut.isolate_name AND
                exsdrm.mutation = sdrm.mutation
            )
        )
    ) AS num_isolates,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = dc.gene AND
        cpr_excluded IS NOT TRUE AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            dc.drug_class = sdrm.drug_class AND
            isomut.mutation = sdrm.mutation AND
            NOT EXISTS (
              SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
                exsdrm.dataset_name = isomut.dataset_name AND
                exsdrm.isolate_name = isomut.isolate_name AND
                exsdrm.mutation = sdrm.mutation
            )
        )
    ) AS num_isolates_accepted,
    0 AS pcnt_isolates,
    NULL::FLOAT AS pcnt_isolates_accpeted
  FROM datasets d, drug_classes dc
  WHERE status NOT IN ('EX', 'New');

DELETE FROM dataset_drug_class_summaries dc WHERE NOT EXISTS (
  SELECT 1 FROM dataset_gene_summaries g
  WHERE
    dc.dataset_name = g.dataset_name AND
    dc.gene = g.gene
);

UPDATE dataset_drug_class_summaries dcSum
  SET pcnt_isolates = 100.0 * dcSum.num_isolates / gSum.num_isolates
  FROM dataset_gene_summaries gSum
  WHERE
    gSum.dataset_name = dcSum.dataset_name AND
    gSum.gene = dcSum.gene;

UPDATE dataset_drug_class_summaries dcSum
  SET pcnt_isolates_accepted = CASE
    WHEN gSum.num_isolates_accepted = 0 THEN NULL::FLOAT
    ELSE 100.0 * dcSum.num_isolates_accepted / gSum.num_isolates_accepted
  END
  FROM dataset_gene_summaries gSum
  WHERE
    gSum.dataset_name = dcSum.dataset_name AND
    gSum.gene = dcSum.gene;

SELECT DISTINCT subtype
  INTO subtypes
  FROM isolates
  ORDER BY subtype;

INSERT INTO dataset_subtype_summaries
  SELECT DISTINCT
    d.dataset_name,
    g.gene,
    s.subtype,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = g.gene AND
        diso.subtype = s.subtype
    ) AS num_isolates,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = g.gene AND
        diso.subtype = s.subtype AND
        cpr_excluded IS NOT TRUE
    ) AS num_isolates_accepted,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = g.gene AND
        diso.subtype = s.subtype AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            isomut.mutation = sdrm.mutation AND
            NOT EXISTS (
              SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
                exsdrm.dataset_name = isomut.dataset_name AND
                exsdrm.isolate_name = isomut.isolate_name AND
                exsdrm.mutation = sdrm.mutation
            )
        )
    ) AS num_sdrm_isolates,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = g.gene AND
        diso.subtype = s.subtype AND
        cpr_excluded IS NOT TRUE AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            isomut.mutation = sdrm.mutation AND
            NOT EXISTS (
              SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
                exsdrm.dataset_name = isomut.dataset_name AND
                exsdrm.isolate_name = isomut.isolate_name AND
                exsdrm.mutation = sdrm.mutation
            )
        )
    ) AS num_sdrm_isolates_accepted,
    0 AS pcnt_sdrm_isolates,
    NULL::FLOAT AS pcnt_sdrm_isolates_accpeted
  FROM datasets d, subtypes s, (SELECT unnest(enum_range(NULL::gene_enum)) AS gene) g
  WHERE
    status NOT IN ('EX', 'New') AND
    EXISTS (
      SELECT 1 FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = g.gene AND
        diso.subtype = s.subtype
    );

UPDATE dataset_subtype_summaries sSum
  SET pcnt_sdrm_isolates = 100.0 * sSum.num_sdrm_isolates / gSum.num_isolates
  FROM dataset_gene_summaries gSum
  WHERE
    gSum.dataset_name = sSum.dataset_name AND
    gSum.gene = sSum.gene;

UPDATE dataset_subtype_summaries sSum
  SET pcnt_sdrm_isolates_accepted = CASE
    WHEN gSum.num_isolates_accepted = 0 THEN NULL::FLOAT
    ELSE 100.0 * sSum.num_sdrm_isolates_accepted / gSum.num_isolates_accepted
  END
  FROM dataset_gene_summaries gSum
  WHERE
    gSum.dataset_name = sSum.dataset_name AND
    gSum.gene = sSum.gene;

INSERT INTO dataset_surv_mutation_summaries
  SELECT DISTINCT
    d.dataset_name,
    m.gene,
    m.mutation,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = m.gene AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            isomut.mutation = m.mutation
        ) AND
        NOT EXISTS (
          SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
            diso.dataset_name = exsdrm.dataset_name AND
            diso.isolate_name = exsdrm.isolate_name AND
            exsdrm.mutation = m.mutation
        )
    ) AS num_isolates,
    (
      SELECT COUNT(DISTINCT isolate_name) FROM dataset_isolates diso
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.gene = m.gene AND
        cpr_excluded IS NOT TRUE AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut WHERE
            diso.dataset_name = isomut.dataset_name AND
            diso.isolate_name = isomut.isolate_name AND
            isomut.mutation = m.mutation
        ) AND
        NOT EXISTS (
          SELECT 1 FROM isolate_excluded_surv_mutations exsdrm WHERE
            diso.dataset_name = exsdrm.dataset_name AND
            diso.isolate_name = exsdrm.isolate_name AND
            exsdrm.mutation = m.mutation
        )
    ) AS num_isolates_accepted,
    0 AS pcnt_isolates,
    NULL::FLOAT AS pcnt_isolates_accpeted
  FROM datasets d, surv_mutations m
  WHERE
    status NOT IN ('EX', 'New') AND
    EXISTS (
      SELECT 1 FROM dataset_isolates diso, isolate_mutations isomut
      WHERE
        diso.dataset_name = d.dataset_name AND
        diso.dataset_name = isomut.dataset_name AND
        diso.isolate_name = isomut.isolate_name AND
        isomut.mutation = m.mutation
    );

UPDATE dataset_surv_mutation_summaries mSum
  SET pcnt_isolates = 100.0 * mSum.num_isolates / gSum.num_isolates
  FROM dataset_gene_summaries gSum
  WHERE
    gSum.dataset_name = mSum.dataset_name AND
    gSum.gene = mSum.gene;

UPDATE dataset_surv_mutation_summaries mSum
  SET pcnt_isolates_accepted = CASE
    WHEN gSum.num_isolates_accepted = 0 THEN NULL::FLOAT
    ELSE 100.0 * mSum.num_isolates_accepted / gSum.num_isolates_accepted
  END
  FROM dataset_gene_summaries gSum
  WHERE
    gSum.dataset_name = mSum.dataset_name AND
    gSum.gene = mSum.gene;

DROP TABLE dataset_isolates;
DROP TABLE subtypes;
