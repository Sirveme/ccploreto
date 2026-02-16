"""
Router: Autenticación
=====================
- Login solo por DNI
- Cambio de clave obligatorio en segundo acceso
- Logout
- Recuperación de clave (placeholder)
"""

from fastapi import APIRouter, Form, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import re

from app.database import get_db
from app.models import User, Member, Organization, Colegiado
from app.utils.security import verify_password, create_access_token, get_password_hash
from app.routers.dashboard import get_current_member

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/auth", tags=["auth"])


# ============================================================
# VALIDACIÓN DE CLAVE
# ============================================================
def validar_clave_nueva(clave: str) -> tuple[bool, str]:
    """
    Valida que la clave cumpla los requisitos:
    - Mínimo 6 caracteres
    - Al menos una letra mayúscula
    - Puede contener letras, números y símbolos (*, @, #, /)
    
    Retorna: (es_valida, mensaje_error)
    """
    if len(clave) < 6:
        return False, "La clave debe tener al menos 6 caracteres"
    
    if not re.search(r'[A-Z]', clave):
        return False, "La clave debe contener al menos una letra mayúscula"
    
    return True, ""


# ============================================================
# LOGIN
# ============================================================
@router.post("/login")
async def login(
    request: Request,
    dni: str = Form(...), 
    code: str = Form(...), 
    db: Session = Depends(get_db)
):
    """
    Login por DNI únicamente.
    Si es el segundo acceso y no ha cambiado clave, redirige a cambio obligatorio.
    """
    # 1. Obtener organización del contexto
    current_org = getattr(request.state, "org", None)
    
    if not current_org:
        return templates.TemplateResponse("pages/errors/403.html", {"request": request})

    # 2. Validar que sea DNI (8 dígitos)
    dni = dni.strip()
    if not (len(dni) == 8 and dni.isdigit()):
        return JSONResponse(
            status_code=200, 
            content="""<div class="p-3 mb-4 text-sm text-red-200 bg-red-900/50 border border-red-500/50 rounded-lg text-center">Ingrese su DNI (8 dígitos)</div>""", 
            media_type="text/html"
        )
    
    # 3. Buscar usuario por DNI
    user = db.query(User).filter(User.public_id == dni).first()
    
    # Si no encuentra, buscar colegiado por DNI para dar mensaje más específico
    if not user:
        colegiado = db.query(Colegiado).filter(
            Colegiado.organization_id == current_org['id'],
            Colegiado.dni == dni
        ).first()
        
        if colegiado:
            # Existe el colegiado pero no tiene usuario → crear automáticamente
            from app.utils.security import get_password_hash
            
            new_user = User(
                public_id=dni,
                name=colegiado.apellidos_nombres or dni,
                access_code=get_password_hash(dni),  # Clave inicial = DNI
                debe_cambiar_clave=True,
                login_count=0,
            )
            db.add(new_user)
            db.flush()
            
            # Determinar rol según condición
            rol = "colegiado"
            
            new_member = Member(
                user_id=new_user.id,
                organization_id=current_org['id'],
                role=rol,
                is_active=True,
            )
            db.add(new_member)
            db.flush()
            
            # Vincular colegiado con member
            colegiado.member_id = new_member.id
            db.commit()
            
            # Ahora el user existe → cae al paso 4 (validar contraseña)
            user = new_user
        else:
            return JSONResponse(
                status_code=200, 
                content="""<div class="p-3 mb-4 text-sm text-red-200 bg-red-900/50 border border-red-500/50 rounded-lg text-center">DNI no registrado en el sistema</div>""", 
                media_type="text/html"
            )
    
    # 4. Validar contraseña
    if not verify_password(code, user.access_code):
        return JSONResponse(
            status_code=200, 
            content="""<div class="p-3 mb-4 text-sm text-red-200 bg-red-900/50 border border-red-500/50 rounded-lg text-center">Clave incorrecta</div>""", 
            media_type="text/html"
        )
    
    # 5. Buscar membresía en esta organización
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

    # 6. Incrementar contador de login
    user.login_count = (user.login_count or 0) + 1
    user.ultimo_login = datetime.now(timezone.utc)
    db.commit()
    
    # 7. Verificar si debe cambiar clave (segundo login en adelante)
    debe_cambiar = getattr(user, 'debe_cambiar_clave', False)
    es_segundo_login = user.login_count >= 2
    
    if debe_cambiar and es_segundo_login:
        # Crear token temporal para cambio de clave
        temp_token = create_access_token(data={
            "sub": str(membership.id),
            "user_id": str(user.id),
            "cambio_clave": True  # Flag especial
        })
        
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = "/auth/cambiar-clave"
        response.set_cookie(
            key="access_token",
            value=f"Bearer {temp_token}",
            httponly=True,
            max_age=600,  # 10 minutos para cambiar clave
            samesite="lax",
            secure=False
        )
        return response

    # 8. Login exitoso normal
    return create_session_response(user, membership, db)


# ============================================================
# LOGOUT
# ============================================================
@router.get("/logout")
async def logout():
    """Cierra sesión y redirige al inicio"""
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token", path="/")
    return response


