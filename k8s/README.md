# Kubernetes manifests (MVP)

Plain, hand-written manifests for the app tier only (`osw-backend`,
`osw-frontend`) -- a starting point, explicitly **not** a full Helm chart
(the original gap-closure plan estimated a full week for that alone; this is
scoped much smaller on purpose). Apply with:

```sh
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml   # copy from secret.yaml.example first -- see that file
kubectl apply -f k8s/backend-deployment.yaml -f k8s/backend-service.yaml
kubectl apply -f k8s/frontend-deployment.yaml -f k8s/frontend-service.yaml
```

## How this relates to `docker-compose.yml`

`docker-compose.yml` (repo root) is the canonical single-host stack:
postgres, redis, neo4j, qdrant, backend, worker (RQ job queue), frontend,
plus an optional `vault` service behind the `advanced` Compose profile, all
in one file. These k8s manifests cover **only the app tier** (backend +
frontend Deployments/Services) -- they assume Postgres/Redis/Neo4j/Qdrant are
already reachable from the cluster some other way (managed cloud services, a
StatefulSet set someone adds later, or the same containers re-hosted
in-cluster). Point `k8s/configmap.yaml`'s `QDRANT_HOST`/`NEO4J_URI` and
`k8s/secret.yaml`'s `DATABASE_URL`/`REDIS_URL`/`NEO4J_PASSWORD` at wherever
those actually run. There is no k8s equivalent of the `worker`/`vault`
services yet -- treat both as compose-only for now.

Both the compose file and these manifests build from the same two
Dockerfiles (`backend/Dockerfile`, `frontend/Dockerfile`), so an image that
works in one works in the other.

## Explicitly NOT included yet

This is an MVP starting point. The following are deliberately left out, not
overlooked -- treat all of them as follow-up work before running this for
real:

- **Ingress** -- no `Ingress` resource exists. Both Services are `ClusterIP`
  only; a browser cannot reach either one without adding an Ingress
  controller + resource (or switching a Service to `LoadBalancer`/`NodePort`
  yourself).
- **HorizontalPodAutoscaler** -- replica counts are static (`2`) in both
  Deployments.
- **PodDisruptionBudget** -- no guaranteed minimum availability during
  voluntary disruptions (node drains, cluster upgrades).
- **Resource requests/limits** -- neither Deployment sets `resources:`.
  Needed before any real scheduling/capacity planning or QoS class matters.
- **Persistent volumes for datastores** -- as noted above, Postgres/Neo4j/
  Redis/Qdrant have no manifests here at all (no `StatefulSet`, no `PVC`).
- **The Slurm SSH key itself** -- `secret.yaml.example` documents a
  `SLURM_SSH_KEY_PATH` key, but no matching Secret volume mount exists to put
  an actual private key file at that path inside the container. Only the
  path string is wired up.
- **gVisor runtime-class / Btrfs CSI** -- `docs/infrastructure/environments_k8s.md`
  describes an intended topology where the OSW Sandbox depends on nodes with
  gVisor KVM `RuntimeClass` support and Btrfs subvolume CoW provisioning via a
  dedicated CSI driver. Nothing here contradicts that document, but nothing
  here implements it either -- both remain aspirational/future work, well
  beyond this MVP's scope. `osw-backend`/`osw-frontend` above run under the
  cluster's default runtime class.

## Multi-replica correctness note

Both Deployments default to `replicas: 2`. The backend is safe to run with
multiple replicas -- request-scoped state lives in Postgres/Neo4j, not
in-process -- **provided `JWT_SECRET` is set** in `secret.yaml` (see the
detailed comment in `secret.yaml.example`). Without it, each pod would mint
and verify JWTs with its own random per-process secret, and a token issued by
one pod would be rejected by another.
