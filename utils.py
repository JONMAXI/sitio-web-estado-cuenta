import re
from datetime import datetime

def safe_int(value, default=0):
    try: return int(value)
    except (ValueError, TypeError): return default

def safe_float(value, default=0.0):
    try: return float(value)
    except (ValueError, TypeError): return default

def safe_date(value, fmt="%Y-%m-%d %H:%M:%S"):
    try: return datetime.strptime(value, fmt)
    except (ValueError, TypeError): return None

def parse_cuotas_field(value):
    if value is None: return []
    if isinstance(value, (int, float)): return [int(value)]
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(',') if p.strip()]
        out = []
        for p in parts:
            try: out.append(int(p))
            except: pass
        return out
    return []

def extraer_numero_cuota(concepto):
    if not concepto: return None
    m = re.search(r'CUOTA.*?(\d+)\s+DE', concepto, re.IGNORECASE)
    if m: return int(m.group(1))
    m2 = re.search(r'(\d+)', concepto)
    if m2: return int(m2.group(1))
    return None
