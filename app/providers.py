# providers.py — primary + optional fallback endpoint (Mini Hermes Phase 1).
# MicroPython-safe: utf-8 only, no new imports, tiny allocations.
# Ordered list [(url, key, model)]: primary from config.cfgEndpoint/cfgApiKey/
# cfgModel, plus one fallback from config.yaml fallback.endpoint/api_key/
# fallback_model (empty endpoint = no fallback).
# Failover triggers: transport failure (ok=False), HTTP 429, HTTP 5xx.
# Anything else (other 4xx incl. 401, bad JSON) is non-retriable: return as-is.


def getProviders():
    """Return [(chat_url, api_key, model)] — primary first, fallback if set."""
    import config
    out = []
    try:
        ep = (config.cfgEndpoint or "").strip()
    except Exception:
        ep = ""
    if ep:
        try:
            url = config.chatCompletionsUrl(ep)
        except Exception:
            url = ep
        try:
            key = config.cfgApiKey or ""
        except Exception:
            key = ""
        try:
            model = config.cfgModel or "gpt-4o-mini"
        except Exception:
            model = "gpt-4o-mini"
        if not model:
            model = "gpt-4o-mini"
        out.append((url, key, model))
    try:
        fep = (getattr(config, "cfgFallbackEndpoint", "") or "").strip()
    except Exception:
        fep = ""
    if fep:
        try:
            furl = config.chatCompletionsUrl(fep)
        except Exception:
            furl = fep
        try:
            fkey = getattr(config, "cfgFallbackKey", "") or ""
        except Exception:
            fkey = ""
        try:
            fmodel = getattr(config, "cfgFallbackModel", "") or ""
        except Exception:
            fmodel = ""
        if not fmodel:
            # fall back to the primary model so the retry is well-formed
            try:
                fmodel = config.cfgModel or "gpt-4o-mini"
            except Exception:
                fmodel = "gpt-4o-mini"
        if not fmodel:
            fmodel = "gpt-4o-mini"
        out.append((furl, fkey, fmodel))
    return out


def resolveProviders():
    """Alias of getProviders (PLAN.md name)."""
    return getProviders()


def isFailoverCode(code):
    """True for HTTP 429 and 5xx (retriable onto the fallback)."""
    try:
        c = int(code)
    except Exception:
        return False
    if c == 429:
        return True
    return 500 <= c <= 599


def shouldFailover(ok, code):
    """True on transport failure or retriable HTTP status."""
    if not ok:
        return True
    return isFailoverCode(code)
