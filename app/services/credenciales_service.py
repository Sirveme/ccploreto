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
        organization_id: int,
        colegiado_id: int
    ):

        organizacion = (

            self.db

            .query(Organization)

            .filter(
                Organization.id == organization_id
            )

            .first()

        )

        if organizacion is None:

            return None

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

            return None

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

            return None

        return {

            "organization": organizacion,

            "template": template,

            "colegiado": colegiado

        }