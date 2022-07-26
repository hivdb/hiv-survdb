#! /bin/bash

set -e

function refname_for_file() {
  echo "${1,,}" | sed "s/[[:space:]]\+/-/g" | sed "s/['\"]//g"
}

function addbom() {
  unix2dos $1 2> /dev/null
  mv $1 $1.1
  printf '\xEF\xBB\xBF' > $1
  cat $1.1 >> $1
  rm $1.1
}

function read_cpr_qa() {
  step1=$(mktemp)
  step2=$(mktemp)

  xlsx2csv -n Analysis $1 > $step1
  cat $step1 |
    csvtk cut -f "sequenceID,pr.qa.problem,rt.qa.problem,in.qa.problem" |
    csvtk mutate2 -n pr_cpr_excluded -e '$2 == "NA" ? "NULL" : ($2 == 0 ? "FALSE" : "TRUE")' |
    csvtk mutate2 -n rt_cpr_excluded -e '$3 == "NA" ? "NULL" : ($3 == 0 ? "FALSE" : "TRUE")' |
    csvtk mutate2 -n in_cpr_excluded -e '$4 == "NA" ? "NULL" : ($4 == 0 ? "FALSE" : "TRUE")' |
    csvtk mutate -f sequenceID -p 'PtID(\d+)\.' -n patient_id |
    csvtk mutate -f sequenceID -p '\.(\d{8})\.(?:PRRT|IN)' -n isolate_date |
    csvtk replace -f isolate_date -p '(\d{4})(\d{2})(\d{2})' -r '$1-$2-$3' > $step2
  cat $step2 |
    csvtk cut -f patient_id,isolate_date,pr_cpr_excluded |
    csvtk filter2 -f '$pr_cpr_excluded != "NULL"' |
    csvtk mutate2 -n gene -e '"PR"' |
    csvtk rename -f 'pr_cpr_excluded' -n 'new_cpr_excluded'
  cat $step2 |
    csvtk cut -f "patient_id,isolate_date,rt_cpr_excluded" |
    csvtk filter2 -f '$rt_cpr_excluded != "NULL"' |
    csvtk mutate2 -n gene -e '"RT"' |
    csvtk del-header
  cat $step2 |
    csvtk cut -f "patient_id,isolate_date,in_cpr_excluded" |
    csvtk filter2 -f '$in_cpr_excluded != "NULL"' |
    csvtk mutate2 -n gene -e '"IN"' |
    csvtk del-header
  rm $step1 $step2
}

function update_isolates() {
  xlsx="payload/suppl-tables/cpr_results/$2/$1-seqs.xlsx"

  if [ -f "$xlsx" ]; then
    TMP_CPR_QA=$(mktemp)
    TMP_ISOLATES=$(mktemp)
    TARGET_ISOLATES=payload/tables/isolates.d/$1-iso.csv

    if [ ! -f $TARGET_ISOLATES ]; then
      echo "Skip $TARGET_ISOLATES"
      return
    fi

    read_cpr_qa $xlsx > $TMP_CPR_QA

    if [ "$(wc -l $TMP_CPR_QA | awk '{print $1}')" -lt 2 ]; then
      echo "Skip $TARGET_ISOLATES since CPR is empty"
      return
    fi
    csvtk join --left-join $TARGET_ISOLATES $TMP_CPR_QA -f patient_id,gene,isolate_date --na NULL |
      csvtk rename -f 'cpr_excluded' -n 'old_cpr_excluded' |
      csvtk mutate2 -n cpr_excluded -e '$new_cpr_excluded == "NULL" ? $old_cpr_excluded : $new_cpr_excluded' |
      csvtk cut -f 'isolate_id,patient_id,gene,isolate_date,subtype,source,seq_method,country_code,genbank_accn,cpr_excluded,date_entered' > $TMP_ISOLATES
    addbom $TMP_ISOLATES
    cp $TMP_ISOLATES $TARGET_ISOLATES
    echo "Update $TARGET_ISOLATES ($2)"
    rm $TMP_CPR_QA
    rm $TMP_ISOLATES
  fi
}

cat payload/tables/articles.csv | cut -d ',' -f 1 | while read ref_name; do
  lower_ref_name=$(refname_for_file $ref_name)
  update_isolates "$lower_ref_name" PRRT
  update_isolates "$lower_ref_name" IN
done
