from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Colegiado,
    Organization
)

from app.models_credenciales import CredentialTemplate


class CredencialesService:

    def __init__(self, db: Session):

        self.db = db


    def obtener_contexto_credencial(
        self,
        request,
        colegiado_id: int
    ):

        org = getattr(request.state, "org", None)

        if org is None:

            raise HTTPException(
                status_code=500,
                detail="Middleware no encontró la organización."
            )

        organization_id = org["id"]

        template = (

            self.db

            .query(CredentialTemplate)

            .filter(
                CredentialTemplate.organization_id == organization_id,
                CredentialTemplate.activa == True
            )

            .first()

        )

        if template is None:

            raise HTTPException(
                status_code=500,
                detail=f"No existe plantilla para organization_id={organization_id}"
            )

        colegiado = (

            self.db

            .query(Colegiado)

            .filter(
                Colegiado.id == colegiado_id,
                Colegiado.organization_id == organization_id
            )

            .first()

        )

        if colegiado is None:

            raise HTTPException(
                status_code=404,
                detail=f"No existe colegiado id={colegiado_id}"
            )

        organization = (

            self.db

            .query(Organization)

            .filter(
                Organization.id == organization_id
            )

            .first()

        )

        if organization is None:

            raise HTTPException(
                status_code=500,
                detail=f"No existe organization id={organization_id}"
            )

        return {

            "request": request,

            "organization": organization,

            "template": template,

            "colegiado": colegiado

        }