"""ctypes bridge to the C data structures. Raises CCoreError on any C error code."""
import ctypes, os, sys
BASE = os.path.join(os.path.dirname(__file__), "..", "c_core")
class CCoreError(Exception): pass

def _load():
    name = "libroadcare_ds.dll" if sys.platform == "win32" else "libroadcare_ds.so"
    path = os.path.abspath(os.path.join(BASE, name))
    if not os.path.exists(path):
        raise CCoreError("C library not built. Run 'make' inside c_core/.")
    lib = ctypes.CDLL(path)
    lib.ll_insert.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_long]
    lib.pq_push.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_long]
    return lib

_lib = None
def lib():
    global _lib
    if _lib is None: _lib = _load()
    return _lib

def _check(code, what):
    if code < 0: raise CCoreError(f"{what} failed (code {code})")

def ordered_queue(tasks):
    """tasks: iterable of (complaint_id, score, unix_ts). Returns ids, highest priority first."""
    L = lib(); L.pq_clear()
    for cid, score, ts in tasks: _check(L.pq_push(cid, float(score), int(ts)), "pq_push")
    buf = (ctypes.c_int * max(L.pq_size(), 1))()
    n = L.pq_snapshot(buf, len(buf))
    return list(buf)[:n]

def register_reports(reports):
    """Rebuild the linked list of complaint records; returns traversal as [(id, score)]."""
    L = lib(); L.ll_clear()
    for cid, score, ts in reports: _check(L.ll_insert(cid, float(score), int(ts)), "ll_insert")
    out, i, s = [], ctypes.c_int(), ctypes.c_double()
    for k in range(L.ll_count()):
        L.ll_get(k, ctypes.byref(i), ctypes.byref(s)); out.append((i.value, s.value))
    return out
