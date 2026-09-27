"""Génère data.json : infra, lignage, orchestration et logique, lus depuis le code.

Rien n'est codé en dur sauf ce que le code ne dit pas (hôte, APIs externes, notes).
Lancé par serve.py à chaque démarrage ; utilisable seul : `uv run python tools/infra_map/build.py`.
"""

import ast
import inspect
import json
import os
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WEBSITE = REPO.parent / "steam-reviews-website"
sys.path.insert(0, str(REPO))

# Valeurs factices : le chargement des définitions exige ces variables, aucune connexion n'est ouverte.
for var in (
    "POSTGRES_HOST",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "IGDB_CLIENT_ID",
    "IGDB_CLIENT_SECRET",
):
    os.environ.setdefault(var, "infra-map")
os.environ.setdefault("POSTGRES_PORT", "5432")

SECRET_HINT = re.compile(r"password|secret|token|key|hash", re.I)

# Ce que le code ne porte pas : endpoints externes et leurs contraintes connues.
EXTERNAL_APIS = {
    "api:appreviews": {
        "label": "Steam /appreviews",
        "url": "https://store.steampowered.com/appreviews/{app_id}",
        "notes": (
            "Reviews d'un jeu, paginées par curseur (100 par page).\n"
            "Limité par IP depuis le 24/09/2026 : seau d'environ 270 requêtes, recharge "
            "~0,96/s, blocage ~4 min 30 après un 429.\n"
            "Appelé via la voie « reviews » du throttle (≥ 1,25 s entre deux requêtes)."
        ),
        "methods": ["get_summary", "get_all_reviews"],
    },
    "api:events": {
        "label": "Steam events",
        "url": "https://store.steampowered.com/events/ajaxgetpartnereventspageable/",
        "notes": "Annonces store (patch notes, actus). Non limité, voie « default » à 0,1 s.",
        "methods": ["get_events"],
    },
    "api:getitems": {
        "label": "Steam GetItems",
        "url": "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/",
        "notes": (
            "Fiches store par lot de 200 ids (URL trop longue au-delà de ~250).\n"
            "include_reviews → summary_filtered.review_count : achats Steam seuls, sans "
            "les clés activées ailleurs. Sert de signal « le jeu a bougé »."
        ),
        "methods": ["get_store_items"],
    },
    "api:igdb": {
        "label": "IGDB dumps",
        "url": "https://api.igdb.com/v4/dumps/{endpoint}",
        "notes": "Dumps CSV signés (S3) : games, external_games, genres, companies, involved_companies, covers. Auth OAuth Twitch.",
        "methods": ["download_dump"],
    },
    "api:discord": {
        "label": "Discord webhook",
        "url": "DISCORD_WEBHOOK_URL",
        "notes": "Alerte à chaque run en échec (discord_run_failure_sensor), 3 essais.",
        "methods": [],
    },
}


def rel(path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO))
    except ValueError:
        return str(path)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def module_constants(source: str) -> list[dict]:
    """Constantes de module en MAJUSCULES : seuils, SQL, tailles de lot."""
    out = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.isupper():
            continue
        comment = []
        lines = source.splitlines()
        i = node.lineno - 2
        while i >= 0 and lines[i].lstrip().startswith("#"):
            comment.insert(0, lines[i].strip("# ").rstrip())
            i -= 1
        out.append(
            {
                "name": target.id,
                "value": ast.get_source_segment(source, node.value),
                "comment": " ".join(comment),
                "line": node.lineno,
            }
        )
    return out


def sql_tables(source: str) -> tuple[set[str], set[str]]:
    reads = set(re.findall(r"\b(?:FROM|JOIN)\s+(raw\.\w+)", source))
    writes = set(
        re.findall(r"\b(?:INSERT INTO|UPDATE|DELETE FROM)\s+(raw\.\w+)", source)
    )
    return reads, writes


