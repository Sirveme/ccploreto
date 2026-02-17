import base64
import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, asc, desc
from app.database import get_db
from app.models import Member, Debt, Payment, Device
from app.routers.dashboard import get_current_member
# IMPORTANTE: Importamos el gestor de websockets
from app.routers.ws import manager 

load_dotenv(override=True)
#print ("🔑 Cargando OPENAI_API_KEY..."+ os.getenv("OPENAI_API_KEY"))

api_key = os.getenv("OPENAI_API_KEY")

#print ("🔑 Cargando clave API en finance.py..."+ api_key)

router = APIRouter(tags=["finance"])
templates = Jinja2Templates(directory="app/templates")

# --- ADMIN: GENERAR CUOTAS MASIVAS ---
@router.post("/finance/generate-fees")
async def generate_fees(
    amount: float = Form(...),
    concept: str = Form(...),
    due_date: str = Form(...),
    db: Session = Depends(get_db),
    admin: Member = Depends(get_current_member)
):
    if admin.role != "admin": return "Acceso denegado"

    vecinos = db.query(Member).filter(
        Member.organization_id == admin.organization_id,
        Member.role == "user",
        Member.is_active == True
    ).all()

    count = 0
    try:
        due_date_obj = datetime.strptime(due_date, '%Y-%m-%d')
    except:
        due_date_obj = None

    for v in vecinos:
        existing = db.query(Debt).filter(
            Debt.member_id == v.id,
            Debt.concept == concept
        ).first()
        
        if not existing:
            deuda = Debt(
                member_id=v.id,
                organization_id=admin.organization_id,
                concept=concept,
                amount=amount,
                balance=amount,
                status="pending",
                due_date=due_date_obj
            )
            db.add(deuda)
            count += 1
    
    db.commit()
    
    return HTMLResponse(f"""
    <div class="bg-green-900/30 border-l-4 border-green-500 p-4 rounded mb-4 fade-me-in">
        <h3 class="font-bold text-green-400">✅ Proceso Terminado</h3>
        <p class="text-sm text-slate-300">Se generaron {count} cuotas de S/ {amount}.</p>
    </div>
    """)

# --- VECINO: REPORTAR PAGO ---
@router.post("/finance/payment/report")
async def report_payment(
    amount: float = Form(...),
    method: str = Form(...),
    # CAMBIO: Ahora es opcional (None)
    operation_code: str = Form(None), 
    voucher: UploadFile = File(None),
    db: Session = Depends(get_db),
    member: Member = Depends(get_current_member)
):
    # VALIDACIÓN LÓGICA: O tiene código O tiene foto
    if not operation_code and not voucher:
         return HTMLResponse('<div class="text-red-500 border border-red-500 p-2 rounded">❌ Debes ingresar el código o subir el voucher.</div>')

    # Si hay código, validamos duplicados
    if operation_code:
        exists = db.query(Payment).filter(
            Payment.operation_code == operation_code,
            Payment.organization_id == member.organization_id,
            Payment.status != 'rejected'
        ).first()
        
        if exists:
            return HTMLResponse('<div class="bg-red-900/50 text-red-200 p-3 rounded">❌ Error: Código duplicado.</div>')

    # Procesar foto
    final_photo = None
    if voucher and voucher.filename:
        contents = await voucher.read()
        img_str = base64.b64encode(contents).decode("utf-8")
        final_photo = f"data:{voucher.content_type};base64,{img_str}"

    new_payment = Payment(
        organization_id=member.organization_id,
        member_id=member.id,
        amount=amount,
        payment_method=method,
        operation_code=operation_code or "Por validar en foto", # Valor por defecto si no hay código
        voucher_url=final_photo,
        status="review"
    )
    db.add(new_payment)
    db.commit()

    # AVISO AL ADMIN (Tiempo Real)
    await manager.broadcast({
        "type": "NEW_PAYMENT_REPORT",
        "org_id": member.organization_id,
        "amount": f"S/ {amount}",
        "user": member.user.name
    })

    # RESPUESTA HTML (Reemplaza al formulario)
    return HTMLResponse("""
        <div class="p-8 text-center flex flex-col items-center justify-center h-full">
            <div class="mb-4 bg-green-500/20 p-4 rounded-full text-green-500 animate-bounce">
                <i class="ph ph-check-circle text-6xl"></i>
            </div>
            <h3 class="text-xl font-bold text-white mb-2">¡Enviado!</h3>
            <p class="text-slate-400 text-sm mb-6">Tu pago está en revisión.</p>
            
            <button onclick="window.closeNeuralUI()" class="w-full bg-slate-700 hover:bg-slate-600 text-white py-3 rounded-lg font-bold transition-colors">
                Cerrar
            </button>
        </div>
    """)

