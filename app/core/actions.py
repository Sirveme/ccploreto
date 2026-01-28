ACTION_REGISTRY = {
    # --- FINANZAS ---
    "finance.pay": {
        "desc": "Pagar deuda, pensión, cuota o subir voucher.",
        "params": ["amount"],
        "niches": ["all"],
        "roles": ["user"],
        "ui": {
            "type": "open_modal",
            "target": "modal-payment", 
            "message": "Abriendo formulario de pago."
        }
    },
    
    # --- SEGURIDAD ---
    "security.panic": {
        "desc": "Emergencia, robo, asalto.",
        "params": [],
        "niches": ["condominio", "club"],
        "roles": ["user", "staff"],
        "ui": {
            "type": "click", 
            "target": "btn-panico", 
            "message": "Activando alerta."
        }
    },
    "security.arrival": {
        "desc": "Avisar llegada.",
        "params": [],
        "niches": ["condominio"],
        "roles": ["user"],
        "ui": {
            "type": "click", 
            "target": "btn-llegando", 
            "message": "Avisando llegada."
        }
    },

    # --- COMUNICACIÓN (Admin) ---
    "comm.broadcast": {
        "desc": "Redactar comunicado masivo.",
        "params": ["title", "content", "priority"],
        "niches": ["all"],
        "roles": ["admin"],
        "ui": {
            "type": "fill_form", 
            "target": "form-boletin", 
            "submit": False
        }
    }
}

def get_allowed_actions(user_role: str, org_type: str):
    allowed = {}
    for key, action in ACTION_REGISTRY.items():
        if "all" not in action["niches"] and org_type not in action["niches"]: continue
        if "all" not in action["roles"] and user_role not in action["roles"]: continue
        allowed[key] = action
    return allowed

def get_action_ui(action_id):
    return ACTION_REGISTRY.get(action_id, {}).get("ui")