#! /bin/bash

set -e

VERSION=$1

python3 scripts/db_to_sqlite.py "postgresql://postgres@hiv-survdb-devdb:5432/postgres" /dev/shm/hiv-survdb-$VERSION.db --all
echo "Written build/hiv-survdb-$VERSION.db"
ln -s hiv-survdb-$VERSION.db /dev/shm/hiv-survdb-latest.db
echo "build/hiv-survdb-latest.db -> hiv-survdb-$VERSION.db"

cp /dev/shm/hiv-survdb-$VERSION.db /dev/shm/hiv-survdb-$VERSION-slim.db
./scripts/make-slim-version.sh /dev/shm/hiv-survdb-$VERSION-slim.db
echo "Written build/hiv-survdb-$VERSION-slim.db"

mkdir -p build/
mv /dev/shm/*.db build/
