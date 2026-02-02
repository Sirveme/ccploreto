from fastapi import APIRouter, Form, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Member, Organization, Colegiado
from app.utils.security import verify_password, create_access_token
from app.routers.dashboard import get_current_member

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/auth", tags=["auth"])


def normalizar_input_login(valor: str) -> dict:
    """
    Normaliza el input del login para detectar si es DNI o matrícula.
    
    Retorna un diccionario con:
    - tipo: 'dni' | 'matricula' | 'otro'
    - valor_original: lo que ingresó el usuario
    - valor_normalizado: el valor limpio para buscar
    - matricula_formato: formato 10-NNNN (solo si es matrícula)
    
    Ejemplos:
    - "07278864"   -> {'tipo': 'dni', 'valor_normalizado': '07278864'}
    - "10-0201"    -> {'tipo': 'matricula', 'matricula_formato': '10-0201'}
    - "100201"     -> {'tipo': 'matricula', 'matricula_formato': '10-0201'}
    - "10201"      -> {'tipo': 'matricula', 'matricula_formato': '10-0201'}
    - "100136A"    -> {'tipo': 'matricula', 'matricula_formato': '10-0136A'}
    - "DECANO"     -> {'tipo': 'otro', 'valor_normalizado': 'DECANO'}
    """
    if not valor:
        return {'tipo': None, 'valor_original': '', 'valor_normalizado': '', 'matricula_formato': None}
    
    valor = valor.strip().upper()
    resultado = {
        'tipo': None,
        'valor_original': valor,
        'valor_normalizado': valor,
        'matricula_formato': None
    }
    
    # CASO 1: Es DNI (exactamente 8 dígitos)
    if len(valor) == 8 and valor.isdigit():
        resultado['tipo'] = 'dni'
        resultado['valor_normalizado'] = valor
        return resultado
    
    # CASO 2: Es matrícula con guión (10-0201, 10-0136A)
    if '-' in valor:
        resultado['tipo'] = 'matricula'
        resultado['matricula_formato'] = valor
        resultado['valor_normalizado'] = valor.replace('-', '')
        return resultado
    
    # CASO 3: Es matrícula sin guión que empieza con 10
    if valor.startswith('10'):
        resto = valor[2:]  # Quitar el "10" inicial
        
        # Separar números de letras finales
        numero = ''
        letra = ''
        for i, char in enumerate(resto):
            if char.isdigit():
                numero += char
            else:
                letra = resto[i:].upper()
                break
        
        # Formatear: rellenar con ceros hasta 4 dígitos
        numero_formateado = numero.zfill(4)
        matricula_formato = f"10-{numero_formateado}{letra}"
        
        resultado['tipo'] = 'matricula'
        resultado['matricula_formato'] = matricula_formato
        resultado['valor_normalizado'] = valor
        return resultado
    
    # CASO 4: No es ni DNI ni matrícula reconocible (ej: "DECANO")
    resultado['tipo'] = 'otro'
    return resultado


