import io
import os
from datetime import datetime, timedelta
from flask import send_file, request, current_app
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib import colors

from . import controllers
from .calendar_view import choose_utils
from models import apartament_maintenance_path, apartament_weekday_calendar_starts, apartament_type
from utils import parameters

# --- FUNCIONES AUXILIARES DE FECHA Y TEXTO ---

def get_week_date_ranges(weekday_start, maintenance_path, fraction, apartment):
    """
    Obtiene los rangos de fechas para 8 años PROYECTADOS a partir de 2028.
    """
    apt_type = apartament_type.get(apartment, "regular")
    idx_maker, _, _ = choose_utils(apartment)
    
    all_weeks = []
    
    # REGLA: Iniciar proyección en 2028
    # Para 'Regular': Enero 2028 - Dic 2035
    # Para 'Snow': Ciclo Sept 2028 - Sept 2036
    base_year = 2028
    
    # Recolectar 8 años de datos
    for i in range(8):
        current_loop_year = base_year + i
        
        # Generamos el calendario matemático para ese año
        # idx_maker ya sabe si es snow/sand y cómo manejar su ciclo interno
        frac_idx = idx_maker(current_loop_year, weekday_start, maintenance_path)
        
        # Ordenar fechas cronológicamente
        sorted_dates = sorted(frac_idx.keys())
        current_week_dates = []
        
        # El backend usa 0 para la fracción 8, aseguramos la comparación
        target_fraction = 0 if fraction == 8 else fraction

        for date_obj in sorted_dates:
            frac_list = frac_idx[date_obj]
            
            # Verificar si la fracción coincide
            if frac_list and frac_list[0] == target_fraction:
                if not current_week_dates:
                    current_week_dates.append(date_obj)
                elif (date_obj - current_week_dates[-1]).days == 1:
                    current_week_dates.append(date_obj)
                else:
                    # Se rompió la continuidad, guardar semana anterior si es válida
                    if len(current_week_dates) >= 5: 
                        all_weeks.append((
                            current_week_dates[0],
                            current_week_dates[-1],
                            current_week_dates[0].year
                        ))
                    current_week_dates = [date_obj]
        
        # Agregar la última semana pendiente del año
        if len(current_week_dates) >= 5:
            all_weeks.append((
                current_week_dates[0],
                current_week_dates[-1],
                current_week_dates[0].year
            ))
            
    return all_weeks

def format_date_short_spanish(date_obj):
    """Convierte fecha a formato corto español: '05 ene 2028'"""
    months_es_short = [
        '', 'ene', 'feb', 'mar', 'abr', 'may', 'jun',
        'jul', 'ago', 'sep', 'oct', 'nov', 'dic'
    ]
    # Aseguramos dos dígitos para el día
    day_str = str(date_obj.day).zfill(2)
    return f"{day_str} {months_es_short[date_obj.month]} {date_obj.year}"

# --- FUNCIONES DE DIBUJO DEL PDF (MANUAL CANVAS) ---

