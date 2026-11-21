"""Road-damage image classifier (ONNX Runtime). Replace the weights to change the model.
Expected files in image_analysis/models/:
  road_damage.onnx - image classifier, input 1x3xHxW float32, output class logits
  labels.json      - e.g. ["Longitudinal crack","Transverse crack","Alligator crack","Pothole","No damage"]"""
import json, os, time
try:
    import cv2, numpy as np
    LIBS_OK = True
except Exception:  # OpenCV/NumPy unavailable (e.g. blocked by a system policy)
    LIBS_OK = False
D = os.path.join(os.path.dirname(__file__), "models")
SEVERITY = {"pothole": "High", "alligator crack": "High", "transverse crack": "Medium",
            "longitudinal crack": "Low", "no damage": "Low"}
LOW_CONF = float(os.environ.get("LOW_CONFIDENCE", 0.60))
_sess = None

def quality_check(img):
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur, bright = cv2.Laplacian(gray, cv2.CV_64F).var(), float(gray.mean())
    if min(h, w) < 224: return False, "Image resolution is too low (minimum 224 px)."
    if blur < 25: return False, "Image appears blurred. Please upload a sharper photo."
    if bright < 30 or bright > 235: return False, "Image is too dark or too bright."
    return True, "OK"

def analyse(path):
    """Returns real stage results. Never fabricates a prediction."""
    stages, t0 = [], time.time()
    def mark(name, ok, note=""): stages.append({"stage": name, "ok": ok, "note": note, "t": round(time.time()-t0, 2)})
    if not LIBS_OK:
        mark("Image analysis libraries", False, "OpenCV/NumPy not available on this computer")
        return {"status": "model_unavailable", "needs_review": True, "stages": stages}
    img = cv2.imread(path)
    if img is None: mark("Image read", False, "Unreadable image"); return {"status": "failed", "stages": stages}
    mark("Image read", True)
    ok, note = quality_check(img); mark("Quality validation", ok, note)
    if not ok: return {"status": "rejected", "reason": note, "stages": stages}
    mp, lp = os.path.join(D, "road_damage.onnx"), os.path.join(D, "labels.json")
    if not (os.path.exists(mp) and os.path.exists(lp)):
        mark("Model inference", False, "Model weights not installed")
        return {"status": "model_unavailable", "needs_review": True, "stages": stages}
    try:
        global _sess
        import onnxruntime as ort
        if _sess is None: _sess = ort.InferenceSession(mp, providers=["CPUExecutionProvider"])
        labels = json.load(open(lp)); inp = _sess.get_inputs()[0]
        size = inp.shape[2] if isinstance(inp.shape[2], int) else 224
        x = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (size, size)).astype("float32") / 255.0
        x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype("float32")
        mark("Preprocessing", True, f"{size}x{size} normalised")
        logits = _sess.run(None, {inp.name: x})[0][0]
        p = np.exp(logits - logits.max()); p /= p.sum(); k = int(p.argmax())
        cat, conf = labels[k], float(p[k]); mark("Damage detection", True, cat)
        sev = SEVERITY.get(cat.lower(), "Medium"); mark("Severity classification", True, sev)
        return {"status": "completed", "category": cat, "severity": sev, "confidence": round(conf, 3),
                "needs_review": conf < LOW_CONF, "stages": stages}
    except Exception as e:
        mark("Model inference", False, "Inference error")
        return {"status": "model_unavailable", "needs_review": True, "stages": stages, "error": str(e)}
