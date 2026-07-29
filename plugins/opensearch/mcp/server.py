#!/usr/bin/env python3
"""Read-only OpenSearch MCP server for BlazeMeter log investigation (multi-environment).

Reads logs through OpenSearch Dashboards' console proxy (no raw OpenSearch API
port is exposed on the dev host — hitting `<host>/<index>/_search` directly 404s).
Every query is relayed via:

    POST {host}/api/console/proxy?path=<index>/<verb>&method=<HTTP verb>
    Headers: osd-xsrf: true   (NOT kbn-xsrf — this is OpenSearch Dashboards 3.x, not Kibana)
    Auth:    HTTP Basic

Environments: denv, bzdev, ci, staging, prod. denv/bzdev share one host today
(https://opensearch-dev.blazemeter.net) and differ only by index pattern. ci/staging/prod
are NOT wired up yet — no host/credentials configured — and every tool reports a clear
"not configured" error for them rather than guessing or silently returning nothing.

To wire up a new environment, set these env vars in .mcp.json's opensearch-reader env block
(uppercase environment name in the suffix, e.g. STAGING, PROD, CI):
  OPENSEARCH_HOST_<ENV>       Dashboards base URL
  OPENSEARCH_USER_<ENV>       Basic auth username
  OPENSEARCH_PASSWORD_<ENV>   Basic auth password
  OPENSEARCH_INDEX_<ENV>      Index pattern (optional, defaults to logstash-<env>*)

denv/bzdev instead read the unsuffixed OPENSEARCH_HOST/OPENSEARCH_USER/OPENSEARCH_PASSWORD
(kept for backwards compatibility with the original single-host setup).
"""

import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

_LEGACY_HOST = os.environ.get("OPENSEARCH_HOST", "https://opensearch-dev.blazemeter.net").rstrip("/")
_LEGACY_USER = os.environ.get("OPENSEARCH_USER", "")
_LEGACY_PASSWORD = os.environ.get("OPENSEARCH_PASSWORD", "")

ENVIRONMENTS = {
    "denv": {"index_pattern": "logstash-denv*"},
    "bzdev": {
        "index_pattern": "logstash-bzdev*",
        "caveat": "Known issue: bzdev log shipping into this cluster appears stopped since "
                  "2026-07-05 (verified — earliest and latest doc in the index pattern are the "
                  "same date). Expect false negatives for anything after that date; this is an "
                  "upstream log-shipping gap, not a query problem.",
    },
    "ci": {"index_pattern": "logstash-ci*"},
    "staging": {"index_pattern": "logstash-staging*"},
    "prod": {"index_pattern": "logstash-blazemeter*"},
}

mcp = FastMCP("OpenSearch Reader")


def _resolve_environment(environment: str) -> dict:
    """Return {host, auth, index_pattern, caveat} for the given environment, or raise
    a clear, actionable error if that environment has no host/credentials configured."""
    env = environment.strip().lower()
    if env not in ENVIRONMENTS:
        raise ValueError(f"Unknown environment '{environment}'. Use one of: {', '.join(ENVIRONMENTS)}.")

    cfg = ENVIRONMENTS[env]
    if env in ("denv", "bzdev"):
        host, user, password = _LEGACY_HOST, _LEGACY_USER, _LEGACY_PASSWORD
    else:
        suffix = env.upper()
        host = os.environ.get(f"OPENSEARCH_HOST_{suffix}", "").rstrip("/")
        user = os.environ.get(f"OPENSEARCH_USER_{suffix}", "")
        password = os.environ.get(f"OPENSEARCH_PASSWORD_{suffix}", "")

    if not host or not user or not password:
        raise ValueError(
            f"OpenSearch for environment '{env}' is not configured yet — no host/credentials "
            f"wired in. Currently only 'denv' and 'bzdev' are set up (single dev cluster: "
            f"{_LEGACY_HOST}). To add '{env}', set OPENSEARCH_HOST_{env.upper()}/"
            f"OPENSEARCH_USER_{env.upper()}/OPENSEARCH_PASSWORD_{env.upper()} in .mcp.json's "
            f"opensearch-reader env block."
        )

    index_pattern = os.environ.get(f"OPENSEARCH_INDEX_{env.upper()}", cfg["index_pattern"])
    return {"host": host, "auth": (user, password), "index_pattern": index_pattern, "caveat": cfg.get("caveat")}


