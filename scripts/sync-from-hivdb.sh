#! /bin/bash

set -e

mkdir -p payload/tables

function refname_for_file() {
  echo "${1,,}" | sed "s/[[:space:]]\+/-/g" | sed "s/['\"]//g"
}

function sql_escape() {
  echo "$1" | sed "s/'/''/g"
}

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
echo "Create $TARGET_ARTICLES"

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
echo "Create $TARGET_JOURNALS"

# ========================
# Table `article_metadata`
# ========================

TMP_REFMETA=/tmp/article_metadata.csv
TARGET_REFMETA=payload/tables/article_metadata.csv
query > $TMP_REFMETA.1 <<EOF
  SELECT DISTINCT
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
echo "Create $TARGET_REFMETA"

# ========================
# Table `article_isolates`
# ========================

TMP_REFISO_DIR=/tmp/refiso
TARGET_REFISO_DIR=payload/tables/article_isolates.d
rm -rf $TARGET_REFISO_DIR
mkdir -p $TMP_REFISO_DIR
mkdir -p $TARGET_REFISO_DIR

cat $TARGET_ARTICLES |
  csvtk cut -f ref_name,ref_id |
  csvtk del-header |
  csvtk csv2tab | while IFS=$'\t' read -r ref_name ref_id;
do
  TMP_REFISO="${TMP_REFISO_DIR}/$(refname_for_file "$ref_name")-refiso.csv"
  TARGET_REFISO="${TARGET_REFISO_DIR}/$(refname_for_file "$ref_name")-refiso.csv"
  
  query > $TMP_REFISO <<EOF
    SELECT DISTINCT
      '$(sql_escape ${ref_name})' as ref_name,
      RL.IsolateID as isolate_id
    FROM tblRefLink RL
    WHERE RL.RefID = ${ref_id}
EOF
  
  addbom $TMP_REFISO
  mv $TMP_REFISO $TARGET_REFISO
  echo "Create $TARGET_REFISO"

done

rm -rf $TMP_REFISO_DIR

# ================
# Table `isolates`
# ================

TMP_ISO_DIR=/tmp/isolates
TARGET_ISO_DIR=payload/tables/isolates.d

rm -rf $TARGET_ISO_DIR
mkdir -p $TMP_ISO_DIR
mkdir -p $TARGET_ISO_DIR

cat $TARGET_ARTICLES |
  csvtk cut -f ref_name,ref_id |
  csvtk del-header |
  csvtk csv2tab | while IFS=$'\t' read -r ref_name ref_id;
do
  TMP_ISO="${TMP_ISO_DIR}/$(refname_for_file "$ref_name")-iso.csv"
  TARGET_ISO="${TARGET_ISO_DIR}/$(refname_for_file "$ref_name")-iso.csv"
  
  query > $TMP_ISO.1 <<EOF
    SELECT DISTINCT
      RL.IsolateID as isolate_id,
      I.PtID as patient_id,
      I.Gene as gene,
      I.IsolateDate as isolate_date,
      S.Subtype as subtype,
      CI.Source as source,
      CI.SeqMethod as seq_method,
      P.Region as country_name,
      I.DateEntered as date_entered
    FROM tblRefLink RL, tblIsolates I, tblSubtypes S, tblClinIsolates CI, tblPatients P
    WHERE
      RL.RefID = ${ref_id} AND
      RL.IsolateID = I.IsolateID AND
      RL.IsolateID = S.IsolateID AND
      RL.IsolateID = CI.IsolateID AND
      I.PtID = P.PtID
    ORDER BY
      RL.IsolateID
EOF

  csvtk join --left-join $TMP_ISO.1 payload/suppl-tables/country_names_and_codes.csv -f country_name --na NULL |
    csvtk cut -f isolate_id,patient_id,gene,isolate_date,subtype,source,seq_method,country_code,date_entered > $TMP_ISO.2
  
  addbom $TMP_ISO.2
  mv $TMP_ISO.2 $TARGET_ISO
  echo "Create $TARGET_ISO"

done

rm -rf $TMP_ISO_DIR

# ========================
# Table `isolate_mutations
# ========================

TMP_ISOMUT_DIR=/tmp/isomuts
TARGET_ISOMUT_DIR=payload/tables/isolate_mutations.d

rm -rf $TARGET_ISOMUT_DIR
mkdir -p $TMP_ISOMUT_DIR
mkdir -p $TARGET_ISOMUT_DIR

cat $TARGET_ARTICLES |
  csvtk cut -f ref_name,ref_id |
  csvtk del-header |
  csvtk csv2tab | while IFS=$'\t' read -r ref_name ref_id;
do
  TMP_ISOMUT="${TMP_ISOMUT_DIR}/$(refname_for_file "$ref_name")-isomuts.csv"
  TARGET_ISOMUT="${TARGET_ISOMUT_DIR}/$(refname_for_file "$ref_name")-isomuts.csv"
  
  query > $TMP_ISOMUT <<EOF
    SELECT
      DISTINCT
      RL.IsolateID as isolate_id,
      M.CodonPos as position,
      (CASE
        WHEN M.Insertion = 'Yes' THEN 'ins'
        WHEN M.MutAA = '~' THEN 'del'
        WHEN M.MutAA = '*' THEN 'stop'
        ELSE M.MutAA
      END) as amino_acid
    FROM tblRefLink RL, tblSequences S, _Mutations M
    WHERE
      RL.RefID = ${ref_id} AND
      RL.IsolateID = S.IsolateID AND
      S.SequenceID = M.SequenceID AND
      M.Mixture = 'No' AND
      M.MutAA != '.'
    ORDER BY RL.IsolateID, M.CodonPos, M.MutAA
EOF
  
  addbom $TMP_ISOMUT
  mv $TMP_ISOMUT $TARGET_ISOMUT
  echo "Create $TARGET_ISOMUT"

done

rm -rf $TMP_ISOMUT_DIR
