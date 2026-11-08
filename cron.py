# cron.py — Mini Hermes Phase 5: <=5 scheduled agent turns, 60s tick.
# MicroPython-safe: utf-8 only, plain substring ops (no `re`), bounded reads,
# lazy imports (`os`/`time`/`socket`/`gc` inside functions), single file
# rewrite per change (flash wear: tick writes ONLY when >=1 job reschedules).
#
# Store: cron.json {"jobs": [{id, prompt, every_s, next_run, enabled,
#   deliver, webhook_url, skills[], created}]}.
#   - id: "j1".. lowest-free (deterministic, collision-free, reuses freed ids).
#   - every_s: clamped 60..86400 (1min..1day).
#   - deliver: "log" | "webhook" | "telegram". Webhook URL lives in
#     webhook_url. "telegram" is ACCEPTED and stored but delivery reports
#     delivered:false, reason "telegram-phase-8" until the Phase 8 gateway
#     lands (never crashes — the job still runs and logs).
#   - skills[]: attached skill names, expanded via skillstore.view() into a
#     context prefix at run time (missing skills skipped, reported).
#
# Clock: `now` = time.time(). On device the epoch is 2000-01-01 (no RTC
# battery; net.syncTime() NTP-syncs after boot), on host it is 1970 — the
# arithmetic (now >= next_run; next_run = now + every_s) is self-consistent
# either way. Jobs survive reboot via cron.json; wall-clock accuracy needs
# NTP (see AGENTS.md).
#
# Missed-run policy: if now > next_run the job runs ONCE immediately and
# next_run resets to now + every_s (no catch-up storm). Disabled jobs never
# run and their next_run is left untouched (also: no write when idle).
# run_now() forces one run without touching the schedule (even when paused).
try:
    import ujson as json
except ImportError:
    import json

CRON_PATH = "cron.json"
MAX_JOBS = 5
EVERY_MIN = 60
EVERY_MAX = 86400
PROMPT_MAX = 1500  # same user-message cap the agent turn applies
SKILLS_MAX = 8  # attached skills per job (each <=3KB in skillstore)
PREFIX_MAX = 1000  # skills context prefix cap (prompt keeps the rest)
READ_CAP = 12288  # cron.json bound (5 jobs x ~1.5KB prompt + envelope)

_POST_HANDSHAKE_TIMEOUT = 5
_POST_TIMEOUT = 10


def _now():
    try:
        import time
        return int(time.time())
    except Exception:
        return 0


def _clamp_every(v):
    try:
        n = int(v)
    except Exception:
        return None
    if n < EVERY_MIN:
        return EVERY_MIN
    if n > EVERY_MAX:
        return EVERY_MAX
    return n


def _norm_job(j):
    """Fill defaults + clamp numerics. Never raises."""
    try:
        d = dict(j)
    except Exception:
        d = {}
    try:
        d["id"] = str(d.get("id", ""))[:16]
    except Exception:
        d["id"] = ""
    try:
        d["prompt"] = str(d.get("prompt", "") or "")
    except Exception:
        d["prompt"] = ""
    ev = _clamp_every(d.get("every_s", 3600))
    d["every_s"] = ev if ev is not None else 3600
    for k in ("next_run", "created"):
        try:
            d[k] = int(d[k])
        except Exception:
            d[k] = 0
    try:
        d["enabled"] = bool(d.get("enabled", True))
    except Exception:
        d["enabled"] = True
    try:
        d["deliver"] = str(d.get("deliver", "log") or "log").strip().lower()[:16]
    except Exception:
        d["deliver"] = "log"
    if d["deliver"] not in ("log", "webhook", "telegram"):
        d["deliver"] = "log"
    try:
        d["webhook_url"] = str(d.get("webhook_url", "") or "")[:500]
    except Exception:
        d["webhook_url"] = ""
    sk = d.get("skills", [])
    if isinstance(sk, str):
        sk = sk.split(",")
    try:
        items = list(sk)
    except Exception:
        items = []
    clean = []
    for s in items[:SKILLS_MAX]:
        try:
            nm = str(s).strip()
        except Exception:
            continue
        if nm:
            clean.append(nm[:40])
    d["skills"] = clean
    return d


