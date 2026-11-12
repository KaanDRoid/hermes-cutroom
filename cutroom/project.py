"""Versioned local projects and exact-plan review receipts.

Receipts prevent accidental stale-plan renders, not malicious local code.
"""

import hashlib
import html
import json
import os
import shlex
import uuid
from pathlib import Path

from .plan import validate_plan


def file_digest(path):
    path = Path(path).expanduser()
    if str(path).startswith(("//", "\\\\")):
        raise ValueError("Network shares are not supported")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def plan_digest(plan):
    validate_plan(plan)
    return hashlib.sha256(
        json.dumps(
            plan, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _read(path):
    path = Path(path).expanduser().resolve(strict=True)
    if path.stat().st_size > 1_000_000:
        raise ValueError("Plan exceeds 1 MB")
    plan = json.loads(path.read_text(encoding="utf-8"))
    validate_plan(plan)
    return path, plan


def save_draft(plan, directory, expected_source_sha256=None):
    validate_plan(plan)
    plan = dict(
        plan, source=str(Path(plan["source"]).expanduser().resolve(strict=True))
    )
    actual_digest = file_digest(plan["source"])
    if expected_source_sha256 is not None and actual_digest != expected_source_sha256:
        raise PermissionError("Source changed during analysis; create a new draft")
    plan["source_sha256"] = actual_digest
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "plan.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(plan, stream, indent=2, allow_nan=False)
    write_review(path)
    return path


REVIEW_RECEIPT = ".review.sha256"
LEGACY_REVIEW_HEADER = b'<!doctype html><html lang="en"><meta charset="utf-8">'


def _replace(target, data):
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_review(review, document):
    """Write review.html, overwriting only a page this module wrote itself."""
    receipt = review.with_name(REVIEW_RECEIPT)
    for path in (review, receipt):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise FileExistsError(f"Refusing to replace a link or directory: {path}")
    current = None
    if review.exists():
        page = review.read_bytes()
        current = hashlib.sha256(page).hexdigest()
        if receipt.exists():
            known = receipt.read_text(encoding="ascii").split()
        else:
            # Reviews written before receipts existed carry Cutroom's own header.
            known = [current] if page.startswith(LEGACY_REVIEW_HEADER) else []
        if current not in known:
            raise FileExistsError(
                f"{review} was not created by Cutroom (or was edited); "
                "refusing to overwrite it"
            )
    data = document.encode("utf-8")
    new = hashlib.sha256(data).hexdigest()
    # Record both pages while swapping so an interruption never locks the review.
    _replace(receipt, " ".join(filter(None, (current, new))).encode("ascii"))
    _replace(review, data)
    _replace(receipt, new.encode("ascii"))


def write_review(path):
    path, plan = _read(path)
    digest = plan_digest(plan)
    duration = sum(s["end"] - s["start"] for s in plan["segments"])
    rows = "".join(
        f"<tr><td>{i + 1}</td><td>{s['start']:.3f}s</td>"
        f"<td>{s['end']:.3f}s</td><td>{s['end'] - s['start']:.3f}s</td></tr>"
        for i, s in enumerate(plan["segments"])
    )
    bars = "".join(
        f'<span title="Keep {s["start"]:.3f}–{s["end"]:.3f}s" '
        f'style="left:{100 * s["start"] / plan["source_duration"]:.5f}%;'
        f'width:{100 * (s["end"] - s["start"]) / plan["source_duration"]:.5f}%"></span>'
        for s in plan["segments"]
    )
    title = html.escape(Path(plan["source"]).name)
    source_uri = html.escape(Path(plan["source"]).as_uri(), quote=True)
    command = html.escape(
        f"python -m cutroom approve {shlex.quote(str(path))} --digest {digest}"
    )
    powershell_path = "'" + str(path).replace("'", "''") + "'"
    powershell_command = html.escape(
        f"python -m cutroom approve {powershell_path} --digest {digest}"
    )
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; media-src file:;">
<title>Cutroom · Review</title><style>
body{{font:16px system-ui;background:#111318;color:#eff0f4;margin:0;padding:32px;max-width:960px}}
h1{{margin-bottom:4px}}p,small{{color:#afb5c1}}video{{width:100%;max-height:400px;background:#000;border-radius:12px}}
.timeline{{position:relative;height:28px;background:#533239;margin:24px 0;border-radius:5px;overflow:hidden}}
.timeline span{{position:absolute;top:0;height:100%;background:#70d4af}}
table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #343946}}
code{{display:block;overflow-wrap:anywhere;background:#20242c;padding:16px;border-radius:8px;font-size:13px}}
</style><h1>Cutroom <small>/ edit review</small></h1><p>{title}</p>
<video controls preload="metadata" src="{source_uri}"></video>
<p>Source preview above. Green = keep; red = remove. This is a silence-based suggestion, not word-level editing.</p>
<div class="timeline">{bars}</div>
<h2>{plan["source_duration"]:.2f}s → {duration:.2f}s</h2>
<table><thead><tr><th>Clip</th><th>Source in</th><th>Source out</th><th>Kept</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Review before rendering</h2><p>Edit plan.json if needed, then run <b>python -m cutroom review &lt;plan-path&gt;</b> to regenerate this page and digest. Listen around every cut: silence detection can remove intentional pauses and does not identify filler words or gaze.</p>
<p>To confirm this exact draft from Bash / Git Bash:</p><code>{command}</code>
<p>PowerShell:</p><code>{powershell_command}</code>
<p>Approval is a local workflow receipt, not an authenticated security boundary. A changed plan or source requires a new review.</p>
</html>'''
    _publish_review(path.parent / "review.html", document)
    return {
        "plan": str(path),
        "review": str(path.parent / "review.html"),
        "digest": digest,
        "output_duration": duration,
        "segments": plan["segments"],
    }


def approve_plan(path, digest):
    path, plan = _read(path)
    if digest != plan_digest(plan):
        raise ValueError("Review digest does not match the current plan")
    if plan.get("source_sha256") != file_digest(plan["source"]):
        raise PermissionError("Source changed; create a new draft")
    receipt = {"plan_digest": digest, "source_sha256": plan["source_sha256"]}
    with (path.parent / "approval.json").open("w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
    return receipt


def load_approved(path):
    path, plan = _read(path)
    try:
        receipt = json.loads(
            (path.parent / "approval.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ValueError) as error:
        raise PermissionError(
            "Review and approve the exact draft before rendering"
        ) from error
    if receipt.get("plan_digest") != plan_digest(plan):
        raise PermissionError("Plan changed after approval; review again")
    actual = file_digest(plan["source"])
    if actual != receipt.get("source_sha256") or actual != plan.get("source_sha256"):
        raise PermissionError("Source changed after approval; create a new draft")
    return plan
