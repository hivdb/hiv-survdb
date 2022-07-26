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
  local tmpfile=$(mktemp)

  cat $1 |
    csvtk cut -f 'sequenceID,pr.qa.problem,rt.qa.problem,in.qa.problem' |
    csvtk mutate2 -n pr_cpr_excluded -e '$2 == "NA" ? "NULL" : ($2 == 0 ? "FALSE" : "TRUE")' |
    csvtk mutate2 -n rt_cpr_excluded -e '$3 == "NA" ? "NULL" : ($3 == 0 ? "FALSE" : "TRUE")' |
    csvtk mutate2 -n in_cpr_excluded -e '$4 == "NA" ? "NULL" : ($4 == 0 ? "FALSE" : "TRUE")' |
    csvtk mutate -f sequenceID -p 'PtID(\d+)\.' -n patient_id |
    csvtk mutate -f sequenceID -p '\.(\d{8})\.(?:PRRT|IN)' -n isolate_date |
    csvtk replace -f isolate_date -p '(\d{4})(\d{2})(\d{2})' -r '$1-$2-$3' > $tmpfile
  cat $tmpfile |
    csvtk cut -f patient_id,isolate_date,pr_cpr_excluded |
    csvtk filter2 -f '$pr_cpr_excluded != "NULL"' |
    csvtk mutate2 -n gene -e '"PR"' |
    csvtk rename -f 'pr_cpr_excluded' -n 'new_cpr_excluded'
  cat $tmpfile |
    csvtk cut -f "patient_id,isolate_date,rt_cpr_excluded" |
    csvtk filter2 -f '$rt_cpr_excluded != "NULL"' |
    csvtk mutate2 -n gene -e '"RT"' |
    csvtk del-header
  cat $tmpfile |
    csvtk cut -f "patient_id,isolate_date,in_cpr_excluded" |
    csvtk filter2 -f '$in_cpr_excluded != "NULL"' |
    csvtk mutate2 -n gene -e '"IN"' |
    csvtk del-header
  rm $tmpfile
}

function unfold_mutations() {
  python3 -c "
import re
import csv
import sys

reader = csv.DictReader(sys.stdin)
writer = csv.writer(sys.stdout)

writer.writerow(['patient_id', 'gene', 'isolate_date', 'mutation', 'position', 'amino_acid', 'is_mixture'])
for row in reader:
  try:
    refaa, pos, aas = re.search(r'^([^\d])(\d+)([^\d\s(]+)', row['mutation']).groups()
  except AttributeError:
    raise AttributeError('Malformed mutation: {!r}'.format(row['mutation']))
  if '_' in aas or aas in ('ins', 'Insertion'):
    aas = 'i'
  elif aas in ('del', 'Deletion', '-'):
    aas = 'd'
  is_mixture = len(aas) > 1
  for aa in aas:
    if refaa == aa:
      continue
    if aa == 'i':
      aa = 'ins'
    elif aa == 'd':
      aa = 'del'
    elif aa == '*':
      aa = 'stop'
    writer.writerow([
      row['patient_id'],
      row['gene'],
      row['isolate_date'],
      '{}:{}{}{}'.format(row['gene'], refaa, pos, aa),
      pos,
      aa,
      int(is_mixture)
    ])
"
}

function read_excluded_surv_mutations() {
  local step1=$(mktemp)
  local step2=$(mktemp)

  cat $1 |
    csvtk cut -f 'sequenceID,pr.SDRMFiltered,rt.SDRMFiltered,in.SDRMFiltered' |
    csvtk mutate -f sequenceID -p 'PtID(\d+)\.' -n patient_id |
    csvtk mutate -f sequenceID -p '\.(\d{8})\.(?:PRRT|IN)' -n isolate_date |
    csvtk replace -f isolate_date -p '(\d{4})(\d{2})(\d{2})' -r '$1-$2-$3' > $step1
  cat $step1 |
    csvtk cut -f 'patient_id,isolate_date,pr.SDRMFiltered' |
    csvtk rename -f 'pr.SDRMFiltered' -n 'mutation' |
    csvtk filter2 -f '$mutation != "NA" && $mutation != "None" && $mutation != ""' |
    csvtk mutate2 -n gene -e '"PR"' |
    csvtk unfold -f 'mutation' -s "; " > $step2
  cat $step1 |
    csvtk cut -f 'patient_id,isolate_date,rt.SDRMFiltered' |
    csvtk rename -f 'rt.SDRMFiltered' -n 'mutation' |
    csvtk filter2 -f '$mutation != "NA" && $mutation != "None" && $mutation != ""' |
    csvtk mutate2 -n gene -e '"RT"' |
    csvtk unfold -f 'mutation' -s "; " |
    csvtk del-header >> $step2
  cat $step1 |
    csvtk cut -f 'patient_id,isolate_date,in.SDRMFiltered' |
    csvtk rename -f 'in.SDRMFiltered' -n 'mutation' |
    csvtk filter2 -f '$mutation != "NA" && $mutation != "None" && $mutation != ""' |
    csvtk mutate2 -n gene -e '"IN"' |
    csvtk unfold -f 'mutation' -s "; " |
    csvtk del-header >> $step2

  cat $step2 | unfold_mutations

  rm $step1 $step2
}

