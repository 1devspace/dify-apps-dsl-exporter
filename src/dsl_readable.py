"""Convert Dify DSL (YAML) workflows into a human-readable Markdown report.

A Dify DSL export is optimised for the Dify editor, not for humans: node IDs are
opaque timestamps, the graph is a flat list of nodes + edges with canvas
coordinates, and variable references look like ``{{#1752536193945.topic#}}``.

This converter turns each DSL into a Markdown document that contains:
  * the app header (name, mode, description),
  * a summary of node types,
  * a Mermaid flowchart of the graph (renders on GitHub / Confluence / VS Code),
  * a node-by-node breakdown with the meaningful config for each node type,
with every opaque node ID rewritten to the node's human title, so a reference
becomes ``{{Topic+subprompt.topic}}``.

Usage:
    python src/dsl_readable.py                      # convert every workflow in
                                                    # DSL_FOLDER_PATH -> ./dify-pelonis-readable
    python src/dsl_readable.py path/to/flow.yml     # convert one file (prints location)
    python src/dsl_readable.py DIR --out OUTDIR      # convert a folder into OUTDIR
"""

import argparse
import glob
import html
import os
import re
from collections import deque

import httpx
import yaml

import confluence

DSL_FOLDER_PATH = os.getenv("DSL_FOLDER_PATH", "./dify-pelonis-workflows").strip()
DEFAULT_OUT = os.getenv("READABLE_FOLDER_PATH", "./dify-pelonis-readable").strip()

# Kroki renders Mermaid -> SVG/PNG so diagrams show up as real images in Confluence
# (which has no native Mermaid support). Point KROKI_URL at a self-hosted instance for
# full privacy: `docker run -p 8000:8000 yuzutech/kroki` then KROKI_URL=http://localhost:8000
KROKI_URL = os.getenv("KROKI_URL", "https://kroki.io").rstrip("/")
KROKI_FORMAT = os.getenv("KROKI_FORMAT", "svg").strip().lower()
KROKI_TIMEOUT = float(os.getenv("KROKI_TIMEOUT", "45"))
_KROKI_CTYPE = {"svg": "image/svg+xml", "png": "image/png"}

# Node types whose children live inside them on the canvas (rendered as subgraphs).
CONTAINER_TYPES = {"iteration", "loop"}

_REF_RE = re.compile(r"\{\{#([^#{}]+?)#\}\}")


