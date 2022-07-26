#!/bin/bash

DB_FILE=$1

sqlite3 $DB_FILE <<EOF
DELETE FROM article_isolates;
DELETE FROM isolates;
DELETE FROM isolate_mutations;
DELETE FROM isolate_excluded_surv_mutations;
VACUUM
EOF
