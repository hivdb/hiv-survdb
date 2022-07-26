LOIP = 10.77.6.245

.ssh-devnext2n-mysql.pid:
	@echo "Creating SSH tunnel to MySQL service@devnext2n..."
	@echo "The sudo privilege is required:"
	@kill $(shell cat $@ 2>/dev/null) 2>/dev/null || true
	@sudo ifconfig lo0 alias ${LOIP}
	@echo "If this takes too long (≥10 seconds), check if your VPN is on/needs to be reset."
	@AUTOSSH_PIDFILE="$$PWD/$@" \autossh -M $$(($$RANDOM%6400 + 1024)) -NfL ${LOIP}:3306:localhost:3306 devnext2n

network:
	@docker network create -d bridge hiv-survdb-network 2>/dev/null || true

builder:
	@docker build . -t hivdb/hiv-survdb-builder:latest

docker-envfile:
	@test -f docker-envfile || (echo "Config file 'docker-envfile' not found, use 'docker-envfile.example' as a template to create it." && false)

update-builder:
	@docker pull hivdb/hiv-survdb-builder:latest > /dev/null

inspect-builder: update-builder network docker-envfile
	@docker run --rm -it \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
		--network=hiv-survdb-network \
		--volume ~/.aws:/root/.aws:ro \
		--env-file ./docker-envfile \
   		hivdb/hiv-survdb-builder:latest /bin/bash

release-builder:
	@docker push hivdb/hiv-survdb-builder:latest

autofill: update-builder
	@docker run --rm -it \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
   		hivdb/hiv-survdb-builder:latest \
		pipenv run python -m drdb.entry autofill-payload payload/

local-release: update-builder network docker-envfile
	@docker run --rm -it \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
		--network=hiv-survdb-network \
		--volume ~/.aws:/root/.aws:ro \
		--env-file ./docker-envfile \
   		hivdb/hiv-survdb-builder:latest \
		scripts/export-sqlite.sh local

release: update-builder network docker-envfile
	@docker run --rm -it \
		--shm-size=1536m \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
		--network=hiv-survdb-network \
		--volume ~/.aws:/root/.aws:ro \
		--env-file ./docker-envfile \
   		hivdb/hiv-survdb-builder:latest \
		scripts/github-release.sh

pre-release: update-builder network docker-envfile
	@docker run --rm -it \
		--shm-size=1536m \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
		--network=hiv-survdb-network \
		--volume ~/.aws:/root/.aws:ro \
		--env-file ./docker-envfile \
   		hivdb/hiv-survdb-builder:latest \
		scripts/github-release.sh --pre-release

debug-export-sqlite: update-builder network docker-envfile
	@docker run --rm -it \
		--shm-size=1536m \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
		--network=hiv-survdb-network \
		--volume ~/.aws:/root/.aws:ro \
		--env-file ./docker-envfile \
   		hivdb/hiv-survdb-builder:latest \
		scripts/export-sqlite.sh debug

sync-from-hivdb: update-builder docker-envfile .ssh-devnext2n-mysql.pid
	@docker run --rm -it \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
		--env HIVDB_HOST=${LOIP} \
		--env-file ./docker-envfile \
   		hivdb/hiv-survdb-builder:latest \
		scripts/sync-from-hivdb.sh

sync-from-cpr: update-builder
	@docker run --rm -it \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
   		hivdb/hiv-survdb-builder:latest \
		scripts/sync-from-cpr.sh

sync-surv-mutations: update-builder
	@docker run --rm -it \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
   		hivdb/hiv-survdb-builder:latest \
		scripts/sync-surv-mutations.sh

sync-to-s3: update-builder docker-envfile
	@docker run --rm -it \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
		--volume ~/.aws:/root/.aws:ro \
		--env-file ./docker-envfile \
   		hivdb/hiv-survdb-builder:latest \
		scripts/sync-to-s3.sh

payload/sequences: scripts/export-sequences-from-hivdb.sh docker-envfile .ssh-devnext2n-mysql.pid
	@HIVDB_HOST=${LOIP} scripts/export-sequences-from-hivdb.sh payload/sequences

devdb: update-builder network
	@docker run \
		--rm -it \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
		hivdb/hiv-survdb-builder:latest \
		scripts/export-sqls.sh
	$(eval volumes = $(shell docker inspect -f '{{ range .Mounts }}{{ .Name }}{{ end }}' hiv-survdb-devdb))
	@mkdir -p local/sqls
	@docker rm -f hiv-survdb-devdb 2>/dev/null || true
	@docker volume rm $(volumes) 2>/dev/null || true
	@docker run \
		-d --name=hiv-survdb-devdb \
		-e POSTGRES_HOST_AUTH_METHOD=trust \
		-p 127.0.0.1:6547:5432 \
		--network=hiv-survdb-network \
		--volume=$(shell pwd)/postgresql.conf:/etc/postgresql/postgresql.conf \
		--volume=$(shell pwd)/local/sqls:/docker-entrypoint-initdb.d \
		postgres:13.1 \
		-c 'config_file=/etc/postgresql/postgresql.conf'

log-devdb:
	@docker logs -f hiv-survdb-devdb

psql-devdb:
	@docker exec -it hiv-survdb-devdb psql -U postgres

psql-devdb-no-docker:
	@psql -U postgres -h localhost -p 6547

payload/suppl-tables/non_genbank_articles.csv: scripts/find-non-genbank-refs.sh
	@scripts/find-non-genbank-refs.sh "$@"

sync-cpr-urls: update-builder docker-envfile
	@docker run --rm -it \
		--volume=$(shell pwd):/hiv-survdb/ \
		--volume=$(shell dirname $$(pwd))/hiv-survdb-payload:/hiv-survdb-payload \
		--volume ~/.aws:/root/.aws:ro \
		--env-file ./docker-envfile \
   		hivdb/hiv-survdb-builder:latest \
		scripts/sync-cpr-urls.sh


.PHONY: autofill network devdb *-devdb builder *-builder *-sqlite release pre-release debug-* sync-* update-builder new-study import-*
