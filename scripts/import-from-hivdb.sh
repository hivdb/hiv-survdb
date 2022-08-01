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

if [ -z "$1" -o ! -f "$1" ]; then
  echo "Usage: make reflist=path/to/reflist.csv import-from-hivdb"
  exit 1
fi
echo $1

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

# rm -rf $TARGET_ISO_DIR
mkdir -p $TMP_ISO_DIR
mkdir -p $TARGET_ISO_DIR

cat $1 |
  csvtk cut -f ref_name,ref_id |
  csvtk del-header |
  csvtk csv2tab | while IFS=$'\t' read -r ref_name ref_id;
do
  TMP_ISO="${TMP_ISO_DIR}/$(refname_for_file "$ref_name")-iso.csv"
  TARGET_ISO="${TARGET_ISO_DIR}/$(refname_for_file "$ref_name")-iso.csv"
  
  query > $TMP_ISO.1 <<EOF
    SELECT
      '${ref_name//\'/\'\'}' as dataset_name,
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
    csvtk cut -f dataset_name,isolate_name,patient_id,gene,isolate_date,subtype,source,seq_method,country_code,genbank_accn,cpr_excluded,date_entered > $TMP_ISO.2

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
