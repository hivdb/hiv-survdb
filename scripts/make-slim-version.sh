#!/bin/bash

DB_FILE=$1

sqlite3 $DB_FILE <<EOF
DELETE FROM isolates;
DELETE FROM isolate_mutations;
DELETE FROM isolate_excluded_surv_mutations;
DELETE FROM articles AS ref WHERE EXISTS (
  SELECT 1 FROM article_annotations refnote WHERE
    ref.ref_name = refnote.ref_name AND
    refnote.status IN ('EX', 'New')
);
DELETE FROM article_summaries AS ref WHERE EXISTS (
  SELECT 1 FROM article_annotations refnote WHERE
    ref.ref_name = refnote.ref_name AND
    refnote.status IN ('EX', 'New')
);
DELETE FROM dataset_summaries AS ref WHERE EXISTS (
  SELECT 1 FROM article_annotations refnote WHERE
    ref.ref_name = refnote.ref_name AND
    refnote.status IN ('EX', 'New')
);
DELETE FROM dataset_gene_summaries AS ref WHERE EXISTS (
  SELECT 1 FROM article_annotations refnote WHERE
    ref.ref_name = refnote.ref_name AND
    refnote.status IN ('EX', 'New')
);
DELETE FROM dataset_drug_class_summaries AS ref WHERE EXISTS (
  SELECT 1 FROM article_annotations refnote WHERE
    ref.ref_name = refnote.ref_name AND
    refnote.status IN ('EX', 'New')
);
DELETE FROM dataset_subtype_summaries AS ref WHERE EXISTS (
  SELECT 1 FROM article_annotations refnote WHERE
    ref.ref_name = refnote.ref_name AND
    refnote.status IN ('EX', 'New')
);
DELETE FROM dataset_surv_mutation_summaries AS ref WHERE EXISTS (
  SELECT 1 FROM article_annotations refnote WHERE
    ref.ref_name = refnote.ref_name AND
    refnote.status IN ('EX', 'New')
);
VACUUM;
EOF
