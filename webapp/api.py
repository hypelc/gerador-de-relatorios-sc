"""Site sem persistência: a planilha é reenviada na inspeção e na geração."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import tempfile
import threading
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Annotated
from xml.etree.ElementTree import ParseError

import openpyxl
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openpyxl.utils.exceptions import InvalidFileException
from starlette.concurrency import run_in_threadpool

from gerador_sc.engine import ReportService
from gerador_sc.models import ReportConfig, ReportValidationError
from gerador_sc.regional import (
    RegionalConfig,
    normalize_name,
    read_values,
    render_regional_report,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = ROOT / "frontend" / "dist"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
VERSION = "0.1.0"
_render_lock = threading.Lock()
_rate_lock = threading.Lock()
_rate_events: dict[str, list[float]] = {}


def _limit(request: Request, action: str, maximum: int, window_seconds: int) -> None:
    address = request.client.host if request.client else "unknown"
    key = f"{action}:{address}"
    now = time.monotonic()
    with _rate_lock:
        recent = [
            when for when in _rate_events.get(key, ()) if now - when < window_seconds
        ]
        if len(recent) >= maximum:
            raise HTTPException(
                429,
                "Muitas tentativas em pouco tempo. Aguarde alguns minutos e tente novamente.",
            )
        recent.append(now)
        _rate_events[key] = recent
        if len(_rate_events) > 1000:
            for old_key, events in list(_rate_events.items()):
                if not events or now - events[-1] > window_seconds:
                    _rate_events.pop(old_key, None)


def _secrets() -> tuple[str, str]:
    password = os.environ.get("APP_ACCESS_PASSWORD", "")
    secret = os.environ.get("APP_SESSION_SECRET", "")
    if len(password) < 12 or len(secret) < 32:
        raise HTTPException(503, "Acesso ainda nao configurado no servidor.")
    return password, secret


def _session_token(password: str, secret: str) -> str:
    expires = int(time.time()) + 12 * 60 * 60
    nonce = secrets.token_urlsafe(12)
    payload = f"{expires}.{nonce}"
    signature = hmac.new(
        secret.encode(), f"{payload}.{password}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}"


def _authenticated(request: Request) -> bool:
    token = request.cookies.get("gerador_session", "")
    parts = token.split(".")
    if len(parts) != 3:
        return False
    try:
        expires = int(parts[0])
    except ValueError:
        return False
    if expires < time.time():
        return False
    try:
        password, secret = _secrets()
    except HTTPException:
        return False
    payload = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(
        secret.encode(), f"{payload}.{password}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(parts[2], expected)


def _require_auth(request: Request) -> None:
    if not _authenticated(request):
        raise HTTPException(401, "Entre com a senha para usar o gerador.")


def _safe_name(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1]
    if not name or Path(name).suffix.lower() not in {".xlsx", ".csv"}:
        raise HTTPException(400, "Escolha uma planilha .xlsx ou .csv.")
    return name


def _copy_upload(upload: UploadFile, directory: Path) -> Path:
    name = _safe_name(upload.filename)
    destination = directory / name
    size = 0
    with destination.open("wb") as target:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "A planilha ultrapassa o limite de 10 MB.")
            target.write(chunk)
    if size == 0:
        raise HTTPException(400, "A planilha enviada está vazia.")
    if destination.suffix.lower() == ".xlsx":
        try:
            with zipfile.ZipFile(destination) as workbook:
                files = workbook.infolist()
                if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(
                    {item.filename for item in files}
                ):
                    raise HTTPException(
                        400, "O arquivo .xlsx não contém uma pasta de trabalho válida."
                    )
                if (
                    len(files) > 500
                    or sum(item.file_size for item in files) > MAX_UNPACKED_BYTES
                ):
                    raise HTTPException(
                        413, "A planilha expandida é grande demais para esta versão."
                    )
        except zipfile.BadZipFile as error:
            raise HTTPException(
                400,
                "O arquivo .xlsx está danificado ou não é uma planilha Excel válida.",
            ) from error
    return destination


def _is_regional(path: Path) -> bool:
    if path.suffix.lower() == ".xlsx":
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            first = workbook.active.cell(1, 1).value
        finally:
            workbook.close()
    else:
        raw = path.read_text(encoding="utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(raw[:4096], delimiters=";,\t")
        except csv.Error:
            dialect = csv.excel
        first = next(csv.reader(io.StringIO(raw), dialect), [""])[0]
    return normalize_name(str(first or "")) == "REGIONAIS"


def _inspect(path: Path) -> dict[str, object]:
    if _is_regional(path):
        values, state_value, indicator, sheet = read_values(path)
        suggested_title = (
            "Distribuição da taxa de profissionais segundo Regionais de Saúde"
            if normalize_name(indicator) == "TAXA DE PROFISSIONAIS"
            else f"Distribuição espacial: {indicator}"
        )
        return {
            "kind": "regional",
            "filename": path.name,
            "sheet": sheet,
            "indicator": indicator,
            "regions": [
                {"name": label, "value": value} for label, value in values.values()
            ],
            "state_value": state_value,
            "models": ["mapa_regional"],
            "suggested_title": suggested_title,
            "notes": [
                "A planilha não informa automaticamente unidade nem período. Confira esses campos antes de gerar."
            ],
        }
    result = ReportService().inspect(path)
    if not result.valid_tables:
        diagnostics = [diagnostic.to_dict() for diagnostic in result.diagnostics]
        raise HTTPException(
            422,
            {
                "message": "Nenhuma tabela anual válida foi encontrada.",
                "diagnostics": diagnostics,
            },
        )
    return {
        "kind": "annual",
        "filename": path.name,
        "import": result.to_dict(),
        "models": ["paineis", "linhas", "mapa"],
    }


def _text(value: object, field: str, maximum: int = 180) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise HTTPException(422, f"Campo {field} inválido ou longo demais.")
    return re.sub(r"\s+", " ", value).strip()


def _filename(title: str, extension: str) -> str:
    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:60]
    return f"{slug or 'relatorio'}.{extension}"


def _generate(path: Path, options: dict[str, object]) -> tuple[bytes, str, str]:
    kind = options.get("kind")
    title = _text(options.get("title", ""), "título", 120)
    if not title:
        raise HTTPException(422, "Informe o título do relatório.")
    authors = _text(options.get("authors", ""), "autores")
    source = _text(options.get("source", ""), "fonte")
    unit = _text(options.get("unit", ""), "unidade", 80)
    with tempfile.TemporaryDirectory(prefix="gerador-web-output-") as temporary:
        directory = Path(temporary)
        if kind == "regional":
            if not _is_regional(path):
                raise HTTPException(
                    422,
                    "A planilha enviada não corresponde ao modelo das 17 Regionais.",
                )
            output_format = options.get("format", "pdf")
            if output_format not in {"pdf", "png"}:
                raise HTTPException(422, "Formato de saída desconhecido.")
            period = _text(options.get("period", ""), "período", 80)
            pdf_path = directory / "relatorio.pdf"
            png_path = directory / "relatorio.png"
            with _render_lock:
                render_regional_report(
                    path,
                    pdf_path,
                    png_path,
                    RegionalConfig(title, authors, source, unit, period),
                )
            target = pdf_path if output_format == "pdf" else png_path
            media_type = "application/pdf" if output_format == "pdf" else "image/png"
            return target.read_bytes(), media_type, _filename(title, output_format)
        if kind != "annual" or _is_regional(path):
            raise HTTPException(
                422, "O modelo selecionado não corresponde à planilha enviada."
            )
        result = ReportService().inspect(path)
        table_ids = options.get("table_ids")
        years = options.get("years")
        confirmed_exclusions = options.get("confirmed_exclusions", [])
        model = options.get("model", "paineis")
        if (
            not isinstance(table_ids, list)
            or not all(isinstance(item, str) for item in table_ids)
            or len(table_ids) > 30
        ):
            raise HTTPException(422, "Seleção de tabelas inválida.")
        if (
            not isinstance(years, list)
            or not all(
                isinstance(item, int) and not isinstance(item, bool) for item in years
            )
            or len(years) > 50
        ):
            raise HTTPException(422, "Seleção de anos inválida.")
        if not isinstance(confirmed_exclusions, list) or not all(
            isinstance(item, str) for item in confirmed_exclusions
        ):
            raise HTTPException(422, "Confirmação de exclusões inválida.")
        if model not in {"paineis", "linhas", "mapa"}:
            raise HTTPException(422, "Modelo de gráfico desconhecido.")
        config = ReportConfig(
            tuple(table_ids),
            model,
            tuple(years),
            title,
            authors,
            source,
            _text(options.get("indicator_name", ""), "indicador", 80),
            unit,
            _text(options.get("palette", "Acessivel"), "paleta", 40),
            tuple(confirmed_exclusions),
            "web",
        )
        service = ReportService()
        artifact = None
        try:
            with _render_lock:
                artifact = service.preview(result, config)
            return (
                artifact.pdf_path.read_bytes(),
                "application/pdf",
                _filename(title, "pdf"),
            )
        except ReportValidationError as error:
            raise HTTPException(
                422,
                {
                    "message": "Revise as escolhas antes de gerar.",
                    "diagnostics": [item.to_dict() for item in error.diagnostics],
                },
            ) from error
        finally:
            service.cleanup(artifact)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Gerador de Relatórios SC",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": VERSION}

    @app.get("/api/session")
    def session(request: Request) -> dict[str, bool]:
        return {"authenticated": _authenticated(request)}

    @app.post("/api/login")
    def login(
        request: Request, payload: dict[str, str], response: Response
    ) -> dict[str, bool]:
        _limit(request, "login", 12, 10 * 60)
        password, secret = _secrets()
        supplied = payload.get("password", "") if isinstance(payload, dict) else ""
        if not hmac.compare_digest(supplied, password):
            raise HTTPException(401, "Senha incorreta.")
        response.set_cookie(
            "gerador_session",
            _session_token(password, secret),
            max_age=12 * 60 * 60,
            httponly=True,
            secure=os.environ.get("APP_ENV") != "local",
            samesite="strict",
            path="/",
        )
        return {"authenticated": True}

    @app.post("/api/logout", dependencies=[Depends(_require_auth)])
    def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie("gerador_session", path="/")
        return {"authenticated": False}

    @app.post("/api/inspect", dependencies=[Depends(_require_auth)])
    async def inspect(request: Request, file: Annotated[UploadFile, File()]):
        _limit(request, "inspect", 30, 60)
        with tempfile.TemporaryDirectory(prefix="gerador-web-upload-") as temporary:
            path = await run_in_threadpool(_copy_upload, file, Path(temporary))
            try:
                return await run_in_threadpool(_inspect, path)
            except (
                UnicodeError,
                InvalidFileException,
                ParseError,
                zipfile.BadZipFile,
            ) as error:
                raise HTTPException(
                    422,
                    "Não foi possível ler a planilha. Verifique se o arquivo está íntegro e, no caso de CSV, salvo em UTF-8.",
                ) from error
            except ValueError as error:
                raise HTTPException(422, str(error)) from error

    @app.post("/api/generate", dependencies=[Depends(_require_auth)])
    async def generate(
        request: Request,
        file: Annotated[UploadFile, File()],
        options: Annotated[str, Form()],
    ):
        _limit(request, "generate", 12, 60)
        try:
            config = json.loads(options)
        except json.JSONDecodeError as error:
            raise HTTPException(422, "Configuração do relatório inválida.") from error
        if not isinstance(config, dict):
            raise HTTPException(422, "Configuração do relatório inválida.")
        with tempfile.TemporaryDirectory(prefix="gerador-web-upload-") as temporary:
            path = await run_in_threadpool(_copy_upload, file, Path(temporary))
            try:
                contents, media_type, filename = await run_in_threadpool(
                    _generate, path, config
                )
            except (
                UnicodeError,
                InvalidFileException,
                ParseError,
                zipfile.BadZipFile,
            ) as error:
                raise HTTPException(
                    422,
                    "Não foi possível ler a planilha. Verifique se o arquivo está íntegro e, no caso de CSV, salvo em UTF-8.",
                ) from error
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
        return Response(
            contents,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if FRONTEND_DIST.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets"
        )

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