def public(job):
    """Stored job as a plain dict copy (safe to hand to callers)."""
    j = _norm_job(job)
    return {"id": j["id"], "prompt": j["prompt"], "every_s": j["every_s"],
            "next_run": j["next_run"], "enabled": j["enabled"],
            "deliver": j["deliver"], "webhook_url": j["webhook_url"],
            "skills": j["skills"], "created": j["created"]}


def _load():
    try:
        with open(CRON_PATH, "r") as f:
            try:
                raw = f.read(READ_CAP + 1)
            except TypeError:
                raw = f.read()  # very old MicroPython read() takes no size
    except OSError:
        return {"jobs": []}
    except Exception:
        return {"jobs": []}
    try:
        d = json.loads((raw or "{}")[:READ_CAP])
    except Exception:
        return {"jobs": []}
    if not isinstance(d, dict):
        return {"jobs": []}
    jobs = d.get("jobs", [])
    if not isinstance(jobs, list):
        return {"jobs": []}
    return {"jobs": [_norm_job(j) for j in jobs[:MAX_JOBS + 3] if isinstance(j, dict)]}


def _save(state):
    try:
        jobs = state.get("jobs", [])
    except Exception:
        jobs = []
    with open(CRON_PATH, "w") as f:
        f.write(json.dumps({"jobs": jobs}))


def _alloc_id(jobs):
    used = set()
    for j in jobs:
        try:
            used.add(str(j.get("id", "")))
        except Exception:
            pass
    n = 1
    while True:
        cand = "j%d" % n
        if cand not in used:
            return cand
        n += 1


def _find(jobs, jid):
    try:
        want = str(jid or "").strip()
    except Exception:
        return None
    for j in jobs:
        try:
            if str(j.get("id", "")) == want:
                return j
        except Exception:
            continue
    return None


def _norm_deliver(deliver, url):
    """Returns (deliver, webhook_url, err). A full http(s) URL as `deliver`
    is shorthand for webhook-to-that-URL."""
    try:
        d = str(deliver if deliver is not None else "log").strip().lower()
    except Exception:
        d = "log"
    try:
        u = str(url if url is not None else "").strip()
    except Exception:
        u = ""
    if d.startswith("http://") or d.startswith("https://"):
        return "webhook", d[:500], ""
    if d == "log":
        return "log", "", ""
    if d == "telegram":
        return "telegram", "", ""
    if d == "webhook":
        if u.startswith("http://") or u.startswith("https://"):
            return "webhook", u[:500], ""
        return "", "", ("webhook needs a webhook_url starting with "
                        "http:// or https://")
    return "", "", "unknown deliver '%s'. Use: log, webhook, telegram" % d[:40]


def _norm_skills_arg(sk):
    if sk is None:
        return [], ""
    if isinstance(sk, str):
        sk = sk.split(",")
    try:
        items = list(sk)
    except Exception:
        return [], "skills must be a list of skill names"
    if not isinstance(sk, list):
        return [], "skills must be a list of skill names"
    if len(items) > SKILLS_MAX:
        return [], "too many skills (%d, max %d)" % (len(items), SKILLS_MAX)
    clean = []
    for s in items:
        if not isinstance(s, str):
            return [], "skills must be a list of skill names"
        try:
            nm = s.strip()
        except Exception:
            return [], "skills must be a list of skill names"
        if not nm:
            return [], "skill names must not be empty"
        clean.append(nm[:40])
    return clean, ""


def list_jobs():
    try:
        st = _load()
    except Exception:
        st = {"jobs": []}
    return {"success": True, "jobs": [public(j) for j in st.get("jobs", [])],
            "count": len(st.get("jobs", [])), "max_jobs": MAX_JOBS}