# ---------------------------------------------------------------------------
# Postgres : tables raw depuis db/init.sql
# ---------------------------------------------------------------------------
def raw_tables() -> dict[str, dict]:
    sql = read(REPO / "db/init.sql")
    tables = {}
    for m in re.finditer(
        r"CREATE TABLE IF NOT EXISTS (raw\.\w+) \((.*?)\n\)(.*?);", sql, re.S
    ):
        name, body, tail = m.group(1), m.group(2), m.group(3)
        cols = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            cm = re.match(
                r"(\w+)\s+([A-Z][A-Z ]*(?:\[\])?(?:\s*\(\w+\))?)(.*?)(?:--\s*(.*))?$",
                line,
            )
            if cm and cm.group(1).upper() not in ("PRIMARY", "UNIQUE", "CONSTRAINT"):
                cols.append(
                    {
                        "name": cm.group(1),
                        "type": cm.group(2).strip(),
                        "description": cm.group(4) or "",
                    }
                )
        tables[name] = {
            "columns": cols,
            "storage": "columnar" if "columnar" in tail else "heap",
        }
    for m in re.finditer(r"ALTER TABLE (raw\.\w+)(.*?);", sql, re.S):
        for col, typ in re.findall(r"ADD COLUMN IF NOT EXISTS (\w+) (\w+)", m.group(2)):
            tables.setdefault(m.group(1), {"columns": [], "storage": "heap"})[
                "columns"
            ].append(
                {"name": col, "type": typ, "description": "migration (ALTER TABLE)"}
            )
    for name, t in tables.items():
        t["ddl"] = "\n\n".join(
            b.strip() for b in re.split(r"\n(?=-- -+|CREATE|ALTER)", sql) if name in b
        )
    return tables


# ---------------------------------------------------------------------------
# Dagster + dbt
# ---------------------------------------------------------------------------
def load_orchestration():

    from orchestration.definitions import defs
    from orchestration.project import dbt_steam_reviews_project

    manifest = json.loads(Path(dbt_steam_reviews_project.manifest_path).read_text())
    repo = defs.get_repository_def()
    graph = repo.asset_graph

    dbt_nodes = {
        n["name"]: n
        for n in manifest["nodes"].values()
        if n["resource_type"] == "model"
    }
    tests_by_model: dict[str, list[str]] = {}
    for n in manifest["nodes"].values():
        if n["resource_type"] == "test":
            for dep in n["depends_on"]["nodes"]:
                tests_by_model.setdefault(dep.split(".")[-1], []).append(
                    n.get("test_metadata", {}).get("name") or n["name"]
                )
    source_to_table = {
        s["unique_id"]: f"{s['schema']}.{s['identifier']}"
        for s in manifest["sources"].values()
    }

    assets = {}
    for key in graph.get_all_asset_keys():
        node = graph.get(key)
        name = key.to_user_string()
        item = {
            "id": f"asset:{name}",
            "name": name,
            "group": node.group_name,
            "kinds": sorted(node.kinds),
            "deps": sorted(f"asset:{p.to_user_string()}" for p in node.parent_keys),
            "tags": sorted(t for t in node.tags if not t.startswith("dagster/")),
        }
        if name in dbt_nodes:
            m = dbt_nodes[name]
            item.update(
                type="dbt",
                description=m["description"],
                materialized=m["config"]["materialized"],
                relation=f"{m['schema']}.{m['alias']}",
                file=f"dbt/{m['original_file_path']}",
                code=m["raw_code"],
                language="sql",
                columns=[
                    {
                        "name": c["name"],
                        "type": c.get("data_type") or "",
                        "description": c.get("description", ""),
                    }
                    for c in m["columns"].values()
                ],
                tests=sorted(tests_by_model.get(name, [])),
                config={
                    k: v
                    for k, v in m["config"].items()
                    if k
                    in (
                        "materialized",
                        "incremental_strategy",
                        "unique_key",
                        "full_refresh",
                        "on_schema_change",
                        "pre-hook",
                        "post-hook",
                    )
                    and v not in (None, [], {})
                },
                refs=sorted(
                    f"asset:{d.split('.')[-1]}"
                    for d in m["depends_on"]["nodes"]
                    if d.startswith("model.")
                ),
                sources=sorted(
                    f"table:{source_to_table[d]}"
                    for d in m["depends_on"]["nodes"]
                    if d in source_to_table
                ),
                macros=sorted(
                    d.split(".")[-1]
                    for d in m["depends_on"].get("macros", [])
                    if ".steam_reviews." in d
                ),
            )
        else:
            assets_def = defs.get_assets_def(key)
            fn = assets_def.op.compute_fn.decorated_fn
            module = sys.modules[fn.__module__]
            module_src = inspect.getsource(module)
            src, line = inspect.getsourcelines(fn)
            reads, writes = sql_tables(module_src)
            calls = set(
                re.findall(
                    r"\.(get_summary|get_all_reviews|get_events|get_store_items|download_dump)\(",
                    module_src,
                )
            )
            # L'incrémental passe par fetch_first_page du backfill.
            if "fetch_first_page" in module_src:
                calls.add("get_all_reviews")
            item.update(
                type="python",
                description=assets_def.descriptions_by_key.get(key) or "",
                file=rel(inspect.getsourcefile(fn)),
                line=line,
                code="".join(src),
                module_doc=module.__doc__ or "",
                module_code=module_src,
                language="python",
                constants=module_constants(module_src),
                reads=sorted(f"table:{t}" for t in reads),
                writes=sorted(f"table:{t}" for t in writes),
                apis=sorted(
                    a
                    for a, spec in EXTERNAL_APIS.items()
                    if calls & set(spec["methods"])
                ),
                resources=sorted(
                    r for r in assets_def.required_resource_keys if r != "io_manager"
                ),
            )
        assets[item["id"]] = item

    jobs = []
    for job in repo.get_all_jobs():
        if job.name.startswith("__"):
            continue
        jobs.append(
            {
                "id": f"job:{job.name}",
                "name": job.name,
                "description": job.description or "",
                "assets": sorted(
                    f"asset:{k.to_user_string()}"
                    for k in job.asset_layer.selected_asset_keys
                ),
            }
        )
    schedules = [
        {
            "id": f"schedule:{s.name}",
            "name": s.name,
            "cron": s.cron_schedule,
            "timezone": s.execution_timezone or "UTC",
            "job": f"job:{s.job_name}",
            "default_status": str(s.default_status.value),
            "description": s.description or "",
        }
        for s in repo.schedule_defs
    ]
    sensors = [
        {
            "id": f"sensor:{s.name}",
            "name": s.name,
            "description": s.description or "",
            "default_status": str(s.default_status.value),
            "code": inspect.getsource(sys.modules["orchestration.sensors"]),
            "file": "orchestration/sensors.py",
        }
        for s in repo.sensor_defs
    ]
    resources = []
    for name, res in defs.resources.items():
        cls = type(res)
        fields = {}
        for field, info in getattr(cls, "model_fields", {}).items():
            value = getattr(res, field, info.default)
            fields[field] = "•••" if SECRET_HINT.search(field) else repr(value)
        mod = sys.modules.get(cls.__module__)
        resources.append(
            {
                "id": f"resource:{name}",
                "name": name,
                "class": f"{cls.__module__}.{cls.__name__}",
                "doc": (mod.__doc__ if mod and mod.__doc__ else "")
                + "\n"
                + (cls.__doc__ or ""),
                "fields": fields,
                "constants": module_constants(inspect.getsource(mod))
                if mod and cls.__module__.startswith("orchestration")
                else [],
                "code": inspect.getsource(cls)
                if cls.__module__.startswith("orchestration")
                else "",
                "file": rel(inspect.getsourcefile(cls))
                if cls.__module__.startswith("orchestration")
                else "",
            }
        )
    macros = {
        m["name"]: {
            "description": m.get("description", ""),
            "code": m["macro_sql"],
            "file": f"dbt/{m['original_file_path']}",
        }
        for m in manifest["macros"].values()
        if m["package_name"] == "steam_reviews"
    }
    return assets, jobs, schedules, sensors, resources, macros


