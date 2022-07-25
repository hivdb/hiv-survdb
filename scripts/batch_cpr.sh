#! /bin/bash
 
set -e

../hivdb-scripts/CPR/batch_cpr_docker -d payload/sequences/PRRT -o payload/suppl-tables/cpr_PRRT.txt -u https://hivdb.stanford.edu/cpr/form/PRRT/
../hivdb-scripts/CPR/batch_cpr_docker -d payload/sequences/IN -o payload/suppl-tables/cpr_IN.txt -u https://hivdb.stanford.edu/cpr/form/IN/

../hivdb-scripts/CPR/batch_download_xlsx_docker -s -i payload/suppl-tables/cpr_PRRT.txt -o payload/suppl-tables/cpr_results/PRRT
../hivdb-scripts/CPR/batch_download_xlsx_docker -s -i payload/suppl-tables/cpr_IN.txt -o payload/suppl-tables/cpr_results/IN