# --- ADMIN: LISTAR PENDIENTES ---
@router.get("/finance/admin/pending")
async def get_pending_payments(
    request: Request, 
    db: Session = Depends(get_db), 
    admin: Member = Depends(get_current_member)
):
    if admin.role != "admin": return ""
    payments = db.query(Payment).filter(Payment.organization_id == admin.organization_id, Payment.status == "review").order_by(Payment.created_at.desc()).all()
    return templates.TemplateResponse("components/admin_payment_list.html", {"request": request, "payments": payments})

# --- ADMIN: APROBAR PAGO (Con Notificación) ---
@router.post("/finance/payment/{payment_id}/approve")
async def approve_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_current_member)
):
    if admin.role != "admin": return "Error"

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment or payment.status != 'review': return "Inválido"

    # 1. Actualizar estado
    payment.status = "approved"
    payment.reviewed_by = admin.id
    payment.reviewed_at = datetime.now(timezone.utc)

    # 2. Imputación FIFO
    pending_debts = db.query(Debt).filter(
        Debt.member_id == payment.member_id,
        Debt.status == "pending"
    ).order_by(asc(Debt.due_date)).all()

    remaining = payment.amount
    for debt in pending_debts:
        if remaining <= 0: break
        if remaining >= debt.balance:
            remaining -= debt.balance
            debt.balance = 0
            debt.status = "paid"
        else:
            debt.balance -= remaining
            remaining = 0
            
    db.commit()

    # 3. NOTIFICAR AL VECINO (AQUÍ ESTÁ LO QUE FALTABA)
    await manager.broadcast({
        "type": "PAYMENT_UPDATE",
        "user_id": payment.member.user_id, # ID del usuario dueño de la membresía
        "status": "approved",
        "msg": f"✅ Pago de S/ {payment.amount} APROBADO."
    })

    return HTMLResponse('<div class="bg-green-900/50 text-green-300 p-2 rounded text-center text-xs">Aprobado</div>')

# --- ADMIN: RECHAZAR PAGO (Con Notificación) ---
@router.post("/finance/payment/{payment_id}/reject")
async def reject_payment(
    payment_id: int,
    reason: str = Form(...),
    db: Session = Depends(get_db),
    admin: Member = Depends(get_current_member)
):
    if admin.role != "admin": return "Error"

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment: return "No encontrado"

    payment.status = "rejected"
    payment.rejection_reason = reason
    payment.reviewed_by = admin.id
    payment.reviewed_at = datetime.now(timezone.utc)
    
    db.commit()

    # NOTIFICAR AL VECINO (AQUÍ TAMBIÉN)
    await manager.broadcast({
        "type": "PAYMENT_UPDATE",
        "user_id": payment.member.user_id,
        "status": "rejected",
        "msg": f"❌ Pago rechazado: {reason}"
    })

    return HTMLResponse('<div class="bg-red-900/50 text-red-300 p-2 rounded text-center text-xs">Rechazado</div>')