# --- LOGIN ---
@router.post("/login")
async def login(
    request: Request,
    dni: str = Form(...), 
    code: str = Form(...), 
    db: Session = Depends(get_db)
):
    # 1. Obtener organización del contexto (Middleware)
    current_org = getattr(request.state, "org", None)
    
    # Validación de seguridad: Login debe ser siempre dentro de un dominio conocido
    if not current_org:
        return templates.TemplateResponse("pages/errors/403.html", {"request": request})

    # 2. Normalizar el input (detectar si es DNI, matrícula u otro)
    input_info = normalizar_input_login(dni)
    user = None
    
    print(f"DEBUG LOGIN: input='{dni}' -> tipo={input_info['tipo']}, matricula={input_info['matricula_formato']}")
    
    # 3. Buscar Usuario según el tipo de input
    
    if input_info['tipo'] == 'dni':
        # Buscar por DNI directo en users
        user = db.query(User).filter(User.public_id == input_info['valor_normalizado']).first()
        
        # Si no encuentra user, buscar en colegiados por DNI
        if not user:
            colegiado = db.query(Colegiado).filter(
                Colegiado.organization_id == current_org['id'],
                Colegiado.dni == input_info['valor_normalizado']
            ).first()
            
            if colegiado and colegiado.member_id:
                member = db.query(Member).filter(Member.id == colegiado.member_id).first()
                if member:
                    user = member.user
    
    elif input_info['tipo'] == 'matricula':
        # Buscar por matrícula en colegiados
        colegiado = db.query(Colegiado).filter(
            Colegiado.organization_id == current_org['id'],
            Colegiado.codigo_matricula == input_info['matricula_formato']
        ).first()
        
        print(f"DEBUG LOGIN: buscando matricula '{input_info['matricula_formato']}' -> colegiado={colegiado.dni if colegiado else 'NO ENCONTRADO'}")
        
        if colegiado:
            # Si el colegiado tiene member_id vinculado, obtener el user
            if colegiado.member_id:
                member = db.query(Member).filter(Member.id == colegiado.member_id).first()
                if member:
                    user = member.user
            
            # Si no tiene member vinculado, buscar user por DNI del colegiado
            if not user and colegiado.dni:
                user = db.query(User).filter(User.public_id == colegiado.dni).first()
        
        # Fallback: buscar en users por el valor sin guión (para compatibilidad)
        if not user:
            user = db.query(User).filter(User.public_id == input_info['valor_normalizado']).first()
        
        # Fallback 2: buscar en users por el valor original
        if not user:
            user = db.query(User).filter(User.public_id == input_info['valor_original']).first()
    
    else:
        # Otros casos (como "DECANO")
        user = db.query(User).filter(User.public_id == input_info['valor_original']).first()
    
    print(f"DEBUG LOGIN: user encontrado = {user.name if user else 'NINGUNO'}")
    
    # 4. Validar Credenciales
    if not user or not verify_password(code, user.access_code):
        return JSONResponse(
            status_code=200, 
            content="""<div class="p-3 mb-4 text-sm text-red-200 bg-red-900/50 border border-red-500/50 rounded-lg text-center animate-pulse">Error: Credenciales incorrectas</div>""", 
            media_type="text/html"
        )
    
    # 5. Buscar Membresía EN ESTA ORGANIZACIÓN
    membership = db.query(Member).filter(
        Member.user_id == user.id,
        Member.organization_id == current_org['id'], 
        Member.is_active == True
    ).first()

    if not membership:
        return JSONResponse(
            status_code=200, 
            content=f"""<div class="p-3 text-sm text-yellow-200 bg-yellow-900/50 rounded text-center">No tiene acceso a {current_org['name']}.</div>""", 
            media_type="text/html"
        )

    # 6. Éxito: Crear Sesión
    return create_session_response(user, membership)


# --- SWITCH PROFILE ---
@router.get("/switch/{target_member_id}")
async def switch_profile(
    target_member_id: int, 
    current_member: Member = Depends(get_current_member),
    db: Session = Depends(get_db)
):
    target_membership = db.query(Member).filter(
        Member.id == target_member_id,
        Member.user_id == current_member.user_id,
        Member.is_active == True
    ).first()
    
    if not target_membership:
        raise HTTPException(status_code=403, detail="Acceso denegado")
    
    return create_session_response(target_membership.user, target_membership)


# --- HELPER: CREAR COOKIE Y REDIRIGIR ---
def create_session_response(user, member):
    from fastapi.responses import Response
    
    # Generar Token
    access_token = create_access_token(data={
        "sub": str(member.id),
        "user_id": str(user.id),
        "name": user.name,
        "role": member.role,
        "org_name": member.organization.name
    })

    # Decidir destino
    target_url = "/dashboard"
    if member.role == "admin": target_url = "/admin"
    elif member.role in ["staff", "security"]: target_url = "/centinela"

    # Respuesta vacía con HX-Redirect (HTMX hará la navegación completa)
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = target_url

    # Set Cookie
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=2592000,
        samesite="lax",
        secure=False  # Cambiar a True en producción con HTTPS
    )
    return response