# ============================================================
# CAMBIO DE CLAVE OBLIGATORIO
# ============================================================
@router.get("/cambiar-clave")
async def pagina_cambiar_clave(request: Request, db: Session = Depends(get_db)):
    """Página para cambio de clave obligatorio"""
    
    # Verificar que tenga token válido
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/", status_code=302)
    
    return templates.TemplateResponse("pages/cambiar_clave.html", {
        "request": request,
        "theme": getattr(request.state, "theme", None),
        "org": getattr(request.state, "org", {})
    })


@router.post("/cambiar-clave")
async def procesar_cambio_clave(
    request: Request,
    clave_actual: str = Form(...),
    clave_nueva: str = Form(...),
    clave_confirmar: str = Form(...),
    db: Session = Depends(get_db)
):
    """Procesa el cambio de clave"""
    
    # Obtener usuario del token
    from jose import jwt, JWTError
    from app.config import SECRET_KEY
    from app.utils.security import ALGORITHM
    
    token = request.cookies.get("access_token")
    if not token:
        return JSONResponse(
            status_code=200,
            content="""<div class="alert alert-error">Sesión expirada. Vuelva a iniciar sesión.</div>""",
            media_type="text/html"
        )
    
    try:
        scheme, token_value = token.split()
        payload = jwt.decode(token_value, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        member_id = payload.get("sub")
    except:
        return JSONResponse(
            status_code=200,
            content="""<div class="alert alert-error">Sesión inválida. Vuelva a iniciar sesión.</div>""",
            media_type="text/html"
        )
    
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return JSONResponse(
            status_code=200,
            content="""<div class="alert alert-error">Usuario no encontrado.</div>""",
            media_type="text/html"
        )
    
    # Validar clave actual
    if not verify_password(clave_actual, user.access_code):
        return JSONResponse(
            status_code=200,
            content="""<div class="alert alert-error">La clave actual es incorrecta.</div>""",
            media_type="text/html"
        )
    
    # Validar que las claves nuevas coincidan
    if clave_nueva != clave_confirmar:
        return JSONResponse(
            status_code=200,
            content="""<div class="alert alert-error">Las claves nuevas no coinciden.</div>""",
            media_type="text/html"
        )
    
    # Validar que no sea igual a la actual
    if clave_actual == clave_nueva:
        return JSONResponse(
            status_code=200,
            content="""<div class="alert alert-error">La clave nueva debe ser diferente a la actual.</div>""",
            media_type="text/html"
        )
    
    # Validar requisitos de la clave
    es_valida, mensaje = validar_clave_nueva(clave_nueva)
    if not es_valida:
        return JSONResponse(
            status_code=200,
            content=f"""<div class="alert alert-error">{mensaje}</div>""",
            media_type="text/html"
        )
    
    # Actualizar clave
    user.access_code = get_password_hash(clave_nueva)
    user.debe_cambiar_clave = False
    db.commit()
    
    # Obtener membership para crear sesión completa
    membership = db.query(Member).filter(Member.id == int(member_id)).first()
    
    if membership:
        return create_session_response(user, membership, db)
    
    # Fallback: redirigir al login
    return JSONResponse(
        status_code=200,
        content="""<div class="alert alert-success">Clave actualizada. <a href="/">Iniciar sesión</a></div>""",
        media_type="text/html"
    )


# ============================================================
# RECUPERAR CLAVE (PLACEHOLDER)
# ============================================================
@router.get("/recuperar-clave")
async def pagina_recuperar_clave(request: Request):
    """Página para recuperar clave (por implementar)"""
    return templates.TemplateResponse("pages/recuperar_clave.html", {
        "request": request,
        "theme": getattr(request.state, "theme", None),
        "org": getattr(request.state, "org", {})
    })


# ============================================================
# SWITCH PROFILE (mantener funcionalidad existente)
# ============================================================
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
    
    return create_session_response(target_membership.user, target_membership, db)


# ============================================================
# HELPER: CREAR COOKIE Y REDIRIGIR
# ============================================================
def create_session_response(user, member, db=None):
    """Crea la respuesta con cookie de sesión"""
    
    access_token = create_access_token(data={
        "sub": str(member.id),
        "user_id": str(user.id),
        "name": user.name,
        "role": member.role,
        "org_name": member.organization.name
    })

    # Decidir destino según rol
    target_url = "/dashboard"
    if member.role == "admin": 
        target_url = "/admin"
    elif member.role in ["staff", "security"]: 
        target_url = "/centinela"
    elif member.role in ["cajero", "tesorero"]:
        target_url = "/caja"
    elif member.role == "colegiado":
        # Verificar condición
        col = db.query(Colegiado).filter(Colegiado.member_id == member.id).first()
        if col and col.condicion not in ('habil', 'vitalicio'):
            target_url = "/portal/inactivo"
        else:
            target_url = "/dashboard"

    response = Response(status_code=200)
    response.headers["HX-Redirect"] = target_url

    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=2592000,  # 30 días
        samesite="lax",
        secure=False  # Cambiar a True en producción con HTTPS
    )
    return response
