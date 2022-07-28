#! /bin/bash
 
set -e

../hivdb-scripts/CPR/batch_cpr_docker -d payload/sequences -o payload/suppl-tables/cpr_POL.txt -u https://hivdb.stanford.edu/cpr/form/POL/

rm -f payload/suppl-tables/cpr-results/*.xlsx
../hivdb-scripts/CPR/batch_download_xlsx_docker -s -i payload/suppl-tables/cpr_POL.txt -o payload/suppl-tables/cpr_results
