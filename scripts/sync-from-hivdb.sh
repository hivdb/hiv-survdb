#! /bin/bash

set -e

mkdir -p payload/tables

function refname_for_file() {
  echo "${1,,}" | sed "s/[[:space:]]\+/-/g" | sed "s/['\"]//g"
}

function tab2csv() {
	python3 -c "
import csv
import sys

reader = csv.reader(sys.stdin, delimiter='\t')
writer = csv.writer(sys.stdout)
writer.writerows(reader)
"
}

function test_csv_empty() {
  test "$(wc -l $1 | awk '{print $1}')" -lt 2
}

function addbom() {
  unix2dos $1 2> /dev/null
  mv $1 $1.1
  printf '\xEF\xBB\xBF' > $1
  cat $1.1 >> $1
  rm $1.1
}

function query() {
  tmpfile=$(mktemp)
  mysql --batch -h$HIVDB_HOST -u$HIVDB_USER -p$HIVDB_PASSWORD HIVDB2 "$@" > "$tmpfile"
  if [ -s "$tmpfile" ]; then
    cat "$tmpfile" | tab2csv
  fi
  rm "$tmpfile"
}

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
    R.Author as first_author,
    R.Title as title,
    CASE
       WHEN LOWER(R.Journal) = 'plos one' THEN 'PLoS ONE'
       ELSE R.Journal
    END as journal_name,
    R.RefYear as year,
    CASE WHEN Published = 'Yes' THEN 'TRUE' ELSE 'FALSE' END AS published
  FROM tblSurRefs SR, tblReferences R
  WHERE
    SR.RefID = R.RefID AND
    R.RefID NOT IN (1154)
EOF

if [ ! -f $TARGET_ARTICLES -o ! -s $TARGET_ARTICLES ]; then
  cp $TMP_ARTICLES $TARGET_ARTICLES
fi
cat $TARGET_ARTICLES |
  csvtk cut -f '-medline_id,-published,-first_author,-title,-journal_name,-year' > $TMP_ARTICLES.1

cat $TMP_ARTICLES |
  csvtk cut -f '-doi,-url' > $TMP_ARTICLES.2

csvtk join --outer-join $TMP_ARTICLES.1 $TMP_ARTICLES.2 -f ref_id --na NULL |
  csvtk cut -f 'ref_name,ref_id,doi,medline_id,url,first_author,title,journal_name,year,published' |
  csvtk uniq -F -f '*' |
  csvtk sort -k ref_name > $TARGET_ARTICLES
rm $TMP_ARTICLES
rm $TMP_ARTICLES.1
rm $TMP_ARTICLES.2

addbom $TARGET_ARTICLES
echo "Create $TARGET_ARTICLES"

# # ===========================
# # Table `article_annotations`
# # ===========================
# 
# TMP_ANNOTS=/tmp/ref_annots.csv
# TARGET_ANNOTS=payload/tables/article_annotations.csv
# 
# query > $TMP_ANNOTS.1 <<EOF
#   SELECT DISTINCT
#     SR.RefID as ref_id,
#     SR.Status as status,
#     SR.Study_Notes as annotation,
#     CASE WHEN SR.Action LIKE 'Use_Only_From_Region:%' THEN 'NULL' ELSE SR.Action END as action
#   FROM tblSurRefs SR
#   WHERE
#     SR.RefID NOT IN (1154)
# EOF
# 
# cat $TARGET_ARTICLES |
#   csvtk cut -f 'ref_name,ref_id' > $TMP_ANNOTS.2
# 
# csvtk join $TMP_ANNOTS.1 $TMP_ANNOTS.2 -f ref_id --na NULL |
#   csvtk cut -f 'ref_name,status,annotation,action' |
#   csvtk sort -k ref_name > $TARGET_ANNOTS
# rm $TMP_ANNOTS.1
# rm $TMP_ANNOTS.2
# 
# addbom $TARGET_ANNOTS
# echo "Create $TARGET_ANNOTS"


# ================
# Table `isolates`
# ================

TMP_ISO_DIR=/tmp/isolates
TARGET_ISO_DIR=payload/tables/isolates.d
GENE_ORDER=$(mktemp)

cat > $GENE_ORDER <<EOF
PR
RT
IN
EOF

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
    SELECT
      '${ref_name//\'/\'\'}' as ref_name,
      P.PseudoName as isolate_name,
      I.PtID as patient_id,
      I.Gene as gene,
      I.IsolateDate as isolate_date,
      ST.Subtype as subtype,
      CI.Source as source,
      CI.SeqMethod as seq_method,
      P.Region as country_name,
      GROUP_CONCAT(DISTINCT Seq.AccessionID SEPARATOR ',') as genbank_accn,
      NULL as cpr_excluded,
      I.DateEntered as date_entered
    FROM tblRefLink RL
      JOIN tblIsolates I ON RL.IsolateID=I.IsolateID
      JOIN tblClinIsolates CI ON RL.IsolateID=CI.IsolateID
      JOIN tblSequences Seq ON RL.IsolateID=Seq.IsolateID
      JOIN tblSpecies SP ON RL.IsolateID=SP.IsolateID
      JOIN tblSubtypes ST ON RL.IsolateID=ST.IsolateID
      JOIN tblPatients P ON I.PtID = P.PtID
    WHERE
      RL.RefID = ${ref_id}
    GROUP BY
      P.PseudoName,
      I.PtID,
      I.Gene,
      I.IsolateDate,
      ST.Subtype,
      CI.Source,
      CI.SeqMethod,
      P.Region,
      I.DateEntered
    ORDER BY
      P.PseudoName,
      I.IsolateDate
EOF

  if [ ! -s $TMP_ISO.1 ]; then
    echo "Skip empty $TARGET_ISO"
    continue
  fi

  csvtk join --left-join $TMP_ISO.1 payload/suppl-tables/country_names_and_codes.csv -f country_name --na NULL |
    csvtk cut -f ref_name,isolate_name,patient_id,gene,isolate_date,subtype,source,seq_method,country_code,genbank_accn,cpr_excluded,date_entered > $TMP_ISO.2

  csvtk cut -f isolate_name $TMP_ISO.2 | csvtk del-header | sort --version-sort > $TMP_ISO.3
  csvtk sort -k isolate_name:u,gene:u -L isolate_name:$TMP_ISO.3 -L gene:$GENE_ORDER $TMP_ISO.2 > $TMP_ISO.4
  
  if test_csv_empty $TMP_ISO.4; then
    echo "Skip empty $TARGET_ISO"
  else
    addbom $TMP_ISO.4
    mv $TMP_ISO.4 $TARGET_ISO
    echo "Create $TARGET_ISO"
  fi

done

rm -rf $TMP_ISO_DIR