function read_cpr_mutations() {
  local step1=$(mktemp)
  local step2=$(mktemp)

  cat $1 |
    csvtk cut -f 'sequenceID,pr.mutationlist,rt.mutationlist,in.mutationlist' |
    csvtk mutate -f sequenceID -p 'PtID(\d+)\.' -n patient_id |
    csvtk mutate -f sequenceID -p '\.(\d{8})\.(?:PRRT|IN)' -n isolate_date |
    csvtk replace -f isolate_date -p '(\d{4})(\d{2})(\d{2})' -r '$1-$2-$3' > $step1
  cat $step1 |
    csvtk cut -f 'patient_id,isolate_date,pr.mutationlist' |
    csvtk rename -f 'pr.mutationlist' -n 'mutation' |
    csvtk filter2 -f '$mutation != "NA" && $mutation != "None" && $mutation != ""' |
    csvtk mutate2 -n gene -e '"PR"' |
    csvtk unfold -f 'mutation' -s ", " > $step2
  cat $step1 |
    csvtk cut -f 'patient_id,isolate_date,rt.mutationlist' |
    csvtk rename -f 'rt.mutationlist' -n 'mutation' |
    csvtk filter2 -f '$mutation != "NA" && $mutation != "None" && $mutation != ""' |
    csvtk mutate2 -n gene -e '"RT"' |
    csvtk unfold -f 'mutation' -s ", " |
    csvtk del-header >> $step2
  cat $step1 |
    csvtk cut -f 'patient_id,isolate_date,in.mutationlist' |
    csvtk rename -f 'in.mutationlist' -n 'mutation' |
    csvtk filter2 -f '$mutation != "NA" && $mutation != "None" && $mutation != ""' |
    csvtk mutate2 -n gene -e '"IN"' |
    csvtk unfold -f 'mutation' -s ", " |
    csvtk del-header >> $step2

  cat $step2 | unfold_mutations

  rm $step1 $step2
}

function update_isolates() {
  local xlsx="payload/suppl-tables/cpr_results/$2/$1-seqs.xlsx"
  local TARGET_ISOLATES=payload/tables/isolates.d/$1-iso.csv

  if [ -f "$xlsx" ]; then
    local TMP_CPR_ANALYSIS=$(mktemp)

    if [ ! -f $TARGET_ISOLATES ]; then
      echo "Skip $TARGET_ISOLATES"
      return
    fi

    xlsx2csv -n Analysis $xlsx > $TMP_CPR_ANALYSIS

    # =================
    # Update `isolates`
    # =================
    local TMP_CPR_QA=$(mktemp)
    local TMP_ISOLATES=$(mktemp)
    read_cpr_qa $TMP_CPR_ANALYSIS > $TMP_CPR_QA

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

    # ==========================
    # Update `isolate_mutations`
    # ==========================
    if [ -f $TARGET_ISOLATES ]; then
      local TMP_CPR_MUTS=$(mktemp)
      local TARGET_MUTATIONS=payload/tables/isolate_mutations.d/$1-$2-isomuts.csv
      read_cpr_mutations $TMP_CPR_ANALYSIS > $TMP_CPR_MUTS
      csvtk join $TMP_CPR_MUTS $TARGET_ISOLATES -f patient_id,gene,isolate_date --na NULL |
        csvtk cut -f isolate_id,position,amino_acid,is_mixture > $TARGET_MUTATIONS
      rm $TMP_CPR_MUTS
    fi

    # ========================================
    # Update `isolate_excluded_surv_mutations`
    # ========================================
    if [ -f $TARGET_ISOLATES ]; then
      local TMP_EX_SDRMS=$(mktemp)
      local TARGET_EX_SDRMS=payload/tables/isolate_excluded_surv_mutations.d/$1-$2-exsdrms.csv
      read_excluded_surv_mutations $TMP_CPR_ANALYSIS > $TMP_EX_SDRMS
      csvtk join $TMP_EX_SDRMS $TARGET_ISOLATES -f patient_id,gene,isolate_date --na NULL |
        csvtk cut -f isolate_id,mutation,position,amino_acid > $TARGET_EX_SDRMS
      rm $TMP_EX_SDRMS
    fi

  fi
}