# --------------------------------------------------------------------------- #
# Loading & ID resolution
# --------------------------------------------------------------------------- #
def load_dsl(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def graph_of(dsl: dict) -> dict:
    return (dsl.get("workflow", {}) or {}).get("graph", {}) or {}


def node_title(node: dict) -> str:
    data = node.get("data", {}) or {}
    title = (data.get("title") or "").strip()
    ntype = data.get("type", "node")
    if not title:
        if ntype == "iteration-start":
            return "Iteration start"
        if ntype == "loop-start":
            return "Loop start"
        return ntype
    return title


def build_id_index(nodes: list[dict]) -> dict[str, str]:
    """Map each node id -> a readable, unique title."""
    index: dict[str, str] = {}
    seen: dict[str, int] = {}
    for node in nodes:
        nid = str(node.get("id"))
        title = node_title(node)
        if title in seen:
            seen[title] += 1
            title = f"{title} ({seen[title]})"
        else:
            seen[title] = 1
        index[nid] = title
    return index


# --------------------------------------------------------------------------- #
# Reference humanisation
# --------------------------------------------------------------------------- #
def humanize_ref(token: str, id_index: dict[str, str]) -> str:
    """Rewrite '<node-id>.<path>' using the node title; leave sys/env/etc. as-is."""
    node_id, _, path = token.partition(".")
    title = id_index.get(node_id.strip())
    if title:
        return f"{{{{{title}.{path}}}}}" if path else f"{{{{{title}}}}}"
    return f"{{{{{token}}}}}"


def humanize_text(text: str, id_index: dict[str, str]) -> str:
    if not isinstance(text, str):
        return text
    return _REF_RE.sub(lambda m: humanize_ref(m.group(1), id_index), text)


def selector_str(selector, id_index: dict[str, str]) -> str:
    """Turn a value_selector list like ['<id>', 'field'] into 'Title.field'."""
    if not isinstance(selector, (list, tuple)) or not selector:
        return str(selector)
    head = str(selector[0])
    head = id_index.get(head, head)
    rest = ".".join(str(p) for p in selector[1:])
    return f"{head}.{rest}" if rest else head


# --------------------------------------------------------------------------- #
# Mermaid diagram
# --------------------------------------------------------------------------- #
def _mermaid_label(text: str) -> str:
    text = text.replace('"', "'").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > 48:
        text = text[:45] + "..."
    return text


def _shape(mid: str, label: str, ntype: str) -> str:
    label = f'"{label}<br/><i>{ntype}</i>"'
    if ntype in ("start", "end"):
        return f"{mid}([{label}])"
    if ntype == "if-else":
        return f"{mid}{{{label}}}"
    if ntype in ("iteration-start", "loop-start"):
        return f"{mid}(({label}))"
    return f"{mid}[{label}]"


def build_mermaid(nodes: list[dict], edges: list[dict], id_index: dict[str, str]) -> str:
    # Stable, safe mermaid ids.
    mid_of: dict[str, str] = {str(n.get("id")): f"n{i}" for i, n in enumerate(nodes)}
    node_by_id = {str(n.get("id")): n for n in nodes}

    children: dict[str, list[str]] = {}
    top_level: list[str] = []
    for n in nodes:
        nid = str(n.get("id"))
        parent = n.get("parentId")
        if parent and str(parent) in node_by_id:
            children.setdefault(str(parent), []).append(nid)
        else:
            top_level.append(nid)

    lines = ["flowchart TD"]

    def emit_node(nid: str, indent: str) -> None:
        n = node_by_id[nid]
        ntype = (n.get("data", {}) or {}).get("type", "node")
        label = _mermaid_label(node_title(n))
        lines.append(f"{indent}{_shape(mid_of[nid], label, ntype)}")

    for nid in top_level:
        n = node_by_id[nid]
        ntype = (n.get("data", {}) or {}).get("type", "node")
        if ntype in CONTAINER_TYPES and nid in children:
            title = _mermaid_label(node_title(n))
            lines.append(f'    subgraph {mid_of[nid]}["{title} ({ntype})"]')
            for child in children[nid]:
                emit_node(child, "        ")
            lines.append("    end")
        else:
            emit_node(nid, "    ")

    # Edges (drawn after all nodes so subgraph endpoints resolve).
    for e in edges:
        src = mid_of.get(str(e.get("source")))
        dst = mid_of.get(str(e.get("target")))
        if not src or not dst:
            continue
        handle = e.get("sourceHandle")
        if handle and handle not in ("source", "", None):
            label = _mermaid_label(str(handle))
            lines.append(f"    {src} -->|{label}| {dst}")
        else:
            lines.append(f"    {src} --> {dst}")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Node ordering (roughly topological from the start node)
# --------------------------------------------------------------------------- #
def order_nodes(nodes: list[dict], edges: list[dict]) -> list[dict]:
    node_by_id = {str(n.get("id")): n for n in nodes}
    adj: dict[str, list[str]] = {}
    indeg: dict[str, int] = {nid: 0 for nid in node_by_id}
    for e in edges:
        s, t = str(e.get("source")), str(e.get("target"))
        if s in node_by_id and t in node_by_id:
            adj.setdefault(s, []).append(t)
            indeg[t] = indeg.get(t, 0) + 1

    starts = [str(n.get("id")) for n in nodes if (n.get("data", {}) or {}).get("type") == "start"]
    starts += [nid for nid in node_by_id if indeg.get(nid, 0) == 0 and nid not in starts]

    visited: set[str] = set()
    ordered: list[dict] = []
    queue = deque(dict.fromkeys(starts))
    while queue:
        nid = queue.popleft()
        if nid in visited or nid not in node_by_id:
            continue
        visited.add(nid)
        ordered.append(node_by_id[nid])
        for nxt in adj.get(nid, []):
            if nxt not in visited:
                queue.append(nxt)
    for n in nodes:  # append anything unreachable, preserving file order
        if str(n.get("id")) not in visited:
            ordered.append(n)
    return ordered


# --------------------------------------------------------------------------- #
# Document model
#
# Rendering produces a list of "blocks" so the same content can be emitted as
# local Markdown or Confluence storage format (XHTML). Inline text uses a tiny
# subset of Markdown: **bold**, `code`, and [text](url).
# --------------------------------------------------------------------------- #
def b_heading(level: int, text: str) -> dict:
    return {"type": "heading", "level": level, "text": text}


def b_para(text: str) -> dict:
    return {"type": "para", "text": text}


def b_italic(text: str) -> dict:
    return {"type": "italic", "text": text}


def b_quote(text: str) -> dict:
    return {"type": "quote", "text": text}


def b_bullets(items: list[str]) -> dict:
    return {"type": "bullets", "items": items}


def b_table(headers: list[str], rows: list[list[str]]) -> dict:
    return {"type": "table", "headers": headers, "rows": rows}


def b_code(lang: str, text: str) -> dict:
    return {"type": "code", "lang": lang, "text": text}


def b_expand(title: str, lang: str, text: str) -> dict:
    return {"type": "expand", "title": title, "lang": lang, "text": text}


def b_mermaid(text: str) -> dict:
    return {"type": "mermaid", "text": text}


def b_image(filename: str, alt: str = "") -> dict:
    return {"type": "image", "filename": filename, "alt": alt}


def type_summary(nodes: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in nodes:
        t = (n.get("data", {}) or {}).get("type", "node")
        counts[t] = counts.get(t, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# --------------------------------------------------------------------------- #
# Per-node detail blocks
# --------------------------------------------------------------------------- #
def node_detail_blocks(node: dict, id_index: dict[str, str]) -> list[dict]:
    data = node.get("data", {}) or {}
    ntype = data.get("type", "node")
    out: list[dict] = []

    def hz(x):
        return humanize_text(x, id_index)

    desc = (data.get("desc") or "").strip()
    if desc:
        out.append(b_italic(desc))

    if ntype == "start":
        rows = []
        for v in data.get("variables", []) or []:
            rows.append([
                f"`{v.get('variable','')}`", v.get("label", ""),
                v.get("type", ""), "yes" if v.get("required") else "no",
            ])
        if rows:
            out.append(b_table(["Variable", "Label", "Type", "Required"], rows))

    elif ntype == "llm":
        model = data.get("model", {}) or {}
        cp = model.get("completion_params", {}) or {}
        name = cp.get("model_name") or model.get("name") or ""
        out.append(b_para(f"**Model:** `{name}` (provider: `{model.get('provider','')}`, "
                          f"mode: {model.get('mode','')})"))
        ctx = data.get("context", {}) or {}
        if ctx.get("enabled") and ctx.get("variable_selector"):
            out.append(b_para(f"**Context:** `{selector_str(ctx['variable_selector'], id_index)}`"))
        prompts = data.get("prompt_template", []) or []
        if isinstance(prompts, str):
            prompts = [{"role": "prompt", "text": prompts}]
        for p in prompts:
            if isinstance(p, str):
                p = {"role": "prompt", "text": p}
            out.append(b_expand(f"Prompt — {p.get('role','prompt')}", "", hz(p.get("text", ""))))

    elif ntype == "code":
        out.append(b_para(f"**Language:** {data.get('code_language','')}"))
        ins = data.get("variables", []) or []
        if ins:
            mapped = ", ".join(
                f"`{v.get('variable')}` = `{selector_str(v.get('value_selector', []), id_index)}`"
                for v in ins
            )
            out.append(b_para(f"**Inputs:** {mapped}"))
        outs = data.get("outputs", {}) or {}
        if outs:
            out.append(b_para("**Outputs:** "
                             + ", ".join(f"`{k}` ({v.get('type','')})" for k, v in outs.items())))
        code = data.get("code", "")
        if code:
            out.append(b_expand("Code", data.get("code_language", "python"), code))

    elif ntype == "http-request":
        out.append(b_para(f"**{str(data.get('method','')).upper()}** `{hz(data.get('url',''))}`"))
        body = data.get("body", {}) or {}
        bdata = body.get("data")
        if isinstance(bdata, list):
            joined = "\n".join(hz(item.get("value", "")) for item in bdata if item.get("value"))
            if joined:
                out.append(b_expand(f"Body ({body.get('type','')})", "json", joined))

    elif ntype == "if-else":
        items = []
        for case in data.get("cases", []) or []:
            op = case.get("logical_operator", "and")
            conds = []
            for c in case.get("conditions", []) or []:
                var = selector_str(c.get("variable_selector", []), id_index)
                conds.append(f"`{var}` {c.get('comparison_operator','')} `{hz(str(c.get('value','')))}`")
            label = case.get("case_id", case.get("id", ""))
            items.append(f"**{label}:** " + f" {op} ".join(conds))
        if items:
            out.append(b_bullets(items))

    elif ntype == "tool":
        out.append(b_para(
            f"**Tool:** `{data.get('tool_name','')}` "
            f"(provider: `{data.get('provider_name','')}`, type: {data.get('provider_type','')})"
        ))
        params = data.get("tool_parameters", {}) or {}
        if params:
            rows = []
            for k, v in params.items():
                val = v.get("value") if isinstance(v, dict) else v
                rows.append([f"`{k}`", f"`{hz(str(val))}`"])
            out.append(b_table(["Parameter", "Value"], rows))

    elif ntype == "iteration":
        out.append(b_para(f"**Iterates over:** `{selector_str(data.get('iterator_selector', []), id_index)}`"))
        out.append(b_para(f"**Collects:** `{selector_str(data.get('output_selector', []), id_index)}` "
                          f"({data.get('output_type','')})"))
        if data.get("is_parallel"):
            out.append(b_para(f"**Parallel:** up to {data.get('parallel_nums')}"))

    elif ntype == "loop":
        if data.get("loop_count"):
            out.append(b_para(f"**Max iterations:** {data.get('loop_count')}"))
        items = []
        for c in data.get("break_conditions", []) or []:
            var = selector_str(c.get("variable_selector", []), id_index)
            items.append(f"**break when:** `{var}` {c.get('comparison_operator','')} "
                         f"`{hz(str(c.get('value','')))}`")
        if items:
            out.append(b_bullets(items))

    elif ntype == "variable-aggregator":
        srcs = [f"`{selector_str(s, id_index)}`" for s in data.get("variables", []) or []]
        if srcs:
            out.append(b_para(f"**Aggregates:** {', '.join(srcs)} → ({data.get('output_type','')})"))

    elif ntype == "assigner":
        items = []
        for item in data.get("items", []) or []:
            tgt = selector_str(item.get("variable_selector", []), id_index)
            val = item.get("value")
            val_s = selector_str(val, id_index) if isinstance(val, list) else hz(str(val))
            items.append(f"`{tgt}` {item.get('operation','=')} `{val_s}`")
        if items:
            out.append(b_bullets(items))

    elif ntype == "end":
        items = [f"`{o.get('variable','')}` = `{selector_str(o.get('value_selector', []), id_index)}`"
                 for o in data.get("outputs", []) or []]
        if items:
            out.append(b_bullets(items))

    return out


def build_blocks(dsl: dict, source_name: str, include_title: bool = True) -> list[dict]:
    app = dsl.get("app", {}) or {}
    graph = graph_of(dsl)
    nodes = graph.get("nodes", []) or []
    edges = graph.get("edges", []) or []
    id_index = build_id_index(nodes)

    blocks: list[dict] = []
    if include_title:
        blocks.append(b_heading(1, app.get("name") or source_name))

    blocks.append(b_para(
        f"{app.get('icon','')} **Mode:** `{app.get('mode','')}` · "
        f"**DSL version:** {dsl.get('version','')} · **Source:** `{source_name}`"
    ))
    if app.get("description"):
        blocks.append(b_quote(app["description"]))

    counts = type_summary([n for n in nodes
                           if (n.get("data", {}) or {}).get("type") != "iteration-start"])
    blocks.append(b_heading(2, "Overview"))
    overview = [f"**Nodes:** {len(nodes)} · **Edges:** {len(edges)}",
                "**Node types:** " + ", ".join(f"{t} ×{c}" for t, c in counts.items())]
    env_vars = (dsl.get("workflow", {}) or {}).get("environment_variables", []) or []
    conv_vars = (dsl.get("workflow", {}) or {}).get("conversation_variables", []) or []
    if env_vars:
        overview.append("**Environment variables:** "
                        + ", ".join(f"`{v.get('name', v)}`" for v in env_vars))
    if conv_vars:
        overview.append("**Conversation variables:** "
                        + ", ".join(f"`{v.get('name', v)}`" for v in conv_vars))
    blocks.append(b_bullets(overview))

    blocks.append(b_heading(2, "Flow"))
    if nodes:
        blocks.append(b_mermaid(build_mermaid(nodes, edges, id_index)))
    else:
        blocks.append(b_italic("No nodes."))

    blocks.append(b_heading(2, "Nodes"))
    skip = {"iteration-start", "loop-start"}
    for node in order_nodes(nodes, edges):
        ntype = (node.get("data", {}) or {}).get("type", "node")
        if ntype in skip:
            continue
        title = id_index.get(str(node.get("id")), node_title(node))
        blocks.append(b_heading(3, f"{title}  `{ntype}`"))
        details = node_detail_blocks(node, id_index)
        blocks.extend(details if details else [b_italic("(no extra configuration)")])

    return blocks


# --------------------------------------------------------------------------- #
# Markdown emitter
# --------------------------------------------------------------------------- #
def blocks_to_markdown(blocks: list[dict]) -> str:
    out: list[str] = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            out.append("#" * b["level"] + " " + b["text"])
        elif t == "para":
            out.append(b["text"])
        elif t == "italic":
            out.append(f"_{b['text']}_")
        elif t == "quote":
            out.append("> " + "\n> ".join(b["text"].splitlines()))
        elif t == "bullets":
            out.append("\n".join(f"- {i}" for i in b["items"]))
        elif t == "table":
            out.append("| " + " | ".join(b["headers"]) + " |")
            out.append("| " + " | ".join("---" for _ in b["headers"]) + " |")
            for row in b["rows"]:
                out.append("| " + " | ".join(str(c) for c in row) + " |")
        elif t == "code":
            out.append(f"```{b['lang']}\n{b['text']}\n```")
        elif t == "expand":
            out.append(f"<details><summary>{b['title']}</summary>\n\n"
                       f"```{b['lang']}\n{b['text']}\n```\n\n</details>")
        elif t == "mermaid":
            out.append(f"```mermaid\n{b['text']}\n```")
        elif t == "image":
            out.append(f"![{b.get('alt','')}]({b['filename']})")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Confluence storage emitter
# --------------------------------------------------------------------------- #
_INLINE_RE = re.compile(r"(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)]+\))")


def _inline_to_storage(text: str) -> str:
    """Convert a tiny Markdown subset (**bold**, `code`, [t](u)) to storage XHTML."""
    out: list[str] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append(html.escape(text[pos:m.start()]))
        token = m.group(0)
        if token.startswith("`"):
            out.append(f"<code>{html.escape(token[1:-1])}</code>")
        elif token.startswith("**"):
            out.append(f"<strong>{html.escape(token[2:-2])}</strong>")
        else:  # link
            lm = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token)
            label, url = lm.group(1), lm.group(2)
            out.append(f'<a href="{html.escape(url)}">{html.escape(label)}</a>')
        pos = m.end()
    if pos < len(text):
        out.append(html.escape(text[pos:]))
    return "".join(out)


def _cdata(text: str) -> str:
    return text.replace("]]>", "]]]]><![CDATA[>")


def _code_macro(text: str, lang: str = "") -> str:
    lang = {"python3": "python", "": "text"}.get(lang, lang)
    param = f'<ac:parameter ac:name="language">{html.escape(lang)}</ac:parameter>' if lang else ""
    return (
        '<ac:structured-macro ac:name="code" ac:schema-version="1">'
        f"{param}"
        f"<ac:plain-text-body><![CDATA[{_cdata(text)}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )


def blocks_to_storage(blocks: list[dict]) -> str:
    out: list[str] = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            lvl = min(max(b["level"], 1), 6)
            out.append(f"<h{lvl}>{_inline_to_storage(b['text'])}</h{lvl}>")
        elif t == "para":
            out.append(f"<p>{_inline_to_storage(b['text'])}</p>")
        elif t == "italic":
            out.append(f"<p><em>{_inline_to_storage(b['text'])}</em></p>")
        elif t == "quote":
            body = "".join(f"<p>{_inline_to_storage(line)}</p>" for line in b["text"].splitlines() if line)
            out.append(f"<blockquote>{body}</blockquote>")
        elif t == "bullets":
            items = "".join(f"<li>{_inline_to_storage(i)}</li>" for i in b["items"])
            out.append(f"<ul>{items}</ul>")
        elif t == "table":
            head = "".join(f"<th><p>{_inline_to_storage(h)}</p></th>" for h in b["headers"])
            rows = "".join(
                "<tr>" + "".join(f"<td><p>{_inline_to_storage(str(c))}</p></td>" for c in row) + "</tr>"
                for row in b["rows"]
            )
            out.append(f"<table><tbody><tr>{head}</tr>{rows}</tbody></table>")
        elif t == "code":
            out.append(_code_macro(b["text"], b["lang"]))
        elif t == "expand":
            out.append(
                '<ac:structured-macro ac:name="expand" ac:schema-version="1">'
                f'<ac:parameter ac:name="title">{html.escape(b["title"])}</ac:parameter>'
                f"<ac:rich-text-body>{_code_macro(b['text'], b['lang'])}</ac:rich-text-body>"
                "</ac:structured-macro>"
            )
        elif t == "mermaid":
            # No guaranteed Mermaid macro in Confluence; show the diagram source as code.
            out.append("<p><em>Mermaid flow diagram (paste into a Mermaid viewer to render):</em></p>")
            out.append(_code_macro(b["text"], "text"))
        elif t == "image":
            out.append(confluence.image_macro(b["filename"]))
    return "".join(out)


# --------------------------------------------------------------------------- #
# Driver helpers
# --------------------------------------------------------------------------- #
def collect_inputs(inputs: list[str]) -> list[str]:
    files: list[str] = []
    for item in inputs:
        if os.path.isdir(item):
            files.extend(sorted(glob.glob(os.path.join(item, "*.yml"))))
            files.extend(sorted(glob.glob(os.path.join(item, "*.yaml"))))
        elif os.path.isfile(item):
            files.append(item)
        else:
            print(f"  ! skipping (not found): {item}")
    return files


def _workflow_info(dsl: dict, base: str, link: str) -> dict:
    app = dsl.get("app", {}) or {}
    nodes = graph_of(dsl).get("nodes", []) or []
    return {
        "name": app.get("name") or base,
        "mode": app.get("mode", ""),
        "nodes": len(nodes),
        "types": type_summary([n for n in nodes
                               if (n.get("data", {}) or {}).get("type") != "iteration-start"]),
        "link": link,
    }


# --------------------------------------------------------------------------- #
# Local Markdown output
# --------------------------------------------------------------------------- #
def run_local(files: list[str], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    print(f"Converting {len(files)} workflow(s) -> {out_dir}")
    entries: list[dict] = []
    for path in files:
        try:
            dsl = load_dsl(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! failed to parse {path}: {exc}")
            continue
        base = os.path.splitext(os.path.basename(path))[0]
        blocks = build_blocks(dsl, os.path.basename(path), include_title=True)
        out_name = base + ".md"
        with open(os.path.join(out_dir, out_name), "w", encoding="utf-8") as fh:
            fh.write(blocks_to_markdown(blocks))
        entries.append(_workflow_info(dsl, base, out_name))
        print(f"  + {out_name}")

    lines = ["# Pelonis Dify Workflows — Readable Index", "",
             f"{len(entries)} workflow(s). Generated from DSL exports.", "",
             "| Workflow | Mode | Nodes | Top node types |", "| --- | --- | --- | --- |"]
    for e in sorted(entries, key=lambda x: x["name"].lower()):
        top = ", ".join(f"{t} ×{c}" for t, c in list(e["types"].items())[:4])
        lines.append(f"| [{e['name']}]({e['link']}) | {e['mode']} | {e['nodes']} | {top} |")
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Done. {len(entries)} report(s) + README.md index in {out_dir}")


# --------------------------------------------------------------------------- #
# Confluence output
# --------------------------------------------------------------------------- #
def _unique_title(name: str, base: str, used: set[str]) -> str:
    title = name.strip() or base
    if title in used:
        title = f"{title} [{base}]"
    suffix = 2
    while title in used:
        title = f"{name} [{base}] ({suffix})"
        suffix += 1
    used.add(title)
    return title


def render_kroki(client: httpx.Client, mermaid_text: str, fmt: str = KROKI_FORMAT) -> bytes:
    """Render Mermaid text to an image via a Kroki server."""
    resp = client.post(
        f"{KROKI_URL}/mermaid/{fmt}",
        content=mermaid_text.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        timeout=KROKI_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.content


def _mermaid_to_images(
    client: httpx.Client, blocks: list[dict], fmt: str
) -> tuple[list[dict], list[tuple[str, bytes, str]]]:
    """Replace mermaid blocks with image blocks; return (blocks, uploads).

    Each upload is (filename, content_bytes, content_type). On render failure the
    original mermaid code block is kept so nothing is lost."""
    new_blocks: list[dict] = []
    uploads: list[tuple[str, bytes, str]] = []
    idx = 0
    ctype = _KROKI_CTYPE.get(fmt, "image/svg+xml")
    for b in blocks:
        if b["type"] != "mermaid":
            new_blocks.append(b)
            continue
        idx += 1
        filename = f"flow.{fmt}" if idx == 1 else f"flow-{idx}.{fmt}"
        try:
            data = render_kroki(client, b["text"], fmt)
            uploads.append((filename, data, ctype))
            new_blocks.append(b_image(filename, "Workflow flow diagram"))
            new_blocks.append(b_expand("Diagram source (Mermaid)", "text", b["text"]))
        except Exception as exc:  # noqa: BLE001
            print(f"    ! diagram render failed ({exc}); keeping Mermaid source")
            new_blocks.append(b)
    return new_blocks, uploads


def _page_url(space_key: str, page_id: str, webui: str | None = None) -> str:
    """Build the browser URL for a Confluence page."""
    base = confluence.CONFLUENCE_BASE_URL
    if webui:
        return base + webui
    return f"{base}/spaces/{space_key}/pages/{page_id}"


def _write_links_file(out_dir: str, entries: list[dict], index_url: str | None) -> str:
    """Write a Markdown table of workflow -> Confluence page URL."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "confluence_links.md")
    lines = ["# Confluence page links", ""]
    if index_url:
        lines += [f"**Index:** [{index_url}]({index_url})", ""]
    lines += ["| Workflow | Page |", "| --- | --- |"]
    for e in sorted(entries, key=lambda x: x["title"].lower()):
        lines.append(f"| {e['title']} | [{e['url']}]({e['url']}) |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


INDEX_TITLE = "Dify Workflows — Index"


def _dify_app_map() -> dict[str, dict]:
    """Best-effort {workflow name: {"url", "id"}}, for unambiguous names only.

    Requires reaching the Dify console (VPN/Tailnet). Returns {} if unreachable so
    Confluence publishing still works without the live links / id-based linking.
    """
    import asyncio
    from collections import Counter

    import dify_api
    import sync_tracker

    async def _go():
        async with httpx.AsyncClient(timeout=60) as c:
            token = await dify_api.login_and_get_token(c)
            return await dify_api.get_app_details(token, c)

    try:
        apps = asyncio.run(_go())
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not reach Dify for workflow links ({exc}); skipping 'Open in Dify' links")
        return {}
    counts = Counter(a.get("name") for a in apps if a.get("name"))
    return {
        a["name"]: {"url": sync_tracker.workflow_url(a["id"]), "id": a["id"]}
        for a in apps
        if a.get("name") and a.get("id") and counts[a["name"]] == 1
    }


def _ensure_index_page(client, space_id, parent_id, space_key) -> tuple[str, str]:
    """Find or create the index page (under the folder). Returns (page_id, url)."""
    for c in confluence.list_folder_children(client, parent_id):
        if c.get("type") == "page" and c["title"] == INDEX_TITLE:
            return c["id"], _page_url(space_key, c["id"])
    res = confluence.create_page(client, space_id, parent_id, INDEX_TITLE,
                                 "<p>Building index…</p>")
    return res["id"], _page_url(space_key, res["id"], (res.get("_links", {}) or {}).get("webui"))


def _all_doc_pages(client, parent_id, index_pid) -> dict[str, str]:
    """Every workflow doc page in the folder subtree, keyed by title -> id.

    Looks under both the folder (legacy layout) and the index page (current layout),
    so the index lists everything even after a single-workflow run.
    """
    docs = {c["title"]: c["id"] for c in confluence.list_folder_children(client, parent_id)
            if c.get("type") == "page" and c["title"] != INDEX_TITLE}
    for c in confluence.list_page_children(client, index_pid):
        if c["title"] != INDEX_TITLE:
            docs[c["title"]] = c["id"]
    return docs


def run_confluence(files: list[str], parent_id: str, space_key: str, out_dir: str,
                   diagrams: str = "image") -> list[dict]:
    with httpx.Client(timeout=60) as client:
        space_id = confluence.get_space_id(client, space_key)
        index_pid, index_url = _ensure_index_page(client, space_id, parent_id, space_key)
        existing = _all_doc_pages(client, parent_id, index_pid)
        print(f"Space '{space_key}' (id {space_id}), folder {parent_id}: "
              f"index page {index_pid}, {len(existing)} existing doc page(s).")

        app_map = _dify_app_map()
        # Map Dify app id -> existing doc page id (rename-safe linking via labels).
        existing_by_app: dict[str, str] = {}
        try:
            for p in confluence.search_by_label(client, confluence.DOC_LABEL):
                appid = confluence.app_id_from_labels(p.get("labels", set()))
                if appid:
                    existing_by_app[appid] = p["id"]
        except httpx.HTTPError as exc:
            print(f"  ! could not read doc labels ({exc}); falling back to title matching")

        used: set[str] = set()
        entries: list[dict] = []
        for path in files:
            try:
                dsl = load_dsl(path)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! failed to parse {path}: {exc}")
                continue
            base = os.path.splitext(os.path.basename(path))[0]
            app = dsl.get("app", {}) or {}
            wf_name = app.get("name") or base
            title = _unique_title(wf_name, base, used)
            blocks = build_blocks(dsl, os.path.basename(path), include_title=False)
            app_info = app_map.get(wf_name) or {}
            app_id = app_info.get("id")
            dify_url = app_info.get("url")
            if dify_url:
                blocks.insert(1, b_para(f"**Workflow:** [Open in Dify]({dify_url})"))

            uploads: list[tuple[str, bytes, str]] = []
            if diagrams == "image":
                blocks, uploads = _mermaid_to_images(client, blocks, KROKI_FORMAT)
            storage = blocks_to_storage(blocks)

            try:
                # Prefer matching the existing page by Dify app id (survives a
                # rename); fall back to the title for legacy/unlabelled pages.
                pid = (app_id and existing_by_app.get(app_id)) or existing.get(title)
                if pid:
                    page = confluence.get_page(client, pid)
                    res = confluence.update_page(client, pid, title, storage, page["version"],
                                                 "Update from DSL readable converter",
                                                 parent_id=index_pid)
                    action = "renamed" if page.get("title") != title else "updated"
                else:
                    res = confluence.create_page(client, space_id, index_pid, title, storage)
                    pid = res["id"]
                    action = "created"
                # Stamp labels so future runs/links find this page by app id.
                labels = [confluence.DOC_LABEL]
                if app_id:
                    labels.append(confluence.app_label(app_id))
                    existing_by_app[app_id] = pid
                try:
                    confluence.add_labels(client, pid, labels)
                except httpx.HTTPError as exc:
                    print(f"    ! could not label {title} ({exc})")
                for filename, data, ctype in uploads:
                    confluence.upload_attachment(client, pid, filename, data, ctype)
            except httpx.HTTPError as exc:
                resp = getattr(exc, "response", None)
                detail = f"{resp.status_code} {resp.text[:160]}" if resp is not None else type(exc).__name__
                print(f"  ! {title}: {detail} (skipped; re-run to retry)")
                continue
            url = _page_url(space_key, pid, (res.get("_links", {}) or {}).get("webui"))
            entries.append(_workflow_info(dsl, base, pid) | {"title": title, "url": url})
            print(f"  {action}: {title} -> {url}{' +diagram' if uploads else ''}")

        # Rebuild the index from EVERY doc page (not just this run) so partial runs
        # never shrink it.
        all_docs = _all_doc_pages(client, parent_id, index_pid)
        _write_index_body(client, index_pid, all_docs, entries)
        links_path = _write_links_file(out_dir, entries, index_url)
        print(f"Done. {len(entries)} page(s) under index {index_pid} (folder {parent_id}).")
        print(f"Index: {index_url}")
        print(f"Links written to {links_path}")
        return entries


def _write_index_body(client, index_pid, all_docs: dict[str, str], entries: list[dict]) -> None:
    by_title = {e["title"]: e for e in entries}
    rows = []
    for title in sorted(all_docs, key=str.lower):
        link = (f'<ac:link><ri:page ri:content-title="{html.escape(title)}" />'
                f'<ac:link-body>{html.escape(title)}</ac:link-body></ac:link>')
        e = by_title.get(title)
        if e:
            top = ", ".join(f"{t} ×{c}" for t, c in list(e["types"].items())[:4])
            mode, nodes = html.escape(e["mode"]), e["nodes"]
        else:
            top, mode, nodes = "", "", ""
        rows.append(f"<tr><td><p>{link}</p></td><td><p>{mode}</p></td>"
                    f"<td><p>{nodes}</p></td><td><p>{html.escape(top)}</p></td></tr>")
    body = (
        f"<p>{len(all_docs)} workflow(s), generated from Dify DSL exports.</p>"
        "<table><tbody><tr><th><p>Workflow</p></th><th><p>Mode</p></th>"
        "<th><p>Nodes</p></th><th><p>Top node types</p></th></tr>"
        + "".join(rows) + "</tbody></table>"
    )
    try:
        page = confluence.get_page(client, index_pid)
        confluence.update_page(client, index_pid, INDEX_TITLE, body, page["version"],
                               "Update index from DSL readable converter")
        print(f"  index: {INDEX_TITLE} ({len(all_docs)} links)")
    except httpx.HTTPError as exc:
        resp = getattr(exc, "response", None)
        detail = f"{resp.status_code} {resp.text[:160]}" if resp is not None else type(exc).__name__
        print(f"  ! index page: {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Dify DSL workflows into readable Markdown or Confluence pages."
    )
    parser.add_argument("inputs", nargs="*", help="DSL files or folders (default: DSL_FOLDER_PATH).")
    parser.add_argument("--output", choices=["local", "confluence"], default="local",
                        help="local (Markdown files, default) or confluence (create/update pages).")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"Output folder for local mode (default: {DEFAULT_OUT}).")
    parser.add_argument("--parent-id", default=os.getenv("CONFLUENCE_DOCS_PARENT_ID", "423952430"),
                        help="Confluence parent folder/page id for confluence mode.")
    parser.add_argument("--space", default=os.getenv("CONFLUENCE_DOCS_SPACE", "SIC"),
                        help="Confluence space key for confluence mode (default: SIC).")
    parser.add_argument("--diagrams", choices=["image", "code"], default="image",
                        help="confluence mode: render diagrams as images via Kroki (default) "
                             "or keep the raw Mermaid source as a code block.")
    args = parser.parse_args()

    inputs = args.inputs or [DSL_FOLDER_PATH]
    files = collect_inputs(inputs)
    if not files:
        print("No DSL files found.")
        return

    if args.output == "confluence":
        run_confluence(files, args.parent_id, args.space, args.out, args.diagrams)
    else:
        run_local(files, args.out)


if __name__ == "__main__":
    main()