def add(prompt, every_s=3600, deliver="log", webhook_url="", skills=None,
        now=None, url=None):
    try:
        st = _load()
    except Exception:
        st = {"jobs": []}
    jobs = st.get("jobs", [])
    if len(jobs) >= MAX_JOBS:
        return {"success": False,
                "error": "cron full (%d jobs max); remove one first" % MAX_JOBS}
    try:
        pr = str(prompt if prompt is not None else "").strip()
    except Exception:
        pr = ""
    if not pr:
        return {"success": False, "error": "prompt is required"}
    if len(pr) > PROMPT_MAX:
        return {"success": False,
                "error": "prompt too long (%d chars, max %d)" % (len(pr), PROMPT_MAX)}
    if every_s is None:
        every_s = 3600
    ev = _clamp_every(every_s)
    if ev is None:
        return {"success": False,
                "error": "every_s must be a number of seconds (clamped %d..%d)"
                         % (EVERY_MIN, EVERY_MAX)}
    if url is not None and not webhook_url:
        webhook_url = url
    dv, wu, derr = _norm_deliver(deliver, webhook_url)
    if derr:
        return {"success": False, "error": derr}
    sk, serr = _norm_skills_arg(skills)
    if serr:
        return {"success": False, "error": serr}
    try:
        t = int(now) if now is not None else _now()
    except Exception:
        t = _now()
    job = {"id": _alloc_id(jobs), "prompt": pr, "every_s": ev,
           "next_run": t + ev, "enabled": True, "deliver": dv,
           "webhook_url": wu, "skills": sk, "created": t}
    jobs.append(job)
    try:
        _save(st)
    except Exception as e:
        return {"success": False, "error": "save failed: %s" % str(e)[:80]}
    return {"success": True, "job": public(job)}


def edit(jid, prompt=None, every_s=None, deliver=None, webhook_url="",
         skills=None, now=None, url=None):
    """Edit a job in place: id + created are preserved, next_run
    reschedules from now (even when paused). Any arg left as None keeps
    its stored value; validation mirrors add() (prompt <=1500 chars,
    every_s clamped 60..86400, deliver whitelist incl. telegram-stored).
    Never raises."""
    try:
        st = _load()
    except Exception:
        return {"success": False, "error": "load failed"}
    j = _find(st.get("jobs", []), jid)
    if j is None:
        return {"success": False,
                "error": "unknown job id '%s'" % str(jid)[:16]}
    if prompt is not None:
        try:
            pr = str(prompt).strip()
        except Exception:
            pr = ""
        if not pr:
            return {"success": False, "error": "prompt is required"}
        if len(pr) > PROMPT_MAX:
            return {"success": False,
                    "error": "prompt too long (%d chars, max %d)" % (len(pr), PROMPT_MAX)}
        j["prompt"] = pr
    if every_s is not None:
        ev = _clamp_every(every_s)
        if ev is None:
            return {"success": False,
                    "error": "every_s must be a number of seconds (clamped %d..%d)"
                             % (EVERY_MIN, EVERY_MAX)}
        j["every_s"] = ev
    if url is not None and not webhook_url:
        webhook_url = url
    if deliver is not None or webhook_url:
        try:
            cur_dv = str(j.get("deliver", "log") or "log")
        except Exception:
            cur_dv = "log"
        cand = deliver if deliver is not None else cur_dv
        cand_url = webhook_url
        if not cand_url and deliver is None:
            try:
                cand_url = str(j.get("webhook_url", "") or "")
            except Exception:
                cand_url = ""
        dv, wu, derr = _norm_deliver(cand, cand_url)
        if derr:
            return {"success": False, "error": derr}
        j["deliver"] = dv
        j["webhook_url"] = wu
    if skills is not None:
        sk, serr = _norm_skills_arg(skills)
        if serr:
            return {"success": False, "error": serr}
        j["skills"] = sk
    try:
        t = int(now) if now is not None else _now()
    except Exception:
        t = _now()
    try:
        ev_now = int(j.get("every_s", 3600))
    except Exception:
        ev_now = 3600
    j["next_run"] = t + ev_now
    try:
        _save(st)
    except Exception as e:
        return {"success": False, "error": "save failed: %s" % str(e)[:80]}
    return {"success": True, "job": public(j)}


def pause(jid):
    try:
        st = _load()
    except Exception:
        return {"success": False, "error": "load failed"}
    j = _find(st.get("jobs", []), jid)
    if j is None:
        return {"success": False,
                "error": "unknown job id '%s'" % str(jid)[:16]}
    j["enabled"] = False
    try:
        _save(st)
    except Exception as e:
        return {"success": False, "error": "save failed: %s" % str(e)[:80]}
    return {"success": True, "job": public(j)}


def resume(jid):
    try:
        st = _load()
    except Exception:
        return {"success": False, "error": "load failed"}
    j = _find(st.get("jobs", []), jid)
    if j is None:
        return {"success": False,
                "error": "unknown job id '%s'" % str(jid)[:16]}
    j["enabled"] = True
    # next_run stays as-is: a stale schedule fires ONCE on the next tick
    # (missed-run policy), then reschedules from now.
    try:
        _save(st)
    except Exception as e:
        return {"success": False, "error": "save failed: %s" % str(e)[:80]}
    return {"success": True, "job": public(j)}


