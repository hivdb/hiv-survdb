#! /bin/bash

set -e

function refname_for_file() {
  echo "${1,,}" | sed "s/[[:space:]]\+/-/g" | sed "s/['\"]//g"
}

function make_permanent_link() {
  uuid=$(echo $1 | cut -d '=' -f 2 | tr -d $'\r' | tr -d $'\n')
  aws s3 cp s3://cprstorage/main/$uuid s3://cprstorage/main/hiv-survdb/$2 >&2
  echo "https://hivdb.stanford.edu/cpr/report/?load=hiv-survdb/$2"
}

function addbom() {
  unix2dos $1 2> /dev/null
  mv $1 $1.1
  printf '\xEF\xBB\xBF' > $1
  cat $1.1 >> $1
  rm $1.1
}

echo "ref_name,test_code,permanent_url" > payload/tables/article_cpr_urls.csv

tail -n +2 payload/tables/articles.csv | cut -d ',' -f 1 | while read ref_name; do
  lower_ref_name=$(refname_for_file $ref_name)
  url=$(grep "^$lower_ref_name-seqs\.fas" payload/suppl-tables/cpr_PRRT.txt | cut -d $'\t' -f 2 | tr -d $'\r' | tr -d $'\n')
  if [ -n "$url" ]; then
    permurl=$(make_permanent_link $url "$lower_ref_name-PRRT")
    echo $ref_name,PRRT,$permurl >> payload/tables/article_cpr_urls.csv
  fi
  url=$(grep "^$lower_ref_name-seqs\.fas" payload/suppl-tables/cpr_IN.txt | cut -d $'\t' -f 2 | tr -d $'\r' | tr -d $'\n')
  if [ -n "$url" ]; then
    permurl=$(make_permanent_link $url "$lower_ref_name-IN")
    echo $ref_name,IN,$permurl >> payload/tables/article_cpr_urls.csv
  fi
done

addbom payload/tables/article_cpr_urls.csv