# --- VECINO: COMPONENTE DE DEUDA ---
@router.get("/finance/my-summary")
async def get_my_summary(
    request: Request, 
    db: Session = Depends(get_db), 
    member: Member = Depends(get_current_member)
):
    total_debt = db.query(func.sum(Debt.balance)).filter(
        Debt.member_id == member.id,
        Debt.status == "pending"
    ).scalar() or 0.0

    status_color = "blue"
    if total_debt > 0: status_color = "red"
    
    return templates.TemplateResponse("components/finance_card.html", {
        "request": request, "total_debt": total_debt, "status_color": status_color, "currency": "S/"
    })

# --- VECINO: DETALLE DE DEUDAS Y PAGOS ---
@router.get("/finance/my-debts-detail")
async def get_my_debts_detail(request: Request, db: Session = Depends(get_db), member: Member = Depends(get_current_member)):
    debts = db.query(Debt).filter(Debt.member_id == member.id).order_by(Debt.status.desc(), Debt.due_date).all()
    payments = db.query(Payment).filter(Payment.member_id == member.id).order_by(Payment.created_at.desc()).limit(10).all()
    
    return templates.TemplateResponse("components/finance_debt_list.html", {
        "request": request, "debts": debts, "payments": payments
    })


# 1. Endpoint para entregar el FORMULARIO LIMPIO
@router.get("/finance/payment/form")
async def get_payment_form(request: Request, amount: str = None, concept: str = None):
    val_amount = amount if amount else ""
    
    return HTMLResponse(f"""
        <div class="bg-slate-900 text-white rounded-2xl shadow-2xl border border-slate-700 w-full overflow-hidden relative">
            <!-- Cabecera -->
            <div class="bg-gradient-to-r from-green-600 to-emerald-600 p-5 flex justify-between items-start sticky top-0 z-10">
                <div>
                    <h3 class="text-xl font-bold text-white leading-none">Reportar Pago</h3>
                    <p class="text-green-100 text-xs mt-1 opacity-90">Sube tu comprobante.</p>
                </div>
                
                <!-- BOTÓN CERRAR CORRECTO (Llama a NeuralUI) -->
                <button type="button" onclick="window.closeNeuralUI()" 
                        class="text-white/80 hover:text-white hover:bg-white/10 rounded-full p-1 transition-colors -mr-2 -mt-2">
                    <i class="ph ph-x text-2xl"></i>
                </button>
            </div>
            
            <!-- Formulario (Target = a sí mismo o un div de éxito) -->
            <form hx-post="/finance/payment/report" 
                hx-swap="innerHTML" 
                enctype="multipart/form-data"
                class="p-6 space-y-4">
            
            <!-- Feedback IA (Oculto) -->
            <div id="ai-analyzing" class="hidden bg-indigo-900/30 border border-indigo-500/50 p-2 rounded text-xs text-indigo-300 gap-2 mb-2 items-center">
                <i class="ph ph-spinner animate-spin"></i> <span>Leyendo voucher...</span>
            </div>

            <!-- 1. MONTO -->
            <div>
                <label class="block text-xs text-slate-400 mb-1 uppercase">Monto (S/)</label>
                <input type="number" id="input-amount" name="amount" value="{val_amount}" step="0.01" required placeholder="0.00"
                       class="w-full bg-black border border-slate-700 rounded-lg p-3 text-white font-bold text-lg focus:border-green-500 outline-none transition-colors">
            </div>

            <!-- 2. MÉTODO DE PAGO -->
            <div>
                <label class="block text-xs text-slate-400 mb-1 uppercase">Método</label>
                <div class="grid grid-cols-2 gap-2">
                    <label class="cursor-pointer">
                        <input type="radio" name="method" value="Yape" class="peer hidden" checked>
                        <div class="bg-slate-800 peer-checked:bg-purple-600 peer-checked:text-white py-2 px-4 rounded text-center text-xs border border-slate-700 transition-all font-bold">Yape / Plin</div>
                    </label>
                    <label class="cursor-pointer">
                        <input type="radio" name="method" value="Transferencia" class="peer hidden">
                        <div class="bg-slate-800 peer-checked:bg-blue-600 peer-checked:text-white py-2 px-4 rounded text-center text-xs border border-slate-700 transition-all font-bold">Transferencia</div>
                    </label>
                </div>
            </div>

            <!-- 3. CÓDIGO OPERACIÓN -->
            <div>
                <label class="block text-xs text-slate-400 mb-1 uppercase">Código Operación</label>
                <input type="text" id="input-operation" name="operation_code" placeholder="Ej: 123456"
                       class="w-full bg-black border border-slate-700 rounded-lg p-3 text-white font-mono tracking-widest focus:border-green-500 outline-none">
            </div>
            
            <!-- 4. VOUCHER -->
             <div>
                <label class="block text-xs text-slate-400 mb-1 uppercase">Voucher (Foto)</label>
                <input type="file" name="voucher" accept="image/*" onchange="if(window.analizarVoucher) window.analizarVoucher(this)"
                       class="w-full text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-slate-800 file:text-white hover:file:bg-slate-700 cursor-pointer">
            </div>

            <!-- BOTONES -->
            <div class="flex gap-2 pt-4 border-t border-slate-800">
                <button type="button" onclick="window.closeModal()" class="flex-1 py-3 rounded-xl font-bold text-slate-500 hover:bg-slate-800 transition-colors">Cancelar</button>
                <button type="submit" class="flex-1 bg-green-600 hover:bg-green-500 text-white font-bold py-3 rounded-xl shadow-lg transition-transform active:scale-95 flex items-center justify-center gap-2">
                    <i class="ph ph-paper-plane-right text-lg"></i> ENVIAR
                </button>
            </div>
        </form>
    </div>
    """)


