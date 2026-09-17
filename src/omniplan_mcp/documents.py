import json
from typing import Optional

from omniplan_mcp.server import mcp


@mcp.tool()
async def list_documents() -> str:
    """List all currently open OmniPlan documents.
    Note: task tools now always operate on the current front document.
    """
    from omniplan_mcp.jxa import run_jxa
    jxa_script = """
const app = Application('OmniPlan');
const docs = app.documents();
const result = docs.map(d => {
  let path = null;
  try {
    const rawPath = d.path();
    path = rawPath ? String(rawPath) : null;
  } catch (_) {
    path = null;
  }
  return { name: d.name(), path };
});
JSON.stringify({ ok: true, data: result });
"""
    raw = await run_jxa(jxa_script)
    envelope = json.loads(raw)
    return json.dumps(envelope.get("data", []))


@mcp.tool()
async def save_document() -> str:
    """Save the front OmniPlan document to disk.

    OmniPlan does NOT autosave the front document on idle — verified
    empirically against OmniPlan 4.10.2 by editing a task via MCP and
    polling `document.modified` over a 10-second window: the flag
    stayed true throughout. Explicit save is therefore the only way to
    persist changes to disk between explicit File > Save commands in
    the UI (or quit-time prompts).

    Returns:
        JSON `{"saved": true, "name": "<doc>", "modified_after": false}`
        on success. The `modified_after` field reads back the document's
        dirty flag after the save call to confirm the save took effect.
    """
    from omniplan_mcp.jxa import run_jxa

    jxa_script = """
const app = Application('OmniPlan');
const d = app.documents()[0];
const name = d.name();
let modifiedBefore = null;
try { modifiedBefore = d.modified(); } catch (_) {}
const inner = JSON.parse(app.evaluateJavascript(`(function() {
  try { document.save(); return JSON.stringify({ok:true, data:null}); }
  catch (e) { return JSON.stringify({ok:false, error: e && e.message ? e.message : String(e)}); }
})()`));
if (!inner.ok) {
  JSON.stringify({ ok: false, error: inner.error });
} else {
  // document.save() returns synchronously but the `modified` flag
  // clears asynchronously (~500ms). Poll up to 2s so the returned
  // shape matches what the user would see if they checked themselves.
  let modifiedAfter = null;
  for (let i = 0; i < 20; i++) {
    delay(0.1);
    try { modifiedAfter = d.modified(); } catch (_) { modifiedAfter = null; }
    if (modifiedAfter === false || modifiedAfter === null) break;
  }
  JSON.stringify({
    ok: true,
    data: {
      saved: true,
      name: name,
      modified_before: modifiedBefore,
      modified_after: modifiedAfter,
    },
  });
}
"""
    raw = await run_jxa(jxa_script)
    envelope = json.loads(raw)
    if not envelope.get("ok"):
        raise RuntimeError(str(envelope.get("error", "Save failed.")))
    return json.dumps(envelope["data"])


@mcp.tool()
async def get_project_info() -> str:
    """Return project-level info for the front document.

    Returns:
        JSON `{name, path, start_date, end_date, scenarios}`. `path` comes
        from the JXA SDEF surface (omniJS doesn't expose it). `start_date`
        and `end_date` are the actual scenario's computed bounds (ISO
        YYYY-MM-DD). `scenarios` is `["Actual", ...proj.baselineNames]`
        — the active scenario followed by every baseline scenario name
        defined on the project. The order matches OmniPlan's own
        baseline list; "Actual" is the conventional name for the active
        scenario (`proj.actual`).

    omniJS surface gaps surfaced during implementation (probed
    2026-05-01 against OmniPlan 4.10.2):
      - `proj.startDate` is undefined; date lives on `actual.startDate`.
      - `actual.currency` accepts a write inline but does NOT persist
        across JXA calls (same trap as constraint dates) — omitted from
        the response shape rather than returning a stale value.
    """
    from omniplan_mcp.jxa import run_jxa

    jxa_script = """
const app = Application('OmniPlan');
const docs = app.documents();
if (docs.length === 0) {
  JSON.stringify({ ok: false, error: 'No OmniPlan document is open.' });
} else {
  const d = docs[0];
  let path = null;
  try { const p = d.path(); path = p ? String(p) : null; } catch (_) {}
  const inner = JSON.parse(app.evaluateJavascript(`(function(){
    function fmt(date) {
      if (!date) return null;
      // LOCAL components. OmniPlan materializes day-granularity dates as
      // JS Dates at local midnight (new Date(y, m-1, d)); local getters
      // round-trip the stored calendar date in any timezone, while UTC
      // getters read them one day early east of UTC (e.g. UTC+8). The
      // write side is symmetric: update_project writes via dateFromISO
      // (local-midnight construction) — see tasks.py _fmt_date.
      var y = date.getFullYear();
      var m = ('0' + (date.getMonth() + 1)).slice(-2);
      var dd = ('0' + date.getDate()).slice(-2);
      return y + '-' + m + '-' + dd;
    }
    try {
      const proj = document.project;
      const actual = proj.actual;
      const baselineNames = proj.baselineNames || [];
      const scenarios = ['Actual'];
      for (var i = 0; i < baselineNames.length; i++) {
        scenarios.push(String(baselineNames[i]));
      }
      return JSON.stringify({ok:true, data:{
        name: document.name || '',
        start_date: fmt(actual.startDate),
        end_date: fmt(actual.endDate),
        scenarios: scenarios,
      }});
    } catch (e) { return JSON.stringify({ok:false, error: String(e)}); }
  })()`));
  if (!inner.ok) {
    JSON.stringify({ ok: false, error: inner.error });
  } else {
    inner.data.path = path;
    JSON.stringify({ ok: true, data: inner.data });
  }
}
"""
    raw = await run_jxa(jxa_script)
    envelope = json.loads(raw)
    if not envelope.get("ok"):
        raise RuntimeError(str(envelope.get("error", "get_project_info failed.")))
    return json.dumps(envelope["data"])


@mcp.tool()
async def update_project(
    start_date: Optional[str] = None,
) -> str:
    """Update project-level fields on the front document.

    Args:
        start_date: ISO date for the project's actual start. Maps to
            `document.project.actual.startDate`. Verified persistent
            across JXA calls. Empty string is rejected — clearing the
            project start date isn't supported.

    Returns:
        Post-write `get_project_info` shape.

    Note: `currency` and `working_hours` are NOT supported by this
    tool. omniJS accepts the writes but they don't persist across calls
    (probed live 2026-05-01); shipping them would be a footgun. The
    fields would need a parallel SDEF AppleScript bridge.
    """
    from omniplan_mcp.jxa import run_omnijs

    if start_date is None:
        raise ValueError("update_project: nothing to update — pass at least one field.")
    if start_date == "":
        raise ValueError("update_project: start_date cannot be cleared (only updated).")

    script = f"""
const _proj = document.project;
function dateFromISO(iso) {{
  if (!iso) return null;
  var parts = iso.match(/^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})$/);
  if (!parts) return new Date(iso);
  return new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
}}
_proj.actual.startDate = dateFromISO({json.dumps(start_date)});
return null;
"""
    await run_omnijs(script)
    return await get_project_info()
