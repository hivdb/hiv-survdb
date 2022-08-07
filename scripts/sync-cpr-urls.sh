#! /bin/bash

set -e

function refname_for_file() {
  echo "${1,,}" | sed "s/[[:space:]]\+/-/g" | sed "s/['\"]//g"
}

function make_permanent_link() {
  uuid=$(echo $1 | cut -d '=' -f 2 | tr -d $'\r' | tr -d $'\n')
  mainfile=$(mktemp)
  treefile=$(mktemp)
  aws s3 cp s3://cprstorage/main/$uuid $mainfile >&2
  aws s3 cp s3://cprstorage/tree/$uuid $treefile.gz >&2
  rm $treefile
  pigz -d $treefile.gz
  sed -i 's/\.\(PtID[[:digit:]]*\)[.|][[:digit:]]\{4\}/.\1/g' $mainfile
  sed -i 's/\.\(PtID[[:digit:]]*\)[.|][[:digit:]]\{4\}/.\1/g' $treefile
  pigz -9 $mainfile
  pigz -9 $treefile
  aws s3 cp $mainfile.gz s3://cprstorage/main/hiv-survdb/$2 --content-encoding gzip --cache-control max-age=2592000 >&2
  aws s3 cp $treefile.gz s3://cprstorage/tree/hiv-survdb/$2 --content-encoding gzip --cache-control max-age=2592000 >&2
  echo "https://hivdb.stanford.edu/cpr/report/?load=hiv-survdb/$2"
  rm $mainfile.gz $treefile.gz
}

function addbom() {
  unix2dos $1 2> /dev/null
  mv $1 $1.1
  printf '\xEF\xBB\xBF' > $1
  cat $1.1 >> $1
  rm $1.1
}

echo "ref_name,continent_name,permanent_url" > payload/suppl-tables/dataset_cpr_urls_new.csv

declare -A REFNAME_LOOKUP

for ref_name in $(tail -n +2 payload/tables/articles.csv | cut -d ',' -f 1); do
  lower_ref_name=$(refname_for_file $ref_name)
  if [ -z "${REFNAME_LOOKUP[$lower_ref_name]}" ]; then
    REFNAME_LOOKUP[$lower_ref_name]=$ref_name
  else
    echo 'Conflict ref_name: ${REFNAME_LOOKUP[$lower_ref_name]} and $ref_name'
  fi
done

tail -n +2 payload/suppl-tables/cpr_POL_new.txt | while IFS=$'\t' read fasfile url; do
  key_name="${fasfile%-seq.fas}"
  lower_ref_name=$key_name
  continent_name='NULL'
  if [[ $key_name == *-africa ]]; then
    lower_ref_name="${lower_ref_name%-africa}"
    continent_name='Africa'
  elif [[ $key_name == *-asia ]]; then
    lower_ref_name="${lower_ref_name%-asia}"
    continent_name='Asia'
  elif [[ $key_name == *-europe ]]; then
    lower_ref_name="${lower_ref_name%-europe}"
    continent_name='Europe'
  elif [[ $key_name == *-north-america ]]; then
    lower_ref_name="${lower_ref_name%-north-america}"
    continent_name='North America'
  elif [[ $key_name == *-oceania ]]; then
    lower_ref_name="${lower_ref_name%-oceania}"
    continent_name='Oceania'
  elif [[ $key_name == *-south-america ]]; then
    lower_ref_name="${lower_ref_name%-south-america}"
    continent_name='South America'
  fi

  permurl=$(make_permanent_link $url $key_name)
  ref_name="${REFNAME_LOOKUP[$lower_ref_name]}"
  echo $ref_name,$continent_name,$permurl >> payload/suppl-tables/dataset_cpr_urls_new.csv
done

addbom payload/suppl-tables/dataset_cpr_urls_new.csv
