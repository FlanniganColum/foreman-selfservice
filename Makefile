.PHONY: up down build logs bootstrap sync test tls-info helm-sync-chiklets helm-lint helm-template k8s-render

CHART ?= deploy/helm/foreman-selfservice
HELM_VALUES ?= deploy/helm/examples/values-production.example.yaml
RELEASE ?= foreman-selfservice
NAMESPACE ?= foreman-selfservice

# Development / integration testing
up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f --tail=200

bootstrap:
	docker compose exec web flask --app wsgi:app portal bootstrap

sync:
	docker compose exec web flask --app wsgi:app portal sync-hosts

test:
	docker compose run --rm web pytest -q

tls-info:
	docker compose exec nginx openssl x509 -in /etc/nginx/certs/fullchain.pem -noout -subject -issuer -dates -ext subjectAltName

# Production deployment validation/rendering
helm-sync-chiklets:
	scripts/sync-helm-chiklets.sh

helm-lint:
	helm lint $(CHART) -f $(HELM_VALUES)

helm-template:
	helm template $(RELEASE) $(CHART) -n $(NAMESPACE) -f $(HELM_VALUES)

k8s-render:
	VALUES=$(HELM_VALUES) RELEASE=$(RELEASE) NAMESPACE=$(NAMESPACE) deploy/kubernetes/render.sh
