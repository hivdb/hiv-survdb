#! /bin/bash

DBML2SQL=$(which dbml2sql)
DOS2UNIX=$(which dos2unix)
TARGET_DIR="/local/sqls"
EXPOSE_DIR="local/sqls"

set -e

cd $(dirname $0)/..

function copy_csv() {
    source_csv=$1
    target_table=$2
    cat <<EOF
COPY "$target_table" FROM STDIN WITH DELIMITER ',' CSV HEADER NULL 'NULL';
$(cat $source_csv | dos2unix)
\.

EOF
}

if [ ! -x "$DBML2SQL" ]; then
    npm install -g @dbml/cli
fi

if [ ! -x "$DOS2UNIX" ]; then
    brew install dos2unix
fi

mkdir -p $TARGET_DIR

dbml2sql --postgres schema.dbml > $TARGET_DIR/01_schema.sql

cat >> $TARGET_DIR/01_schema.sql <<EOF
CREATE EXTENSION btree_gist;
EOF

cat constraints_pre-import.sql >> $TARGET_DIR/01_schema.sql
echo "Written to $TARGET_DIR/01_schema.sql"

copy_csv payload/tables/drug_classes.csv drug_classes >> $TARGET_DIR/02_data_tables.sql
copy_csv payload/tables/journals.csv journals >> $TARGET_DIR/02_data_tables.sql
copy_csv payload/tables/articles.csv articles >> $TARGET_DIR/02_data_tables.sql
copy_csv payload/tables/article_cpr_urls.csv article_cpr_urls >> $TARGET_DIR/02_data_tables.sql
copy_csv payload/tables/article_annotations.csv article_annotations >> $TARGET_DIR/02_data_tables.sql
copy_csv payload/tables/countries.csv countries >> $TARGET_DIR/02_data_tables.sql
copy_csv payload/tables/surv_mutations.csv surv_mutations >> $TARGET_DIR/02_data_tables.sql

ls payload/tables/isolates.d/*.csv | sort -h | while read filepath; do
    copy_csv $filepath isolates >> $TARGET_DIR/02_data_tables.sql
done

ls payload/tables/isolate_mutations.d/*.csv | sort -h | while read filepath; do
    copy_csv $filepath isolate_mutations >> $TARGET_DIR/02_data_tables.sql
done

ls payload/tables/article_isolates.d/*.csv | sort -h | while read filepath; do
    copy_csv $filepath article_isolates >> $TARGET_DIR/02_data_tables.sql
done

pushd payload/
if [ -z "$(git status -s .)" ]
then
    mtime=$(git log -1 --date unix . | \grep '^Date:' | \awk '{print $2}')
else
    # echo 'There are uncommited changes under payload/ repository. Please commit your changes.' 1>&2
    # exit 42
    mtime=$(find . -type f -print0 | xargs -0 stat -c %Y | sort -nr | head -1)
fi
export TZ=0
last_update=$(date -d @${mtime} +%FT%TZ)
popd
echo "INSERT INTO last_update (scope, last_update) VALUES ('global', '${last_update}');" >> $TARGET_DIR/02_data_tables.sql

echo "Written to $TARGET_DIR/02_data_tables.sql"

echo '' > $TARGET_DIR/03_derived_tables.sql
ls derived_tables/*.sql | sort -h | while read filepath; do
    cat $filepath >> $TARGET_DIR/03_derived_tables.sql
done
cat constraints_post-import.sql >> $TARGET_DIR/03_derived_tables.sql
echo "Written to $TARGET_DIR/03_derived_tables.sql"

rm -rf $EXPOSE_DIR 2>/dev/null || true
mkdir -p $(dirname $EXPOSE_DIR)
mv $TARGET_DIR $EXPOSE_DIR
