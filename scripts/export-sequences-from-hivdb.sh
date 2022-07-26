#! /bin/bash

set -e

source docker-envfile

function separate_genes() {
  if [ -f "$1" ]; then
    file_prrt=$(dirname $1)/PRRT/$(basename $1)
    file_in=$(dirname $1)/IN/$(basename $1)
    \grep -A1 ">.*PRRT$" "$1" | \grep -v -F -- "--" > $file_prrt || true
    \grep -A1 ">.*IN$" "$1" | \grep -v -F -- "--" > $file_in || true
    if [ ! -s $file_prrt ]; then
      rm $file_prrt
    fi
    if [ ! -s $file_in ]; then
      rm $file_in
    fi

  fi
}

function refname_for_file() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed "s/[[:space:]]\+/-/g" | sed "s/['\"]//g"
}
export DATABASE_URI="mysql+pymysql://$HIVDB_USER:$HIVDB_PASSWORD@$HIVDB_HOST/HIVDB2"

mkdir -p $1
mkdir -p $1/PRRT
mkdir -p $1/IN

tail -n +2 payload/tables/articles.csv | while IFS="," read -r ref_name ref_id extras; do
  TARGET=$(realpath "$1/$(refname_for_file "$ref_name")-seqs.fas")
  METADATA=$(realpath "$1/$(refname_for_file "$ref_name")-meta.json")
  if [ -f $METADATA ]; then
    echo "Skip existing $TARGET"
    separate_genes $TARGET
    continue
  fi
  pushd ../hivdb-graphql > /dev/null
  echo "Exporting $TARGET ..."
  pipenv run hivdbql export-fasta2 \
    --no-filter \
    --rx naive \
    --refs $ref_id \
    --concat-option PRRT/IN \
    --trim-dot \
    --metadata-json $METADATA \
    $TARGET
  separate_genes $TARGET
  popd > /dev/null
done