# ---------------------------------------------------------------------------
# Déploiement : compose, Caddy, Dagster instance, CI/CD
# ---------------------------------------------------------------------------
def deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = (
            deep_merge(out[k], v)
            if isinstance(v, dict) and isinstance(out.get(k), dict)
            else v
        )
    return out


def compose_services() -> dict[str, dict]:
    base = yaml.safe_load(read(REPO / "docker-compose.yml")) or {}
    prod = yaml.safe_load(read(REPO / "docker-compose.prod.yml")) or {}
    services = {}
    for env, doc in (("base", base), ("prod", prod)):
        for name, svc in (doc.get("services") or {}).items():
            merged = deep_merge(services.get(name, {}).get("spec", {}), svc)
            services[name] = {
                "spec": merged,
                "prod_only": name not in (base.get("services") or {}),
            }
    out = {}
    for name, s in services.items():
        spec = s["spec"]
        deps = spec.get("depends_on") or []
        env = spec.get("environment") or {}
        if isinstance(env, dict):
            env = {k: ("•••" if SECRET_HINT.search(k) else v) for k, v in env.items()}
        out[name] = {
            "id": f"svc:{name}",
            "name": name,
            "image": spec.get("image")
            or ("build: " + str((spec.get("build") or {}).get("context", "."))),
            "command": spec.get("command") or spec.get("entrypoint"),
            "ports": [str(p) for p in spec.get("ports") or []],
            "depends_on": sorted(deps if isinstance(deps, list) else deps.keys()),
            "volumes": [
                v if isinstance(v, str) else f"{v.get('source')} → {v.get('target')}"
                for v in spec.get("volumes") or []
            ],
            "environment": env,
            "prod_only": s["prod_only"],
            "yaml": yaml.safe_dump({name: spec}, sort_keys=False, allow_unicode=True),
        }
    return out