@router.post("/finance/payment/analyze-voucher")
async def analyze_voucher(
    voucher: UploadFile = File(...),
    db: Session = Depends(get_db),
    member: Member = Depends(get_current_member)
):
    print("🧠 Analizando voucher con IA...")
    
    # 1. Leer imagen y convertir a Base64
    contents = await voucher.read()
    base64_image = base64.b64encode(contents).decode('utf-8')

    # USAR LA CLAVE DIRECTA
    #print("🔑 Cargando clave API..."+ os.getenv("OPENAI_API_KEY"))
    
    print("🔑 Clave API cargada." + api_key)

     # Validación de seguridad
    if not api_key:
        print("❌ Error: No se encontró OPENAI_API_KEY")
        return {"status": "error", "msg": "Error de configuración (Falta API Key)"}

    client = OpenAI(api_key=api_key)
    
    # 2. Preparar Cliente OpenAI
    #client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # 3. Prompt para Visión
    prompt = """
    Analiza esta imagen de un comprobante de pago (Yape, Plin, Transferencia BCP/Interbank/BBVA).
    Extrae estrictamente en formato JSON:
    - "amount": El monto total (número decimal, sin símbolo de moneda).
    - "operation_code": El número de operación o ID de transacción.
    - "date": La fecha y hora si es visible (formato YYYY-MM-DD HH:MM), si no, null.
    - "bank": El nombre del banco o billetera digital detectada.
    
    Si no encuentras algún dato, pon null. No inventes.
    Responde SOLO el JSON.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # O gpt-4o si necesitas más precisión
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{voucher.content_type};base64,{base64_image}"
                            },
                        },
                    ],
                }
            ],
            max_tokens=300,
        )
        
        # Limpiar respuesta (a veces GPT pone ```json ... ```)
        content = response.choices[0].message.content.replace("```json", "").replace("```", "")
        data = json.loads(content)

        #print("🔑 Cargando clave API xxxx..."+ os.getenv("OPENAI_API_KEY"))
        #print("🔑 Clave API cargada.xxxxx" + api_key)

        return {"status": "ok", "data": data}

    except Exception as e:
        print(f"Error IA Voucher: {e}")
        return {"status": "error", "msg": "No se pudo leer el voucher. Ingrese datos manualmente."}