def draw_header_and_footer(pdf, width, height, apartment, display_fraction, page_num):
    """Dibuja el encabezado y el disclaimer legal en cada página"""
    
    # 1. LOGO (Esquina Superior Derecha)
    try:
        logo_path = os.path.join(current_app.root_path, 'static', 'seascape_logo_pdf.png')
        if os.path.exists(logo_path):
            # Ajuste de tamaño y posición del logo
            pdf.drawImage(logo_path, width - 2.5*inch, height - 1.0*inch, 
                          width=2*inch, height=0.66*inch, mask='auto', preserveAspectRatio=True)
    except Exception:
        pass # Si falla el logo, no romper el PDF

    # 2. TÍTULOS (Esquina Superior Izquierda)
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(0.8*inch, height - 0.8*inch, "ASIGNACIÓN PROYECTADA DE SEMANAS")
    
    pdf.setFont("Helvetica", 10)
    pdf.drawString(0.8*inch, height - 1.0*inch, f"Apartamento {apartment} - Fracción {display_fraction}")
    pdf.drawString(0.8*inch, height - 1.2*inch, "Periodo Estimado: 2028 - 2035")

    # 3. DISCLAIMER (Pie de Página)
    pdf.setFont("Helvetica", 7)
    pdf.setFillColor(colors.grey)
    
    # Línea separadora
    pdf.setStrokeColor(colors.lightgrey)
    pdf.line(0.8*inch, 0.7*inch, width - 0.8*inch, 0.7*inch)
    
    # Texto legal
    disclaimer_lines = [
        "NOTA LEGAL: El presente documento es una proyección informativa basada en una fecha estimada de entrega (Enero 2028).",
        "Las semanas y fechas aquí mostradas son tentativas y están sujetas a la fecha real de inicio de operaciones del condominio,",
        "así como a las disposiciones finales del Régimen de Propiedad en Condominio. No constituye una obligación legal definitiva."
    ]
    
    text_y = 0.55 * inch
    for line in disclaimer_lines:
        pdf.drawCentredString(width / 2, text_y, line)
        text_y -= 9 
        
    # Número de página
    pdf.drawRightString(width - 0.8*inch, 0.55*inch, f"Pág. {page_num}")

def draw_table_header(pdf, x, y, col_widths):
    """Dibuja la fila de encabezados de la tabla"""
    # Fondo Azul Oscuro
    pdf.setFillColor(colors.HexColor('#2c3e50'))
    pdf.rect(x, y - 0.25 * inch, sum(col_widths), 0.25 * inch, fill=True, stroke=False)
    
    # Texto Blanco
    pdf.setFillColor(colors.whitesmoke)
    pdf.setFont("Helvetica-Bold", 9)
    
    headers = ["Año Fiscal", "Semana", "Fecha Inicio", "Fecha Fin"]
    current_x = x
    for i, header in enumerate(headers):
        pdf.drawCentredString(current_x + col_widths[i] / 2, y - 0.17 * inch, header)
        current_x += col_widths[i]
    
    pdf.setFillColor(colors.black)

def draw_table_row(pdf, x, y, row_data, col_widths, is_even):
    """Dibuja una fila de datos de la tabla"""
    # Fondo alternado (Gris claro para pares)
    if is_even:
        pdf.setFillColor(colors.HexColor('#f8f9fa'))
        pdf.rect(x, y - 0.22 * inch, sum(col_widths), 0.22 * inch, fill=True, stroke=False)
        pdf.setFillColor(colors.black)
    
    # Bordes
    pdf.setStrokeColor(colors.lightgrey)
    pdf.setLineWidth(0.5)
    pdf.rect(x, y - 0.22 * inch, sum(col_widths), 0.22 * inch, fill=False, stroke=True)
    
    # Texto
    pdf.setFont("Helvetica", 9)
    current_x = x
    for i, data in enumerate(row_data):
        pdf.drawCentredString(current_x + col_widths[i] / 2, y - 0.15 * inch, str(data))
        current_x += col_widths[i]

# --- RUTAS DE FLASK ---

