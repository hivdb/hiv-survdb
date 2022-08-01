#! /bin/bash

set -e

function is_csv_empty() {
  if [ ! -f $1 ]; then
    return 0
  fi
  test "$(wc -l $1 | awk '{print $1}')" -lt 2
}

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
    csvtk mutate -f sequenceID -p '\.PtID(\d+)' -n patient_id |
    csvtk mutate -f sequenceID -p '\.(\d{4}-\d{2}-\d{2})\.PtID' -n isolate_date > $tmpfile
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
    elif aa == 'X':
      # drop X
      continue
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
    csvtk mutate -f sequenceID -p '\.PtID(\d+)' -n patient_id |
    csvtk mutate -f sequenceID -p '\.(\d{4}-\d{2}-\d{2})\.PtID' -n isolate_date > $step1
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
    csvtk mutate -f sequenceID -p '\.PtID(\d+)' -n patient_id |
    csvtk mutate -f sequenceID -p '\.(\d{4}-\d{2}-\d{2})\.PtID' -n isolate_date > $step1
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

  ls payload/suppl-tables/cpr_results/$1-*seq.xlsx 2> /dev/null | while read xlsx; do
    local TMP_CPR_ANALYSIS=$(mktemp)
    local dataset_filename=$(basename $xlsx)
    dataset_filename=${dataset_filename%-seq.xlsx}
    local TARGET_ISOLATES=payload/tables/isolates.d/${dataset_filename}-iso.csv
    csvtk xlsx2csv --sheet-name Analysis $xlsx > $TMP_CPR_ANALYSIS
    if is_csv_empty $TMP_CPR_ANALYSIS; then
      continue

      echo "Remove $TARGET_ISOLATES since CPR is empty"
      rm -f $TARGET_ISOLATES
      return
    fi

    # =================
    # Update `isolates`
    # =================
    local TMP_CPR_QA=$(mktemp)
    local TMP_ISOLATES=$(mktemp)
    local isolate_header='dataset_name,isolate_name,patient_id,gene,isolate_date,subtype,source,seq_method,country_code,genbank_accn,cpr_excluded,date_entered'
    read_cpr_qa $TMP_CPR_ANALYSIS > $TMP_CPR_QA

    if is_csv_empty $TMP_CPR_QA; then
      echo "Remove $TARGET_ISOLATES since CPR is empty"
      rm -f $TARGET_ISOLATES
      return
    fi
    if is_csv_empty $TARGET_ISOLATES; then
      echo $isolate_header > $TARGET_ISOLATES
      echo $isolate_header | sed 's/[^,]*/NULL/g' >> $TARGET_ISOLATES
    fi
    csvtk join --outer-join $TARGET_ISOLATES $TMP_CPR_QA -f patient_id,gene,isolate_date --na NULL |
      csvtk rename -f 'cpr_excluded' -n 'old_cpr_excluded' |
      csvtk mutate2 -n cpr_excluded -e '$new_cpr_excluded == "NULL" ? $old_cpr_excluded : $new_cpr_excluded' |
      csvtk filter2 -f '$cpr_excluded != "NULL"' |
      csvtk cut -f $isolate_header > $TMP_ISOLATES
    addbom $TMP_ISOLATES
    cp $TMP_ISOLATES $TARGET_ISOLATES
    echo "Update $TARGET_ISOLATES"
    rm $TMP_CPR_QA
    rm $TMP_ISOLATES

    # ==========================
    # Update `isolate_mutations`
    # ==========================
    if [ -f $TARGET_ISOLATES ]; then
      local TMP_CPR_MUTS=$(mktemp)
      local TARGET_MUTATIONS=payload/tables/isolate_mutations.d/${dataset_filename}-isomuts.csv
      read_cpr_mutations $TMP_CPR_ANALYSIS > $TMP_CPR_MUTS
      csvtk join $TMP_CPR_MUTS $TARGET_ISOLATES -f patient_id,gene,isolate_date --na NULL |
        csvtk cut -f dataset_name,isolate_name,gene,mutation,position,amino_acid,is_mixture > $TARGET_MUTATIONS
      if is_csv_empty $TARGET_MUTATIONS; then
        echo "Remove $TARGET_MUTATIONS since it is empty"
        rm -f $TARGET_MUTATIONS
      else
        addbom $TARGET_MUTATIONS
      fi
      rm $TMP_CPR_MUTS
    fi

    # ========================================
    # Update `isolate_excluded_surv_mutations`
    # ========================================
    if [ -f $TARGET_ISOLATES ]; then
      local TMP_EX_SDRMS=$(mktemp)
      local TARGET_EX_SDRMS=payload/tables/isolate_excluded_surv_mutations.d/${dataset_filename}-exsdrms.csv
      read_excluded_surv_mutations $TMP_CPR_ANALYSIS > $TMP_EX_SDRMS
      csvtk join $TMP_EX_SDRMS $TARGET_ISOLATES -f patient_id,gene,isolate_date --na NULL |
        csvtk cut -f dataset_name,isolate_name,gene,mutation,position,amino_acid > $TARGET_EX_SDRMS
      if is_csv_empty $TARGET_EX_SDRMS; then
        echo "Remove $TARGET_EX_SDRMS since it is empty"
        rm -f $TARGET_EX_SDRMS
      else
        addbom $TARGET_EX_SDRMS
      fi
      rm $TMP_EX_SDRMS
    fi
  done

}

mkdir -p payload/tables/isolate_mutations.d
mkdir -p payload/tables/isolate_excluded_surv_mutations.d
rm -f payload/tables/isolate_mutations.d/*.csv
rm -f payload/tables/isolate_excluded_surv_mutations.d/*.csv

tail -n +2 payload/tables/articles.csv | cut -d ',' -f 1 | while read ref_name; do
  lower_ref_name=$(refname_for_file $ref_name)

  update_isolates "$lower_ref_name"
done
