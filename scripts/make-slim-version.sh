#!/bin/bash

DB_FILE=$1

sqlite3 $DB_FILE <<EOF
DELETE FROM isolates;
DELETE FROM isolate_mutations;
DELETE FROM isolate_excluded_surv_mutations;
DELETE FROM articles AS ref WHERE NOT EXISTS (
  SELECT 1 FROM datasets ds WHERE
    ref.ref_name = ds.ref_name AND
    ds.status NOT IN ('EX', 'New')
);
VACUUM;
EOF