@controllers.route('/preview_pdf')
def preview_pdf():
    """Genera la página HTML con el iframe para previsualizar el PDF"""
    apartment = request.args.get('apartament', 205, type=int)
    fraction = request.args.get('fraction', type=int)
    
    if fraction is None:
        return "Error: No fraction specified", 400
    
    display_fraction = 8 if fraction == 0 else fraction
    
    # HTML incrustado
    html = f'''
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Proyección - Depto {apartment} Fracción {display_fraction}</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background-color: #525659;
                overflow: hidden;
            }}
            .pdf-container {{
                width: 100vw;
                height: 100vh;
                display: flex;
                flex-direction: column;
            }}
            iframe {{
                flex-grow: 1;
                width: 100%;
                border: none;
            }}
            .print-button {{
                position: fixed;
                bottom: 30px;
                right: 30px;
                background: #e85d04;
                color: white;
                border: none;
                padding: 15px 30px;
                font-size: 16px;
                font-weight: 600;
                border-radius: 50px;
                cursor: pointer;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                display: flex;
                align-items: center;
                gap: 10px;
                transition: transform 0.2s;
                z-index: 1000;
            }}
            .print-button:hover {{
                transform: scale(1.05);
                background: #ff6b10;
            }}
        </style>
    </head>
    <body>
        <div class="pdf-container">
            <iframe src="/generate_pdf?apartament={apartment}&fraction={fraction}" type="application/pdf"></iframe>
        </div>
        <button class="print-button" onclick="printPDF()">
            <span>🖨️ Imprimir Documento</span>
        </button>
        
        <script>
            function printPDF() {{
                const iframe = document.querySelector('iframe');
                try {{
                    iframe.contentWindow.focus();
                    iframe.contentWindow.print();
                }} catch (e) {{
                    window.print();
                }}
            }}
        </script>
    </body>
    </html>
    '''
    return html

@controllers.route('/generate_pdf')
def generate_pdf():
    # 1. Obtener parámetros
    apartment = request.args.get('apartament', 205, type=int)
    fraction = request.args.get('fraction', type=int)
    
    if fraction is None:
        return "Error: No fraction specified", 400
    
    # Ajuste visual: Fracción 0 en backend es la 8
    display_fraction = 8 if fraction == 0 else fraction
    
    # 2. Obtener configuración del modelo
    maintenance_path = apartament_maintenance_path.get(apartment, 1)
    weekday_start = apartament_weekday_calendar_starts.get(apartment, 1)
    
    # 3. Obtener fechas (Proyección 8 años desde 2028)
    weeks = get_week_date_ranges(weekday_start, maintenance_path, fraction, apartment)
    
    # 4. Configurar Canvas PDF
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # --- CONFIGURACIÓN DE TABLA ---
    # Márgenes y anchos
    col_widths = [1.2 * inch, 1.2 * inch, 2.25 * inch, 2.25 * inch]
    # Centrar la tabla en el ancho disponible
    table_width = sum(col_widths)
    table_x = (width - table_width) / 2
    
    # Filas por página
    rows_per_page = 32
    
    # Variables de bucle
    current_page = 1
    row_index = 0
    
    # --- BUCLE DE PÁGINAS ---
    while row_index < len(weeks):
        # Dibujar Encabezado y Footer en cada página
        draw_header_and_footer(pdf, width, height, apartment, display_fraction, current_page)
        
        # Posición Y inicial para la tabla (debajo del encabezado)
        y = height - 1.6 * inch
        
        # Dibujar encabezados de tabla
        draw_table_header(pdf, table_x, y, col_widths)
        y -= 0.25 * inch
        
        # Dibujar filas
        rows_drawn = 0
        while rows_drawn < rows_per_page and row_index < len(weeks):
            start_date, end_date, year = weeks[row_index]
            week_num = start_date.isocalendar()[1]
            
            # Formatear datos
            row_data = [
                str(year),
                f"Sem {week_num}",
                format_date_short_spanish(start_date),
                format_date_short_spanish(end_date)
            ]
            
            # Dibujar fila
            draw_table_row(pdf, table_x, y, row_data, col_widths, row_index % 2 == 0)
            
            y -= 0.22 * inch
            rows_drawn += 1
            row_index += 1
        
        # Finalizar página
        pdf.showPage()
        current_page += 1
    
    # Guardar PDF
    pdf.save()
    buffer.seek(0)
    
    # --- NOMBRE DE ARCHIVO PERSONALIZADO ---
    # Formato: OSC_COM_Apt<Num>_Fraccion<Num>_Semanas_<YYYYMMDD>
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"OSC_COM_Apt{apartment}_Fraccion{display_fraction}_Semanas_{date_str}.pdf"
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=False, # False para que se vea en el iframe
        download_name=filename
    )