#! /bin/bash

set -e

curl -sSL https://raw.githubusercontent.com/hivdb/hivfacts/main/data/sdrms_hiv1.json -o /tmp/sdrms_hiv1.json
curl -sSL https://raw.githubusercontent.com/hivdb/hivfacts/main/data/genes_hiv1.json -o /tmp/genes_hiv1.json

python3 <<EOF
import csv
import json

with open('/tmp/sdrms_hiv1.json') as sdrms, open('/tmp/genes_hiv1.json') as genes:
    sdrms = json.load(sdrms)
    genes = json.load(genes)

refaas = {
  gene['abstractGene']: gene['refSequence']
  for gene in genes
  }

with open('payload/tables/surv_mutations.csv', 'w', encoding='utf-8-sig') as fp:
  writer = csv.writer(fp)
  writer.writerow(['mutation', 'gene', 'drug_class', 'position', 'amino_acid'])
  for drug_class, mutations in sdrms.items():
    rows = []
    for mutation in mutations:
      gene = mutation['gene']
      position = mutation['position']
      refaa = refaas[gene][position - 1]
      aas = mutation['aa']
      for aa in aas:
        if aa == '_':
          aa = 'ins'
        elif aa == '-':
          aa = 'del'
        elif aa == '*':
          aa = 'stop'
        muttext = '{}:{}{}{}'.format(gene, refaa, position, aa)
        rows.append([muttext, gene, drug_class, position, aa])
    rows.sort(key=lambda r: (r[3], r[4]))
    writer.writerows(rows)
EOF

echo "Create payload/tables/surv_mutations.csv"