def caddy_hosts() -> list[dict]:
    src = read(REPO / "deploy/Caddyfile")
    hosts = []
    for m in re.finditer(r"^([\w.-]+\.[\w.-]+) \{(.*?)^\}", src, re.S | re.M):
        target = re.search(r"reverse_proxy ([\w-]+):(\d+)", m.group(2))
        hosts.append(
            {
                "host": m.group(1),
                "upstream": target.group(1) if target else None,
                "port": target.group(2) if target else None,
                "basicauth": "basicauth" in m.group(2),
                "block": m.group(0),
            }
        )
    return hosts


def workflows() -> list[dict]:
    out = []
    for path in sorted((REPO / ".github/workflows").glob("*.yml")):
        doc = yaml.safe_load(read(path))
        triggers = doc.get(True) or doc.get("on") or {}
        out.append(
            {
                "id": f"ci:{path.stem}",
                "name": doc.get("name", path.stem),
                "file": rel(path),
                "triggers": list(triggers)
                if isinstance(triggers, dict)
                else [triggers],
                "jobs": [
                    {
                        "name": j.get("name", jid),
                        "needs": j.get("needs"),
                        "steps": [
                            s.get("name") or s.get("uses") or s.get("run", "")[:60]
                            for s in j.get("steps", [])
                        ],
                    }
                    for jid, j in doc["jobs"].items()
                ],
                "code": read(path),
            }
        )
    return out


def website_consumers() -> list[dict]:
    """Fichiers du site qui lisent une table de l'entrepôt."""
    if not WEBSITE.exists():
        return []
    out = []
    for path in sorted((WEBSITE / "src").rglob("*.ts*")):
        if ".test." in path.name or path.name == "types.ts":
            continue
        tables = sorted(
            set(
                re.findall(
                    r"\b((?:marts|intermediate|staging|raw)\.[a-z_]+)\b", read(path)
                )
            )
        )
        if tables:
            out.append(
                {
                    "id": f"web:{path.relative_to(WEBSITE)}",
                    "name": str(path.relative_to(WEBSITE / "src")),
                    "tables": tables,
                }
            )
    return out


def main() -> None:
    assets, jobs, schedules, sensors, resources, macros = load_orchestration()
    tables = raw_tables()
    relation_to_asset = {
        a["relation"]: aid for aid, a in assets.items() if a.get("relation")
    }
    web = website_consumers()
    for w in web:
        w["reads"] = sorted(
            {relation_to_asset.get(t, f"table:{t}") for t in w["tables"]}
        )

    data = {
        "generated_from": rel(REPO),
        "assets": assets,
        "tables": {
            f"table:{k}": {"id": f"table:{k}", "name": k, **v}
            for k, v in tables.items()
        },
        "apis": {k: {"id": k, **v} for k, v in EXTERNAL_APIS.items()},
        "jobs": jobs,
        "schedules": schedules,
        "sensors": sensors,
        "resources": resources,
        "macros": macros,
        "services": compose_services(),
        "caddy": caddy_hosts(),
        "dagster_instance": {
            "yaml": read(REPO / "deploy/dagster.yaml"),
            "config": yaml.safe_load(read(REPO / "deploy/dagster.yaml")),
            "workspace": read(REPO / "deploy/workspace.yaml"),
        },
        "dockerfile": read(REPO / "Dockerfile"),
        "workflows": workflows(),
        "website": web,
        "host": {"name": "VPS Hetzner CX33", "ip": "167.235.145.180", "user": "deploy"},
    }
    (HERE / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=str)
    )
    print(
        f"data.json : {len(assets)} assets, {len(data['tables'])} tables raw, {len(jobs)} jobs, "
        f"{len(data['services'])} services, {len(web)} fichiers du site"
    )


if __name__ == "__main__":
    main()
