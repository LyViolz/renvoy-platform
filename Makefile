CLUSTER ?= renvoy

.PHONY: test lint cluster image deploy smoke up down

test:
	cd app && uv run pytest -q

lint:
	cd app && uv run ruff check . && uv run ruff format --check .

cluster:
	k3d cluster create $(CLUSTER) -p "8080:80@loadbalancer" --wait
	@# Docker Desktop makes k3d write host.docker.internal as the API host, which WSL cannot
	@# reach. The API port is published on localhost too, and the k3s certificate covers 127.0.0.1.
	kubectl config set-cluster k3d-$(CLUSTER) --server="$$(kubectl config view \
		-o jsonpath='{.clusters[?(@.name=="k3d-$(CLUSTER)")].cluster.server}' \
		| sed -E 's#//[^:/]+:#//127.0.0.1:#')"

image:
	docker build -t renvoy-status:dev app
	k3d image import renvoy-status:dev -c $(CLUSTER)

deploy:
	kubectl apply -k deploy/k8s/overlays/local

smoke:
	bash scripts/smoke.sh

# Full local run: cluster, image, deploy, smoke test. Then open http://status.localhost:8080
up: cluster image deploy smoke

down:
	k3d cluster delete $(CLUSTER)
