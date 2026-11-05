import io

import pytest
from docx import Document
from pps_api.service import Service


@pytest.fixture
def document():
    doc = Document()
    doc.add_paragraph("Los administradores deben tener bloqueo de cuenta.")
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


@pytest.fixture
def service(tmp_path):
    return Service(tmp_path / "api.sqlite3")
