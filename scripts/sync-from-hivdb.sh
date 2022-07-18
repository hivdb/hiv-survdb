#! /bin/bash

set -e

mkdir -p payload/tables

function addbom() {
  unix2dos $1 2> /dev/null
  mv $1 $1.1
  printf '\xEF\xBB\xBF' > $1
  cat $1.1 >> $1
  rm $1.1
}

function query() {
  mysql --batch -h$HIVDB_HOST -u$HIVDB_USER -p$HIVDB_PASSWORD HIVDB2 "$@" | csvtk tab2csv -l
}


# ================
# Table `articles`
# ================

TARGET_ARTICLES=payload/tables/articles.csv
TMP_ARTICLES=/tmp/articles.csv

query > $TMP_ARTICLES <<EOF
  SELECT DISTINCT
    R.RefID as ref_id,
    'NULL' as doi,
    R.MedlineID as medline_id,
    'NULL' as url,
    (CASE WHEN Published = 'Yes' THEN 'TRUE' ELSE 'FALSE' END) AS published
  FROM tblSurRefs SR, tblReferences R
  WHERE
    SR.RefID = R.RefID
EOF

if [ ! -f $TARGET_ARTICLES -o ! -s $TARGET_ARTICLES ]; then
  cp $TMP_ARTICLES $TARGET_ARTICLES
fi
cat $TARGET_ARTICLES |
  csvtk cut -f '-medline_id,-published' > $TMP_ARTICLES.1

cat $TMP_ARTICLES |
  csvtk cut -f '-doi,-url' > $TMP_ARTICLES.2

csvtk join --outer-join $TMP_ARTICLES.1 $TMP_ARTICLES.2 -f ref_id --na NULL |
  csvtk cut -f 'ref_name,ref_id,doi,medline_id,url,published' |
  csvtk uniq -F -f '*' |
  csvtk sort -k ref_name > $TARGET_ARTICLES
rm $TMP_ARTICLES
rm $TMP_ARTICLES.1
rm $TMP_ARTICLES.2

addbom $TARGET_ARTICLES
echo "Sync $TARGET_ARTICLES"

# ================
# Table `journals`
# ================

TARGET_JOURNALS=payload/tables/journals.csv
query > $TARGET_JOURNALS <<EOF
  SELECT DISTINCT
    Journal as journal_name
  FROM tblReferences R
  WHERE EXISTS (
    SELECT 1 FROM tblSurRefs SR WHERE
      SR.RefID=R.RefID
  )
  ORDER BY journal_name
EOF

addbom $TARGET_JOURNALS
echo "Sync $TARGET_JOURNALS"

# ========================
# Table `article_metadata`
# ========================

TMP_REFMETA=/tmp/article_metadata.csv
TARGET_REFMETA=payload/tables/article_metadata.csv
query > $TMP_REFMETA.1 <<EOF
  SELECT
    R.RefID as ref_id,
    R.Author as first_author,
    R.Title as title,
    R.Journal as journal_name,
    R.RefYear as year
  FROM tblReferences R
  WHERE EXISTS (
    SELECT 1 FROM tblSurRefs SR WHERE
      SR.RefID=R.RefID
  )
EOF

cat $TARGET_ARTICLES |
  csvtk cut -f 'ref_name,ref_id' > $TMP_REFMETA.2

csvtk join --outer-join $TMP_REFMETA.1 $TMP_REFMETA.2 -f ref_id --na NULL |
  csvtk cut -f 'ref_name,first_author,title,journal_name,year' |
  csvtk sort -k ref_name > $TARGET_REFMETA
rm $TMP_REFMETA.1
rm $TMP_REFMETA.2

addbom $TARGET_REFMETA
echo "Sync $TARGET_REFMETA"
