import os
import secrets
import smtplib
import string
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from io import BytesIO
from urllib.parse import urlencode
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import qrcode
import requests
from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from flask_sqlalchemy import SQLAlchemy
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# -----------------------------------------------------------------------------
# Configuración base del proyecto
# -----------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
QRCODE_DIR = os.path.join(BASE_DIR, "static", "qrcodes")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/auth/google/callback")

# Creamos las carpetas necesarias para fotos y QR al iniciar la app.
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(QRCODE_DIR, exist_ok=True)


def ensure_default_assets():
    """Crea imágenes por defecto si la primera ejecución no tiene archivos."""
    default_file = os.path.join(UPLOAD_DIR, "default-user.png")
    if not os.path.exists(default_file):
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (500, 500), color=(228, 232, 240))
        draw = ImageDraw.Draw(img)
        draw.ellipse((150, 90, 350, 310), fill=(162, 169, 181))
        draw.rounded_rectangle((120, 320, 380, 440), radius=36, fill=(162, 169, 181))
        img.save(default_file)

    if not os.listdir(QRCODE_DIR):
        sample = qrcode.make("QR-company-demo")
        sample.save(os.path.join(QRCODE_DIR, "sample-qr.png"))


ensure_default_assets()

# -----------------------------------------------------------------------------
# Inicialización de Flask y SQLAlchemy
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = "qr-company-secret-2026"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "company_db.sqlite3")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# -----------------------------------------------------------------------------
# Modelos de base de datos
# -----------------------------------------------------------------------------
class Company(db.Model):
    __tablename__ = "companies"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    profile_image = db.Column(db.String(255), default="/static/uploads/default-user.png")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employees = db.relationship("Employee", backref="company", lazy=True, cascade="all, delete-orphan")


class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    employee_code = db.Column(db.String(50), unique=True, nullable=False)
    municipio = db.Column(db.String(100), nullable=False, default="N/A")
    qr_code_url = db.Column(db.String(255), nullable=False)
    image_url = db.Column(db.String(255), default="/static/uploads/default-user.png")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    attendance = db.relationship("Attendance", backref="employee", lazy=True, cascade="all, delete-orphan")


