#! /bin/bash

set -e

mkdir -p payload/tables

function refname_for_file() {
  echo "${1,,}" | sed "s/[[:space:]]\+/-/g" | sed "s/['\"]//g"
}

function sql_escape() {
  echo "$1" | sed "s/'/''/g"
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

# ===========================
# Table `article_annotations`
# ===========================

TMP_ANNOTS=/tmp/ref_annots.csv
TARGET_ANNOTS=payload/tables/article_annotations.csv

query > $TMP_ANNOTS.1 <<EOF
  SELECT DISTINCT
    SR.RefID as ref_id,
    SR.Status as status,
    SR.Study_Notes as annotation,
    CASE WHEN SR.Action LIKE 'Use_Only_From_Region:%' THEN 'NULL' ELSE SR.Action END as action
  FROM tblSurRefs SR
  WHERE
    SR.RefID NOT IN (1154)
EOF

cat $TARGET_ARTICLES |
  csvtk cut -f 'ref_name,ref_id' > $TMP_ANNOTS.2

csvtk join $TMP_ANNOTS.1 $TMP_ANNOTS.2 -f ref_id --na NULL |
  csvtk cut -f 'ref_name,status,annotation,action' |
  csvtk sort -k ref_name > $TARGET_ANNOTS
rm $TMP_ANNOTS.1
rm $TMP_ANNOTS.2

addbom $TARGET_ANNOTS
echo "Create $TARGET_ANNOTS"


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
      '$(sql_escape "${ref_name}")' as ref_name,
      RL.IsolateID as isolate_id
    FROM tblRefLink RL
    WHERE
      RL.RefID = ${ref_id} AND
      -- NOT EXISTS (
      --   SELECT 1 FROM tblIsolateFilters IsoF
      --   WHERE
      --     RL.IsolateID = IsoF.IsolateID AND
      --     IsoF.Filter = 'QA'
      -- ) AND
      EXISTS (
        SELECT 1 FROM tblIsolates I
        WHERE
          RL.IsolateID = I.IsolateID AND
          I.Type = 'Clinical'
      )
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
    SELECT
      RL.IsolateID as isolate_id,
      I.PtID as patient_id,
      I.Gene as gene,
      I.IsolateDate as isolate_date,
      S.Subtype as subtype,
      CI.Source as source,
      CI.SeqMethod as seq_method,
      P.Region as country_name,
      GROUP_CONCAT(Seq.AccessionID SEPARATOR ',') as genbank_accn,
      NULL as cpr_excluded,
      I.DateEntered as date_entered
    FROM tblRefLink RL, tblIsolates I, tblSubtypes S, tblClinIsolates CI, tblPatients P, tblSequences Seq
    WHERE
      RL.RefID = ${ref_id} AND
      -- NOT EXISTS (
      --   SELECT 1 FROM tblIsolateFilters IsoF
      --   WHERE
      --     RL.IsolateID = IsoF.IsolateID AND
      --     IsoF.Filter = 'QA'
      -- ) AND
      RL.IsolateID = I.IsolateID AND
      RL.IsolateID = S.IsolateID AND
      RL.IsolateID = CI.IsolateID AND
      RL.IsolateID = Seq.IsolateID AND
      (
        RL.Priority = 1 OR
        NOT EXISTS (
          SELECT 1 FROM tblSurRefs SR, tblRefLink RL2
          WHERE
            SR.RefID != ${ref_id} AND
            SR.RefID = RL2.RefID AND
            RL2.IsolateID = RL.IsolateID AND
            RL2.Priority = 1
        )
      ) AND
      I.Type = 'Clinical' AND
      I.PtID = P.PtID
    GROUP BY
      RL.IsolateID,
      I.PtID,
      I.Gene,
      I.IsolateDate,
      S.Subtype,
      CI.Source,
      CI.SeqMethod,
      P.Region,
      I.DateEntered
    ORDER BY
      RL.IsolateID
EOF

  if [ ! -s $TMP_ISO.1 ]; then
    echo "Skip empty $TARGET_ISO"
    continue
  fi

  csvtk join --left-join $TMP_ISO.1 payload/suppl-tables/country_names_and_codes.csv -f country_name --na NULL |
    csvtk cut -f isolate_id,patient_id,gene,isolate_date,subtype,source,seq_method,country_code,genbank_accn,cpr_excluded,date_entered > $TMP_ISO.2
  
  addbom $TMP_ISO.2
  mv $TMP_ISO.2 $TARGET_ISO
  echo "Create $TARGET_ISO"

done

rm -rf $TMP_ISO_DIR

# =========================
# Table `isolate_mutations`
# =========================

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
  
  query > $TMP_ISOMUT.1 <<EOF
    SELECT
      DISTINCT
      RL.IsolateID as isolate_id,
      M.CodonPos as position,
      CASE
        WHEN M.Insertion = 'Yes' THEN 'ins'
        WHEN M.MutAA = '~' THEN 'del'
        WHEN M.MutAA = '*' THEN 'stop'
        ELSE M.MutAA
      END as amino_acid,
      M.MutText as mut_text,
      M.Mixture = 'Yes' as is_mixture
    FROM tblRefLink RL, tblSequences S, _Mutations M
    WHERE
      RL.RefID = ${ref_id} AND
      -- NOT EXISTS (
      --   SELECT 1 FROM tblIsolateFilters IsoF
      --   WHERE
      --     RL.IsolateID = IsoF.IsolateID AND
      --     IsoF.Filter = 'QA'
      -- ) AND
      RL.IsolateID = S.IsolateID AND
      (
        RL.Priority = 1 OR
        NOT EXISTS (
          SELECT 1 FROM tblSurRefs SR, tblRefLink RL2
          WHERE
            SR.RefID != ${ref_id} AND
            SR.RefID = RL2.RefID AND
            RL2.IsolateID = RL.IsolateID AND
            RL2.Priority = 1
        )
      ) AND
      EXISTS (
        SELECT 1 FROM tblIsolates I
        WHERE
          RL.IsolateID = I.IsolateID AND
          I.Type = 'Clinical'
      ) AND
      (
        S.SeqType = 'Consensus' OR
        NOT EXISTS (
          SELECT 1 FROM tblSequences S2 WHERE
            RL.IsolateID = S2.IsolateID AND
            S.SequenceID != S2.SequenceID
        )
      ) AND
      S.SequenceID = M.SequenceID AND
      -- TODO: what to do with mixtures?
      M.Mixture = 'No' AND
      M.MutAA != '.'
    ORDER BY RL.IsolateID, M.CodonPos, M.MutAA
EOF


  if [ ! -s $TMP_ISOMUT.1 ]; then
    echo "Skip empty $TARGET_ISOMUT"
    continue
  fi

  cat $TMP_ISOMUT.1 | python3 -c "
import re
import csv
import sys

reader = csv.reader(sys.stdin)
writer = csv.writer(sys.stdout)

writer.writerow(next(reader))
for row in reader:
  if row[4] == 'true':
    refaa, aas = re.split(r'\d+', row[3])
    for aa in aas:
      if refaa == aa:
        continue
      row[2] = aa
      writer.writerow(row)
  else:
    writer.writerow(row)
" | csvtk cut -f 'isolate_id,position,amino_acid,is_mixture' > $TMP_ISOMUT.2
  
  addbom $TMP_ISOMUT.2
  mv $TMP_ISOMUT.2 $TARGET_ISOMUT
  echo "Create $TARGET_ISOMUT"

done

rm -rf $TMP_ISOMUT_DIR