def _proxy(resolved: dict, path: str, method: str, body: dict | None = None) -> dict:
    """Route a request through OpenSearch Dashboards' console proxy."""
    resp = httpx.post(
        f"{resolved['host']}/api/console/proxy",
        params={"path": path, "method": method},
        headers={"osd-xsrf": "true", "Content-Type": "application/json"},
        auth=resolved["auth"],
        content=json.dumps(body) if body is not None else None,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def ping(environment: str = "denv") -> str:
    """
    Test OpenSearch Dashboards connectivity for a given environment and return cluster status.
    Always call this first for a given environment — if it fails (including "not configured"),
    stop and report that rather than attempting search_logs/list_indices.

    Args:
        environment: 'denv' (default), 'bzdev', 'ci', 'staging', or 'prod'.
    """
    try:
        resolved = _resolve_environment(environment)
        resp = httpx.get(f"{resolved['host']}/api/status", auth=resolved["auth"], timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return json.dumps({
            "status": "connected",
            "environment": environment,
            "cluster_name": data.get("name"),
            "version": data.get("version", {}).get("number"),
            "overall_state": data.get("status", {}).get("overall", {}).get("state"),
        })
    except Exception as e:
        return json.dumps({"status": "error", "environment": environment, "error": str(e)})


@mcp.tool()
def list_indices(environment: str = "denv", index_pattern: str = "") -> str:
    """
    List concrete indices matching the environment's index pattern. Useful to confirm
    log data exists for a given date range before querying it. Note: on the dev cluster
    this currently 403s for the service account (cat APIs may be role-restricted) —
    prefer search_logs with a narrow query to check data presence instead.

    Args:
        environment:   'denv' (default), 'bzdev', 'ci', 'staging', or 'prod'.
        index_pattern: Override the index pattern explicitly.
    """
    try:
        resolved = _resolve_environment(environment)
        pattern = index_pattern or resolved["index_pattern"]
        data = _proxy(resolved, f"_cat/indices/{pattern}?format=json&s=index", "GET")
        return json.dumps({"environment": environment, "index_pattern": pattern, "indices": data}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def search_logs(
    lucene_query: str,
    environment: str = "denv",
    time_from: str = "",
    time_to: str = "",
    size: int = 20,
    index_pattern: str = "",
    source_fields: str = "@timestamp,message,raw_message,channel,host.name",
) -> str:
    """
    Search logs with a Lucene query string — same syntax as the OpenSearch
    Dashboards search bar, e.g.
    masterId:"82747221" AND ("insert_instances_start" OR "stockout_detected").

    Always pass time_from/time_to as UTC ISO8601 (e.g. '2026-07-19T19:10:00.000Z').
    Querying with explicit UTC bounds avoids the local-timezone display mismatch
    that the Dashboards UI time-picker is prone to.

    Lucene gotcha: an unquoted term containing a hyphen (e.g. a denv namespace like
    himanshu-perforce, or host.name:himanshu-perforce*) gets misparsed — query_string
    treats a `-` before part of a term as a NOT operator, so "himanshu-perforce*"
    silently becomes "himanshu AND NOT perforce*" and matches nothing. Always quote
    hyphenated values: host.name:"himanshu-perforce".

    Lucene gotcha #2: a bare/unqualified term (no "field:" prefix) is expanded across
    EVERY dynamically-mapped field in the index. This index has enough distinct field
    shapes (from varied JSON log structures) that 2+ bare terms ANDed together can blow
    past OpenSearch's maxClauseCount (1024), throwing "too_many_nested_clauses" (500).
    Always qualify freeform keyword terms to a specific field — usually message:<word>
    or raw_message:"<phrase>" — instead of leaving them bare.

    Args:
        lucene_query:  Lucene query_string syntax
        environment:   'denv' (default), 'bzdev', 'ci', 'staging', or 'prod' — selects the
                       host and index pattern. ci/staging/prod are not configured yet and
                       will return a clear error until credentials are wired in.
        time_from:     ISO8601 UTC lower bound on @timestamp (optional — omit for no time filter)
        time_to:       ISO8601 UTC upper bound on @timestamp (optional)
        size:          Max hits to return (default 20, capped at 100)
        index_pattern: Override the index pattern explicitly
        source_fields: Comma-separated _source fields to return (default: compact log fields).
                       Pass '*' for the full source document.
    """
    try:
        resolved = _resolve_environment(environment)
        pattern = index_pattern or resolved["index_pattern"]
        size = min(size, 100)

        must: list[dict] = [{"query_string": {"query": lucene_query}}]
        if time_from or time_to:
            range_filter = {}
            if time_from:
                range_filter["gte"] = time_from
            if time_to:
                range_filter["lte"] = time_to
            must.append({"range": {"@timestamp": range_filter}})

        body: dict = {
            "size": size,
            "sort": [{"@timestamp": "asc"}],
            "query": {"bool": {"must": must}},
        }
        if source_fields.strip() != "*":
            body["_source"] = [f.strip() for f in source_fields.split(",") if f.strip()]

        data = _proxy(resolved, f"{pattern}/_search", "GET", body)

        hits = data.get("hits", {})
        total = hits.get("total", {})
        results = [
            {"_index": h.get("_index"), "_id": h.get("_id"), **h.get("_source", {})}
            for h in hits.get("hits", [])
        ]
        result = {
            "environment": environment,
            "index_pattern": pattern,
            "lucene_query": lucene_query,
            "time_from": time_from or None,
            "time_to": time_to or None,
            "total_matches": total.get("value"),
            "returned": len(results),
            "hits": results,
        }
        if resolved.get("caveat"):
            result["caveat"] = resolved["caveat"]
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run()