def remove(jid):
    try:
        st = _load()
    except Exception:
        return {"success": False, "error": "load failed"}
    jobs = st.get("jobs", [])
    j = _find(jobs, jid)
    if j is None:
        return {"success": False,
                "error": "unknown job id '%s'" % str(jid)[:16]}
    try:
        jobs.remove(j)
    except Exception:
        pass
    try:
        _save(st)
    except Exception as e:
        return {"success": False, "error": "save failed: %s" % str(e)[:80]}
    return {"success": True, "removed": str(j.get("id", ""))}


def _skills_prefix(names):
    """Attached-skills context prefix ('' when none loadable). Never raises."""
    if not names:
        return "", [], []
    if isinstance(names, str):
        names = [names]
    try:
        items = list(names)
    except Exception:
        return "", [], []
    try:
        import skillstore as _sk
    except Exception:
        return "", [], [str(s)[:40] for s in items[:SKILLS_MAX]]
    parts, loaded, missing = [], [], []
    for s in items[:SKILLS_MAX]:
        try:
            nm = str(s).strip()
        except Exception:
            continue
        if not nm:
            continue
        try:
            v = _sk.view(nm)
        except Exception:
            missing.append(nm[:40])
            continue
        if isinstance(v, dict) and v.get("success"):
            try:
                body = str(v.get("content", ""))[:1500]
            except Exception:
                body = ""
            parts.append("## skill: %s\n%s" % (nm[:40], body))
            loaded.append(nm[:40])
        else:
            missing.append(nm[:40])
    if not parts:
        return "", loaded, missing
    text = "Attached skills context:\n" + "\n\n".join(parts)
    return (text[:PREFIX_MAX] + "\n---\n"), loaded, missing


def _split_url(url):
    u = (url or "").strip()
    is_https = u.startswith("https://")
    if is_https:
        rest = u[8:]
    elif u.startswith("http://"):
        rest = u[7:]
    else:
        rest = u
    slash = rest.find("/")
    if slash < 0:
        host, path = rest, "/"
    else:
        host, path = rest[:slash], rest[slash:]
    port = 443 if is_https else 80
    if ":" in host:
        h, p = host.rsplit(":", 1)
        try:
            port = int(p)
            host = h
        except Exception:
            pass
    if not host:
        raise ValueError("empty host")
    return is_https, host, port, path or "/"


def _send_all(s, buf):
    if isinstance(buf, str):
        buf = buf.encode()
    mv = memoryview(buf)
    sent = 0
    while sent < len(buf):
        n = s.send(mv[sent:])
        if n is None:
            continue
        if n <= 0:
            raise OSError("send stalled")
        sent += n


def _post(url, body_text):
    """Minimal raw-socket HTTP POST of a small JSON body. Returns
    (True, code) or (False, err). Single attempt, short timeouts,
    gc around the socket — same discipline as llm._post_raw. Never raises.

    Factored as a module-level seam so host tests can monkeypatch it
    (no network in tests)."""
    try:
        is_https, host, port, path = _split_url(url)
    except Exception as e:
        return False, "bad url: %s" % str(e)[:60]
    try:
        import socket
    except ImportError:
        return False, "no socket"
    s = None
    try:
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        s = socket.socket()
        try:
            s.settimeout(_POST_HANDSHAKE_TIMEOUT)
        except Exception:
            pass
        try:
            import llm as _llm
            addrs = _llm._resolve_all_ipv4(host, port)
        except Exception:
            addrs = []
        if not addrs:
            try:
                infos = socket.getaddrinfo(host, port)
                addrs = [i[4] for i in infos]
            except Exception:
                return False, "dns failed for %s" % host[:60]
        if not addrs:
            return False, "no address for %s" % host[:60]
        s.connect(addrs[0])
        if is_https:
            try:
                import ssl as _sslmod
            except ImportError:
                try:
                    import ussl as _sslmod
                except ImportError:
                    return False, "no ssl"
            _wrap = getattr(_sslmod, "wrap_socket", None)
            if _wrap is not None:
                try:
                    s = _wrap(s, server_hostname=host)
                except TypeError:
                    s = _wrap(s)
            else:
                _ctx = _sslmod.create_default_context()
                try:
                    _ctx.check_hostname = False
                    _ctx.verify_mode = _sslmod.CERT_NONE
                except Exception:
                    pass
                s = _ctx.wrap_socket(s, server_hostname=host)
            # NOTE: no settimeout() on the wrapped socket — MicroPython's
            # SSLSocket has no settimeout (timeout was set pre-wrap above).
        body = body_text.encode("utf-8") if isinstance(body_text, str) else body_text
        head = ("POST %s HTTP/1.0\r\nHost: %s\r\nContent-Type: application/json\r\n"
                "Content-Length: %d\r\nConnection: close\r\n\r\n" % (path, host, len(body)))
        _send_all(s, head.encode() + body)
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 4096:
            try:
                d = s.recv(512)
            except Exception:
                break
            if not d:
                break
            buf += d
        try:
            code = int(buf.split(b"\r\n", 1)[0].decode().split(" ")[1])
        except Exception:
            return False, "bad status"
        if 200 <= code < 300:
            return True, code
        return False, "HTTP %d" % code
    except Exception as e:
        return False, str(e)[:80]
    finally:
        try:
            if s is not None:
                s.close()
        except Exception:
            pass


