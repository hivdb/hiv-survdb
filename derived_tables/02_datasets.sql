INSERT INTO datasets
  SELECT DISTINCT
    refloc.ref_name,
    loc.continent_name
  FROM
    article_countries refloc,
    countries loc
  WHERE
    refloc.country_code = loc.country_code
  ORDER BY
    refloc.ref_name,
    loc.continent_name;

SELECT
  refiso.ref_name,
  loc.continent_name,
  iso.isolate_id,
  patient_id,
  gene,
  EXTRACT(YEAR FROM isolate_date) AS year,
  subtype,
  source,
  seq_method,
  cpr_excluded
INTO TABLE dataset_isolates
FROM
  isolates iso,
  article_isolates refiso,
  countries loc
WHERE
  refiso.isolate_id = iso.isolate_id AND
  iso.country_code = loc.country_code;

CREATE INDEX ON dataset_isolates (ref_name, continent_name);
CREATE INDEX ON dataset_isolates (ref_name, continent_name, gene);

INSERT INTO dataset_summaries
  SELECT DISTINCT
    d.ref_name,
    d.continent_name,
    (
      SELECT MIN(year) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name
    ) AS isolate_year_begin,
    (
      SELECT MAX(year) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name
    ) AS isolate_year_end,
    (
      SELECT STRING_AGG(source::TEXT, ',' ORDER BY source) FROM (
        SELECT DISTINCT source FROM dataset_isolates diso
        WHERE
          diso.ref_name = d.ref_name AND
          diso.continent_name = d.continent_name
      ) AS t1
    ) AS isolate_sources,
    (
      SELECT STRING_AGG(seq_method::TEXT, ',' ORDER BY seq_method) FROM (
        SELECT DISTINCT seq_method FROM dataset_isolates diso
        WHERE
          diso.ref_name = d.ref_name AND
          diso.continent_name = d.continent_name
      ) AS t2
    ) AS isolate_seq_methods,
    (
      SELECT COUNT(DISTINCT patient_id) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name
    ) AS num_patients,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name
    ) AS num_isolates,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name AND
        cpr_excluded IS NOT TRUE
    ) AS num_isolates_accepted,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.isolate_id = isomut.isolate_id AND
            diso.gene = sdrm.gene AND
            isomut.position = sdrm.position AND
            isomut.amino_acid = sdrm.amino_acid
        )
    ) AS num_sdrm_isolates,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name AND
        cpr_excluded IS NOT TRUE AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.isolate_id = isomut.isolate_id AND
            diso.gene = sdrm.gene AND
            isomut.position = sdrm.position AND
            isomut.amino_acid = sdrm.amino_acid
        )
    ) AS num_sdrm_isolates_accepted,
    0 AS pcnt_sdrm_isolates,
    0 AS pcnt_sdrm_isolates_accepted
  FROM datasets d;

UPDATE dataset_summaries
  SET pcnt_sdrm_isolates = 100.0 * num_sdrm_isolates / num_isolates;

UPDATE dataset_summaries
  SET pcnt_sdrm_isolates_accepted = 100.0 * num_sdrm_isolates_accepted / num_isolates_accepted;

INSERT INTO dataset_gene_summaries
  SELECT DISTINCT
    d.ref_name,
    d.continent_name,
    g.gene,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name AND
        diso.gene = g.gene
    ) AS num_isolates,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name AND
        diso.gene = g.gene AND
        cpr_excluded IS NOT TRUE
    ) AS num_isolates_accepted,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name AND
        diso.gene = g.gene AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.isolate_id = isomut.isolate_id AND
            g.gene = sdrm.gene AND
            isomut.position = sdrm.position AND
            isomut.amino_acid = sdrm.amino_acid
        )
    ) AS num_sdrm_isolates,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name AND
        diso.gene = g.gene AND
        cpr_excluded IS NOT TRUE AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.isolate_id = isomut.isolate_id AND
            g.gene = sdrm.gene AND
            isomut.position = sdrm.position AND
            isomut.amino_acid = sdrm.amino_acid
        )
    ) AS num_sdrm_isolates_accepted,
    0 AS pcnt_sdrm_isolates,
    0 AS pcnt_sdrm_isolates_accpeted
  FROM datasets d, (SELECT unnest(enum_range(NULL::gene_enum)) AS gene) g;

DELETE FROM dataset_gene_summaries WHERE num_isolates = 0;

UPDATE dataset_gene_summaries dcSum
  SET pcnt_sdrm_isolates = 100.0 * num_sdrm_isolates / num_isolates;

UPDATE dataset_gene_summaries dcSum
  SET pcnt_sdrm_isolates = 100.0 * num_sdrm_isolates_accepted / num_isolates_accepted;

INSERT INTO dataset_drug_class_summaries
  SELECT DISTINCT
    d.ref_name,
    d.continent_name,
    dc.gene,
    dc.drug_class,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name AND
        diso.gene = dc.gene AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.isolate_id = isomut.isolate_id AND
            dc.drug_class = sdrm.drug_class AND
            isomut.position = sdrm.position AND
            isomut.amino_acid = sdrm.amino_acid
        )
    ) AS num_sdrm_isolates,
    (
      SELECT COUNT(*) FROM dataset_isolates diso
      WHERE
        diso.ref_name = d.ref_name AND
        diso.continent_name = d.continent_name AND
        diso.gene = dc.gene AND
        cpr_excluded IS NOT TRUE AND
        EXISTS (
          SELECT 1 FROM isolate_mutations isomut, surv_mutations sdrm WHERE
            diso.isolate_id = isomut.isolate_id AND
            dc.drug_class = sdrm.drug_class AND
            isomut.position = sdrm.position AND
            isomut.amino_acid = sdrm.amino_acid
        )
    ) AS num_sdrm_isolates_accepted,
    0 AS pcnt_sdrm_isolates,
    0 AS pcnt_sdrm_isolates_accpeted
  FROM datasets d, drug_classes dc;

DELETE FROM dataset_drug_class_summaries dc WHERE NOT EXISTS(
  SELECT 1 FROM dataset_gene_summaries g
  WHERE
    g.ref_name = dc.ref_name AND
    g.continent_name = dc.continent_name AND
    g.gene = dc.gene
);

UPDATE dataset_drug_class_summaries dcSum
  SET pcnt_sdrm_isolates = 100.0 * dcSum.num_sdrm_isolates / gSum.num_isolates
  FROM dataset_gene_summaries gSum
  WHERE
    gSum.ref_name = dcSum.ref_name AND
    gSum.continent_name = dcSum.continent_name AND
    gSum.gene = dcSum.gene;

UPDATE dataset_drug_class_summaries dcSum
  SET pcnt_sdrm_isolates_accepted = 100.0 * dcSum.num_sdrm_isolates_accepted / gSum.num_isolates_accepted
  FROM dataset_gene_summaries gSum
  WHERE
    gSum.ref_name = dcSum.ref_name AND
    gSum.continent_name = dcSum.continent_name AND
    gSum.gene = dcSum.gene;

DROP TABLE dataset_isolates;