mkdir -p payload/tables/isolate_mutations.d
mkdir -p payload/tables/isolate_excluded_surv_mutations.d
rm -f payload/tables/isolate_mutations.d/*.csv
rm -f payload/tables/isolate_excluded_surv_mutations.d/*.csv

tail -n +2 payload/tables/articles.csv | cut -d ',' -f 1 | while read ref_name; do
  lower_ref_name=$(refname_for_file $ref_name)

  update_isolates "$lower_ref_name" PRRT
  update_isolates "$lower_ref_name" IN

  # =================================
  # Merge PRRT/IN `isolate_mutations`
  # =================================
  PRRT_MUTATIONS=payload/tables/isolate_mutations.d/${lower_ref_name}-PRRT-isomuts.csv
  IN_MUTATIONS=payload/tables/isolate_mutations.d/${lower_ref_name}-IN-isomuts.csv
  TARGET_MUTATIONS=payload/tables/isolate_mutations.d/${lower_ref_name}-isomuts.csv
  if [ -f $PRRT_MUTATIONS ]; then
    cp $PRRT_MUTATIONS $TARGET_MUTATIONS.tmp
    if [ -f $IN_MUTATIONS ]; then
      tail -n +2 $IN_MUTATIONS >> $TARGET_MUTATIONS.tmp
    fi
  elif [ -f $IN_MUTATIONS ]; then
    cp $IN_MUTATIONS $TARGET_MUTATIONS.tmp
  fi

  if [ -f $TARGET_MUTATIONS.tmp ]; then
    if [ "$(wc -l $TARGET_MUTATIONS.tmp | awk '{print $1}')" -gt 1 ]; then
      cat $TARGET_MUTATIONS.tmp | csvtk sort -k isolate_id:n,position:n,amino_acid:N | uniq > $TARGET_MUTATIONS
      addbom $TARGET_MUTATIONS
      echo "Update $TARGET_MUTATIONS"
    else
      echo "Skip empty $TARGET_MUTATIONS"
    fi
  else
    echo "Skip empty $TARGET_MUTATIONS"
  fi
  rm -f $PRRT_MUTATIONS $IN_MUTATIONS $TARGET_MUTATIONS.tmp

  # ===============================================
  # Merge PRRT/IN `isolate_excluded_surv_mutations`
  # ===============================================
  PRRT_EX_SDRMS=payload/tables/isolate_excluded_surv_mutations.d/${lower_ref_name}-PRRT-exsdrms.csv
  IN_EX_SDRMS=payload/tables/isolate_excluded_surv_mutations.d/${lower_ref_name}-IN-exsdrms.csv
  TARGET_EX_SDRMS=payload/tables/isolate_excluded_surv_mutations.d/${lower_ref_name}-exsdrms.csv
  if [ -f $PRRT_EX_SDRMS ]; then
    cp $PRRT_EX_SDRMS $TARGET_EX_SDRMS.tmp
    if [ -f $IN_EX_SDRMS ]; then
      tail -n +2 $IN_EX_SDRMS >> $TARGET_EX_SDRMS.tmp
    fi
  elif [ -f $IN_EX_SDRMS ]; then
    cp $IN_EX_SDRMS $TARGET_EX_SDRMS.tmp
  fi

  if [ -f $TARGET_EX_SDRMS.tmp ]; then
    if [ "$(wc -l $TARGET_EX_SDRMS.tmp | awk '{print $1}')" -gt 1 ]; then
      cat $TARGET_EX_SDRMS.tmp | csvtk sort -k isolate_id:n,position:n,amino_acid:N |
        csvtk cut -f isolate_id,mutation | uniq > $TARGET_EX_SDRMS
      addbom $TARGET_EX_SDRMS
      echo "Update $TARGET_EX_SDRMS"
    else
      echo "Skip empty $TARGET_EX_SDRMS"
    fi
  else
    echo "Skip empty $TARGET_EX_SDRMS"
  fi
  rm -f $PRRT_EX_SDRMS $IN_EX_SDRMS $TARGET_EX_SDRMS.tmp
done