def _default_run(prompt_text):
    import agent_core
    return agent_core.runTurn(prompt_text, [])


def run_job(job, run_fn=None):
    """Run one job now: skills prefix + run_fn + log + delivery. The schedule
    is NOT touched (see run_now/tick). run_fn(prompt)->reply; default is
    agent_core.runTurn with empty history. Never raises."""
    try:
        jid = str(job.get("id", "?"))[:16]
    except Exception:
        jid = "?"
    try:
        prompt = str(job.get("prompt", "") or "")
    except Exception:
        prompt = ""
    if not prompt.strip():
        return {"success": False, "id": jid, "error": "job has no prompt"}
    try:
        prefix, loaded, missing = _skills_prefix(job.get("skills", []))
    except Exception:
        prefix, loaded, missing = "", [], []
    full = (prefix + prompt) if prefix else prompt
    if len(full) > PROMPT_MAX:
        full = full[:PROMPT_MAX]
    fn = run_fn if run_fn is not None else _default_run
    try:
        reply = fn(full)
    except Exception as e:
        return {"success": False, "id": jid,
                "error": "cron run failed: %s" % str(e)[:120]}
    if reply is None:
        reply = ""
    try:
        reply = str(reply)
    except Exception:
        reply = ""
    try:
        import agent_tools
        agent_tools.appendChatLog("[cron %s] %s" % (jid, prompt[:200]), reply)
        logged = True
    except Exception:
        logged = False
    try:
        target = str(job.get("deliver", "log") or "log").strip().lower()
    except Exception:
        target = "log"
    delivered, reason = True, ""
    if target == "webhook":
        try:
            wurl = str(job.get("webhook_url", "") or "")
        except Exception:
            wurl = ""
        if not wurl:
            delivered, reason = False, "no webhook_url stored"
        else:
            try:
                payload = json.dumps({"id": jid, "prompt": prompt[:200],
                                      "reply": reply[:500], "at": _now()})
            except Exception:
                payload = "{}"
            try:
                ok, info = _post(wurl, payload)
            except Exception as e:
                ok, info = False, str(e)[:80]
            if ok:
                delivered = True
            else:
                delivered, reason = False, str(info)[:120]
    elif target == "telegram":
        # Phase 8: deliver via the Telegram gateway (lazy import — a broken
        # gateway.py must never break cron). No token/allowlist -> the same
        # delivered:false envelope as before Phase 8.
        try:
            import gateway as _gw
            delivered, reason = _gw.tg_send_result(reply, prompt[:200], jid)
        except Exception:
            delivered, reason = False, "telegram-phase-8"
    out = {"success": True, "id": jid, "reply": reply, "logged": logged,
           "delivered": delivered, "target": target,
           "skills_loaded": loaded, "skills_missing": missing}
    if reason:
        out["reason"] = reason
    return out


def run_now(jid, run_fn=None):
    """Force one run of a job WITHOUT touching next_run (works paused too).
    Never raises."""
    try:
        st = _load()
    except Exception:
        return {"success": False, "error": "load failed"}
    j = _find(st.get("jobs", []), jid)
    if j is None:
        return {"success": False,
                "error": "unknown job id '%s'" % str(jid)[:16]}
    try:
        r = run_job(j, run_fn)
    except Exception as e:
        return {"success": False, "id": str(jid)[:16],
                "error": "cron run failed: %s" % str(e)[:120]}
    try:
        r["schedule_unchanged"] = True
    except Exception:
        pass
    return r


