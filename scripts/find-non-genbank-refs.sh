#! /bin/bash

set -e

docker exec hiv-survdb-devdb psql -U postgres -c "
copy (
  SELECT DISTINCT ref_id, ref.ref_name
  FROM articles ref, article_isolates refiso, isolates iso
  WHERE
    ref.ref_name = refiso.ref_name AND
    refiso.isolate_id=iso.isolate_id AND
    iso.genbank_accn IS NULL
  ORDER BY ref_id
) TO STDOUT WITH CSV HEADER
" > $1

echo "Create $1"
