# QR Company - Control de asistencia y empleados

Aplicación web en Flask para registrar empresas, registrar empleados, generar credenciales con QR, controlar asistencia por entrada y salida y visualizar un dashboard tipo Gmail.

## Características

- Registro de empresa con correo y contraseña
- Inicio de sesión de empresa
- Registro de empleados con nombre y foto opcional
- Generación automática de código de empleado
- Generación automática de código QR por empleado
- Vista de credencial con código QR configurable
- Descarga del QR/credencial
- Registro de asistencia con entrada y salida
- Dashboard con resumen y vista semanal de asistencia
- Lista de trabajadores registrados
- Diseño responsivo y estilo similar a Gmail

## Requisitos

- Python 3.10 o superior
- Windows, Linux o macOS
- Git (opcional)

## 1) Abrir la carpeta del proyecto

Abre la carpeta del proyecto en la terminal:

```bash
cd "C:\Users\secto\OneDrive\Desktop\qr.py"
```

## 2) Crear entorno virtual

En Windows PowerShell:

```powershell
py -m venv .venv
```

Activarlo:

```powershell
.\.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea la ejecución, usa:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 3) Instalar dependencias

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 4) Ejecutar la aplicación

```powershell
python app.py
```

Luego abre en tu navegador:

```text
http://127.0.0.1:5000
```

## 5) Flujo normal del sistema

1. Abre la página principal.
2. Registra tu empresa.
3. Inicia sesión con el correo y contraseña que registraste.
4. En el dashboard, agrega empleados.
5. El sistema genera automáticamente:
   - nombre del empleado
   - código de empleado
   - código QR
6. Usa el escáner de asistencia para registrar entrada o salida por código.
7. Consulta la credencial y descarga el QR.

## Estructura del proyecto

```text
qr.py/
├── app.py
├── requirements.txt
├── README.md
├── static/
│   ├── css/
│   ├── qrcodes/
│   └── uploads/
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── credential.html
│   └── ...
└── company_db.sqlite3
```

## Nota importante

La base de datos se crea automáticamente al iniciar la app en SQLite. Los archivos de imágenes y QR se generan en las carpetas `static/uploads` y `static/qrcodes` si no existen.

## Si quieres detener la app

En la terminal presiona:

```text
Ctrl + C
```

## Sugerencia para desarrollo

Puedes usar este comando para arrancar con auto-reload:

```powershell
python app.py
```

La app ya está configurada con `debug=True`, por lo que Flask reiniciará al detectar cambios en el código.