def tick(now=None, run_fn=None):
    """Reschedule due jobs (enabled + next_run <= now -> next_run = now +
    every_s), write the file ONCE iff anything changed, and — only when
    run_fn is given — run each due job via run_job. Returns
    {"due": [...], "results": [...], "changed": bool}. Never raises.

    The main loop calls tick() with no run_fn and runs the returned due
    jobs itself; tests pass a fake run_fn for a one-call run+reschedule."""
    try:
        t = int(now) if now is not None else _now()
    except Exception:
        t = _now()
    try:
        st = _load()
    except Exception:
        return {"due": [], "results": [], "changed": False}
    jobs = st.get("jobs", [])
    due = []
    for j in jobs:
        try:
            if not j.get("enabled", True):
                continue  # disabled: skip AND leave next_run stale (no write)
            if int(j.get("next_run", 0)) <= t:
                try:
                    ev = int(j.get("every_s", 3600))
                except Exception:
                    ev = 3600
                if ev < EVERY_MIN:
                    ev = EVERY_MIN
                if ev > EVERY_MAX:
                    ev = EVERY_MAX
                j["next_run"] = t + ev
                due.append(j)
        except Exception:
            continue
    changed = bool(due)
    if changed:
        try:
            _save(st)
        except Exception:
            pass
    results = []
    if run_fn is not None:
        for j in due:
            try:
                results.append(run_job(j, run_fn))
            except Exception as e:
                try:
                    jid = str(j.get("id", "?"))[:16]
                except Exception:
                    jid = "?"
                results.append({"success": False, "id": jid,
                                "error": "cron run failed: %s" % str(e)[:120]})
    return {"due": [public(j) for j in due], "results": results,
            "changed": changed}


def run_due(run_fn=None, now=None):
    """One scheduler pass for the main-loop tick: tick() (no run_fn) then
    run_job() per due job. Every failure is captured per job — this function
    never raises, so a cron crash can NEVER kill the server."""
    try:
        t = int(now) if now is not None else _now()
    except Exception:
        t = _now()
    try:
        r = tick(t, None)
    except Exception as e:
        return {"success": False, "ran": 0, "results": [],
                "error": "tick failed: %s" % str(e)[:80]}
    results = []
    for job in r.get("due", []):
        try:
            results.append(run_job(job, run_fn))
        except Exception as e:
            try:
                jid = str(job.get("id", "?"))[:16]
            except Exception:
                jid = "?"
            results.append({"success": False, "id": jid,
                            "error": "cron run failed: %s" % str(e)[:120]})
    return {"success": True, "ran": len(results), "results": results}


def handle(d):
    """Single dict-in/dict-out dispatcher shared by the `cron` tool and
    POST /api/cron. Never raises."""
    try:
        if not isinstance(d, dict):
            return {"success": False, "error": "args must be an object"}
        op = str(d.get("op", "list") or "list").strip().lower()
    except Exception:
        return {"success": False, "error": "bad args"}
    try:
        if op == "add":
            return add(d.get("prompt", ""),
                       d.get("every_s", d.get("every", 3600)),
                       d.get("deliver", "log"),
                       d.get("webhook_url", d.get("url", "")),
                       d.get("skills", []))
        if op in ("list", "get"):
            return list_jobs()
        if op == "edit":
            jid = str(d.get("id", "") or "").strip()
            if not jid:
                return {"success": False,
                        "error": "id is required for 'edit'"}
            ev_arg = d.get("every_s", d.get("every", None))
            return edit(jid, d.get("prompt", None), ev_arg,
                        d.get("deliver", None),
                        d.get("webhook_url", d.get("url", "")),
                        d.get("skills", None))
        if op in ("pause", "resume", "remove", "run_now"):
            jid = str(d.get("id", "") or "").strip()
            if not jid:
                return {"success": False,
                        "error": "id is required for '%s'" % op}
            if op == "pause":
                return pause(jid)
            if op == "resume":
                return resume(jid)
            if op == "remove":
                return remove(jid)
            return run_now(jid)
        return {"success": False,
                "error": ("Unknown op '%s'. Use: add, list, edit, pause, resume, "
                          "remove, run_now" % op[:40])}
    except Exception as e:
        return {"success": False, "error": "cron failed: %s" % str(e)[:120]}