class Attendance(db.Model):
    __tablename__ = "attendance"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)
    entry_time = db.Column(db.Time, nullable=True)
    exit_time = db.Column(db.Time, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def ensure_company_profile_columns():
    """Asegura columnas extras para el perfil del administrador en SQLite existentes."""
    inspector = db.session.execute(db.text("PRAGMA table_info(companies)"))
    columns = [row[1] for row in inspector.fetchall()]

    if "profile_image" not in columns:
        db.session.execute(db.text("ALTER TABLE companies ADD COLUMN profile_image VARCHAR(255) DEFAULT '/static/uploads/default-user.png'"))
        db.session.commit()


with app.app_context():
    # Esto crea las tablas si aún no existen.
    db.create_all()
    ensure_company_profile_columns()


# -----------------------------------------------------------------------------
# Lista de municipios para usar en el formulario de empleados
# -----------------------------------------------------------------------------
MUNICIPIOS = [
    "Aguascalientes",
    "Baja California",
    "Baja California Sur",
    "Campeche",
    "Chiapas",
    "Chihuahua",
    "Ciudad de México",
    "Coahuila",
    "Colima",
    "Durango",
    "Guanajuato",
    "Guerrero",
    "Hidalgo",
    "Jalisco",
    "Estado de México",
    "Michoacán",
    "Morelos",
    "Nayarit",
    "Nuevo León",
    "Oaxaca",
    "Puebla",
    "Querétaro",
    "Quintana Roo",
    "San Luis Potosí",
    "Sinaloa",
    "Sonora",
    "Tabasco",
    "Tamaulipas",
    "Tlaxcala",
    "Veracruz",
    "Yucatán",
    "Zacatecas",
]


# -----------------------------------------------------------------------------
# Funciones auxiliares
# -----------------------------------------------------------------------------
def generate_random_code():
    """Genera un código aleatorio único para cada empleado."""
    while True:
        code = "EMP-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        if not Employee.query.filter_by(employee_code=code).first():
            return code


def google_login_is_configured():
    """Regresa True si ya se configuró OAuth de Google."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def send_verification_email(recipient_email, code):
    """Envía el código de verificación por correo. Si no hay SMTP configurado, solo lo imprime en consola."""
    smtp_server = os.getenv("MAIL_SERVER", "localhost")
    smtp_port = int(os.getenv("MAIL_PORT", "587"))
    smtp_username = os.getenv("MAIL_USERNAME")
    smtp_password = os.getenv("MAIL_PASSWORD")
    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    default_from = os.getenv("MAIL_FROM", "noreply@qrcompany.local")

    message = EmailMessage()
    message["Subject"] = "Verifica tu cuenta de QR Company"
    message["From"] = default_from
    message["To"] = recipient_email
    message.set_content(
        f"Tu código de verificación es: {code}\n"
        "Ingresa ese número en la pantalla de confirmación para terminar el registro."
    )

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            if use_tls:
                server.starttls()
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.send_message(message)
        return True
    except Exception as exc:
        print(f"[EMAIL] No se pudo enviar el correo: {exc}")
        print(f"[EMAIL] Código de prueba para {recipient_email}: {code}")
        return False


def save_uploaded_file(file_storage):
    """Guarda la foto del empleado y devuelve la ruta que Flask usará en la plantilla."""
    if not file_storage or file_storage.filename == "":
        return "/static/uploads/default-user.png"

    filename = secure_filename(file_storage.filename)
    name, ext = os.path.splitext(filename)
    unique_name = f"{name}-{secrets.token_hex(4)}{ext or '.png'}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    file_storage.save(file_path)
    return f"/static/uploads/{unique_name}"




def generate_qr_code(employee_code, employee_name):
    """Genera la imagen QR con código + nombre para identificar al empleado."""
    qr_payload = f"{employee_code}|{employee_name}"
    image_name = f"{employee_code}-{secrets.token_hex(4)}.png"
    image_path = os.path.join(QRCODE_DIR, image_name)
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(qr_payload)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#111827", back_color="white")
    qr_img.save(image_path)
    return f"/static/qrcodes/{image_name}"


# -----------------------------------------------------------------------------
# Rutas de autenticación y páginas principales
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register-company", methods=["GET", "POST"])
def register_company():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not name or not email or not password:
            flash("Completa todos los campos.", "error")
            return redirect(url_for("register_company"))

        if Company.query.filter_by(email=email).first():
            flash("Este correo ya está registrado.", "error")
            return redirect(url_for("register_company"))

        new_company = Company(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
        )
        db.session.add(new_company)
        db.session.commit()

        verification_code = "".join(secrets.choice(string.digits) for _ in range(6))
        session["pending_company_id"] = new_company.id
        session["pending_company_name"] = new_company.name
        session["pending_company_email"] = email
        session["pending_verification_code"] = verification_code

        send_verification_email(email, verification_code)
        flash("Se envió un código de verificación a tu correo. Ingresa el número para terminar el registro.", "success")
        return redirect(url_for("verify_company_email"))

    return render_template("register.html", page_title="Registrar empresa")


@app.route("/verify-company-email", methods=["GET", "POST"])
def verify_company_email():
    if "pending_company_id" not in session:
        flash("Primero completa el registro de tu empresa.", "error")
        return redirect(url_for("register_company"))

    if request.method == "POST":
        entered_code = request.form.get("code", "").strip()
        stored_code = session.get("pending_verification_code", "")

        if entered_code == stored_code:
            session["company_id"] = session["pending_company_id"]
            session["company_name"] = session["pending_company_name"]
            session.pop("pending_company_id", None)
            session.pop("pending_company_name", None)
            session.pop("pending_company_email", None)
            session.pop("pending_verification_code", None)
            flash("Correo verificado. Tu empresa ya quedó activa.", "success")
            return redirect(url_for("dashboard"))

        flash("El código ingresado no es válido. Intenta de nuevo.", "error")

    return render_template("verify_email.html", email=session.get("pending_company_email"))


@app.route("/login/google")
def login_google():
    """Redirige a Google para iniciar sesión con OAuth2."""
    if not google_login_is_configured():
        flash("Google OAuth no está configurado. Configura GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en tu entorno.", "error")
        return redirect(url_for("login"))

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return redirect(auth_url)


@app.route("/auth/google/callback")
def google_callback():
    """Recibe el código de Google y crea o identifica la empresa."""
    if not google_login_is_configured():
        flash("Google OAuth no está configurado.", "error")
        return redirect(url_for("login"))

    code = request.args.get("code")
    if not code:
        flash("No se recibió el código de Google.", "error")
        return redirect(url_for("login"))

    token_payload = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    token_response = requests.post("https://oauth2.googleapis.com/token", data=token_payload)
    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        flash("No se pudo obtener el token de Google.", "error")
        return redirect(url_for("login"))

    user_info_response = requests.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    user_info = user_info_response.json()
    email = (user_info.get("email") or "").strip().lower()
    name = (user_info.get("name") or email.split("@", 1)[0] or "Empresa").strip()

    if not email:
        flash("Google no devolvió un correo válido.", "error")
        return redirect(url_for("login"))

    company = Company.query.filter_by(email=email).first()
    if not company:
        company = Company(
            name=name,
            email=email,
            password_hash=generate_password_hash(secrets.token_urlsafe(16)),
        )
        db.session.add(company)
        db.session.commit()

    session["company_id"] = company.id
    session["company_name"] = company.name
    flash("Sesión iniciada con Google.", "success")
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        company = Company.query.filter_by(email=email).first()
        if company and check_password_hash(company.password_hash, password):
            session["company_id"] = company.id
            session["company_name"] = company.name
            flash("Bienvenido de nuevo.", "success")
            return redirect(url_for("dashboard"))

        flash("Credenciales incorrectas.", "error")
        return redirect(url_for("login"))

    return render_template("login.html", page_title="Iniciar sesión")


@app.route("/logout")
def logout():
    session.clear()
    flash("Cerrando sesión...", "success")
    return redirect(url_for("index"))


@app.route("/dashboard/profile", methods=["POST"])
def update_profile():
    """Actualiza nombre e imagen del perfil del administrador."""
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    company = Company.query.get_or_404(session["company_id"])
    new_name = request.form.get("admin_name", "").strip()
    profile_image = request.files.get("profile_image")

    if new_name:
        company.name = new_name

    if profile_image and profile_image.filename:
        company.profile_image = save_uploaded_file(profile_image)

    db.session.commit()
    session["company_name"] = company.name
    flash("Perfil actualizado correctamente.", "success")
    return redirect(url_for("dashboard"))


# -----------------------------------------------------------------------------
# Dashboard principal
# -----------------------------------------------------------------------------
@app.route("/dashboard")
def dashboard():
    """Prepara toda la información del panel con empleados, resumen y asistencias."""
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    company = Company.query.get_or_404(session["company_id"])
    employees = Employee.query.filter_by(company_id=company.id).order_by(Employee.created_at.desc()).all()

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    summary = {
        "employees": len(employees),
        "present_today": 0,
        "records_today": Attendance.query.join(Employee).filter(Employee.company_id == company.id, Attendance.attendance_date == today).count(),
        "pending": 0,
    }

    for employee in employees:
        employee_attendance = Attendance.query.filter_by(employee_id=employee.id, attendance_date=today).first()
        if employee_attendance and employee_attendance.entry_time:
            summary["present_today"] += 1
        if employee_attendance and not employee_attendance.exit_time:
            summary["pending"] += 1

    employee_week = []
    for employee in employees:
        row = {
            "employee": employee,
            "days": {},
            "present_count": 0,
        }
        for current_day in week_dates:
            entry = Attendance.query.filter_by(employee_id=employee.id, attendance_date=current_day).first()
            row["days"][current_day.isoformat()] = entry
            if entry and entry.entry_time:
                row["present_count"] += 1
        employee_week.append(row)

    last_employee = employees[0] if employees else None
    return render_template(
        "dashboard.html",
        company=company,
        employees=employees,
        summary=summary,
        week_dates=week_dates,
        employee_week=employee_week,
        last_employee=last_employee,
        today=today,
        municipios=MUNICIPIOS,
    )


# -----------------------------------------------------------------------------
# Gestión de empleados
# -----------------------------------------------------------------------------
@app.route("/dashboard/add-employee", methods=["POST"])
def add_employee():
    """Registra un empleado, genera su QR y abre su credencial."""
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip()
    municipio = request.form.get("municipio", "N/A").strip()
    photo = request.files.get("photo")

    if not name:
        flash("El nombre del empleado es obligatorio.", "error")
        return redirect(url_for("dashboard"))

    if not municipio:
        municipio = "N/A"

    try:
        employee_code = generate_random_code()
        image_url = save_uploaded_file(photo)
        qr_code_url = generate_qr_code(employee_code, name)

        employee = Employee(
            company_id=session["company_id"],
            name=name,
            employee_code=employee_code,
            municipio=municipio,
            qr_code_url=qr_code_url,
            image_url=image_url,
        )

        db.session.add(employee)
        db.session.commit()

        flash(
            f"Trabajador {employee.name} registrado correctamente. "
            f"Código: {employee.employee_code}",
            "success",
        )

        return redirect(
            url_for("employee_credential", employee_id=employee.id)
        )

    except Exception as exc:
        db.session.rollback()
        print(f"[ADD EMPLOYEE] Error: {exc}")
        flash(
            "No se pudo registrar el trabajador. "
            "Revisa la consola para más detalles.",
            "error",
        )
        return redirect(url_for("dashboard"))


# -----------------------------------------------------------------------------
# Registro de asistencia por entrada/salida
# -----------------------------------------------------------------------------
@app.route("/attendance/scan", methods=["POST"])
def scan_attendance():
    """Registra la entrada o salida del empleado usando su código QR o código manual."""
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    employee_code = request.form.get("employee_code", "").strip().upper()
    mode = (request.form.get("mode", "") or "").strip().lower()

    employee = Employee.query.filter_by(employee_code=employee_code, company_id=session["company_id"]).first()
    if not employee:
        flash("Código de empleado no encontrado.", "error")
        return redirect(url_for("dashboard"))

    today = date.today()
    record = Attendance.query.filter_by(employee_id=employee.id, attendance_date=today).first()
    now_time = datetime.now().time()

    if record is None:
        record = Attendance(employee_id=employee.id, attendance_date=today)

    if not mode:
        if record.entry_time and record.exit_time:
            flash(f"{employee.name} ya completó su jornada de hoy.", "error")
            return redirect(url_for("dashboard"))
        mode = "entry" if not record.entry_time else "exit"

    if mode == "entry":
        if record.entry_time:
            flash(f"La entrada de {employee.name} ya fue registrada hoy.", "error")
            return redirect(url_for("dashboard"))
        record.entry_time = now_time
        message = f"Entrada registrada para {employee.name}."
    else:
        if not record.entry_time:
            flash(f"Primero debe registrar la entrada de {employee.name}.", "error")
            return redirect(url_for("dashboard"))
        if record.exit_time:
            flash(f"La salida de {employee.name} ya fue registrada hoy.", "error")
            return redirect(url_for("dashboard"))
        record.exit_time = now_time
        message = f"Salida registrada para {employee.name}."

    db.session.add(record)
    db.session.commit()
    flash(message, "success")
    return redirect(url_for("dashboard"))


# -----------------------------------------------------------------------------
# Vistas de credenciales y exportación
# -----------------------------------------------------------------------------
@app.route("/employee/<int:employee_id>/credential")
def employee_credential(employee_id):
    """Muestra la credencial del empleado con foto, código y QR."""
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    employee = Employee.query.filter_by(id=employee_id, company_id=session["company_id"]).first_or_404()
    return render_template("credential.html", employee=employee)


@app.route("/employee/<int:employee_id>/download-qr")
def employee_download_qr(employee_id):
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    employee = Employee.query.filter_by(id=employee_id, company_id=session["company_id"]).first_or_404()
    relative = employee.qr_code_url.replace("/static/", "")
    file_path = os.path.join(BASE_DIR, "static", relative)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name=f"{employee.employee_code}.png")
    flash("No se encontró el QR generado.", "error")
    return redirect(url_for("dashboard"))


@app.route("/employee/<int:employee_id>/download-credential-pdf")
def employee_download_credential_pdf(employee_id):
    """Genera una credencial tipo ID con diseño formal de empresa."""
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    employee = Employee.query.filter_by(id=employee_id, company_id=session["company_id"]).first_or_404()
    company_name = Company.query.get(session["company_id"]).name

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    card_title = Paragraph("Credencial de empleado", styles["Title"])
    story.append(card_title)
    story.append(Spacer(1, 18))

    photo_path = os.path.join(BASE_DIR, employee.image_url.strip("/"))
    qr_path = os.path.join(BASE_DIR, employee.qr_code_url.strip("/"))

    photo = Image(photo_path, width=84, height=84) if os.path.exists(photo_path) else Paragraph("Foto", styles["BodyText"]) 
    qr_image = Image(qr_path, width=142, height=142) if os.path.exists(qr_path) else Paragraph("QR", styles["BodyText"])

    info_table = Table(
        [
            [Paragraph("<b>Nombre</b>", styles["BodyText"]), Paragraph(employee.name, styles["BodyText"])],
            [Paragraph("<b>Código</b>", styles["BodyText"]), Paragraph(employee.employee_code, styles["BodyText"])],
            [Paragraph("<b>Municipio</b>", styles["BodyText"]), Paragraph(employee.municipio, styles["BodyText"])],
            [Paragraph("<b>Empresa</b>", styles["BodyText"]), Paragraph(company_name, styles["BodyText"])],
            [Paragraph("<b>Registro</b>", styles["BodyText"]), Paragraph(employee.created_at.strftime("%d/%m/%Y"), styles["BodyText"])],
        ],
        colWidths=[120, 260],
    )
    info_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7F9FF")),
            ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#DDE5F3")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 8),
        ])
    )

    main_card = Table(
        [
            [
                Paragraph("<b>QR Company</b>", styles["Heading2"]),
                Paragraph("CREDENCIAL", styles["BodyText"]),
            ],
            [
                Table(
                    [[photo, Paragraph("<b>" + employee.name + "</b>", styles["Heading1"])], [Paragraph("", styles["BodyText"])], [info_table]],
                    colWidths=[100, 280],
                ),
                qr_image,
            ],
        ],
        colWidths=[420, 120],
    )

    main_card.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#DDE5F3")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 12),
        ])
    )

    story.append(main_card)
    story.append(Spacer(1, 20))
    story.append(Paragraph("Autorizado por la empresa", styles["BodyText"]))

    doc.build(story)
    pdf_value = buffer.getvalue()
    buffer.close()
    return send_file(BytesIO(pdf_value), as_attachment=True, download_name=f"credencial-{employee.employee_code}.pdf", mimetype="application/pdf")


@app.route("/employee/<int:employee_id>/delete", methods=["POST"])
def delete_employee(employee_id):
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    employee = Employee.query.filter_by(id=employee_id, company_id=session["company_id"]).first_or_404()
    db.session.delete(employee)
    db.session.commit()
    flash("Empleado eliminado correctamente.", "success")
    return redirect(url_for("dashboard"))


@app.route("/dashboard/bitacora-diaria-pdf")
def daily_log_pdf():
    """Descarga la bitácora del día actual para seguimiento inmediato."""
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    company = Company.query.get_or_404(session["company_id"])
    employees = Employee.query.filter_by(company_id=company.id).order_by(Employee.name.asc()).all()
    today = date.today()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(f"Bitácora diaria - {company.name}", styles["Title"]))
    story.append(Paragraph(f"Fecha: {today.strftime('%d/%m/%Y')}", styles["BodyText"]))
    story.append(Spacer(1, 18))

    table_data = [["Empleado", "Código", "Municipio", "Entrada", "Salida", "Estado"]]
    for employee in employees:
        record = Attendance.query.filter_by(employee_id=employee.id, attendance_date=today).first()
        entry = record.entry_time.strftime("%H:%M") if record and record.entry_time else "—"
        exit_time = record.exit_time.strftime("%H:%M") if record and record.exit_time else "—"
        status = "Presente" if record and record.entry_time else "Sin registro"
        table_data.append([employee.name, employee.employee_code, employee.municipio, entry, exit_time, status])

    table = Table(table_data, colWidths=[150, 80, 100, 70, 70, 85])
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE7FF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#D8E1F0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFF")]),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 7),
        ])
    )
    story.append(table)
    doc.build(story)
    pdf_value = buffer.getvalue()
    buffer.close()
    return send_file(BytesIO(pdf_value), as_attachment=True, download_name=f"bitacora-diaria-{today.isoformat()}.pdf", mimetype="application/pdf")


@app.route("/dashboard/weekly-report-pdf")
def weekly_report_pdf():
    """Descarga la bitácora semanal con presencia por día."""
    if "company_id" not in session:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    company = Company.query.get_or_404(session["company_id"])
    employees = Employee.query.filter_by(company_id=company.id).order_by(Employee.name.asc()).all()
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(f"Bitácora semanal - {company.name}", styles["Title"]))
    story.append(Paragraph(f"Periodo: {week_dates[0].strftime('%d/%m/%Y')} - {week_dates[-1].strftime('%d/%m/%Y')}", styles["BodyText"]))
    story.append(Spacer(1, 18))

    table_data = [["Empleado", "Municipio", "Código", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]]
    for employee in employees:
        row = [employee.name, employee.municipio, employee.employee_code]
        for current_day in week_dates:
            entry = Attendance.query.filter_by(employee_id=employee.id, attendance_date=current_day).first()
            row.append("✓" if entry and entry.entry_time else "-")
        table_data.append(row)

    table = Table(table_data, repeatRows=1, colWidths=[120, 80, 70, 35, 35, 35, 35, 35, 35, 35])
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE7FF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#DDE3EE")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FF")]),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("PADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(table)

    doc.build(story)
    pdf_value = buffer.getvalue()
    buffer.close()
    return send_file(BytesIO(pdf_value), as_attachment=True, download_name=f"bitacora-semanal-{company.name.lower().replace(' ', '-')}.pdf", mimetype="application/pdf")

if __name__ == "__main__":
    app.run(debug=True)
