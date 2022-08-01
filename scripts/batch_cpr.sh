#! /bin/bash
 
set -e

../hivdb-scripts/CPR/batch_cpr_docker -d payload/sequences/new -o payload/suppl-tables/cpr_POL_new.txt -u https://hivdb.stanford.edu/cpr/form/POL/

rm -f payload/suppl-tables/cpr-results/*.xlsx
../hivdb-scripts/CPR/batch_download_xlsx_docker -s -i payload/suppl-tables/cpr_POL_new.txt -o payload/suppl-tables/cpr_results
