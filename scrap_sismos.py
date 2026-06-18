import requests
from bs4 import BeautifulSoup
import boto3
import uuid
import re

def lambda_handler(event, context):
    # URL oficial indicada para los reportes sísmicos del IGP
    url = "https://ultimosismo.igp.gob.pe/productos/reportes-sismicos"
    
    # User-Agent estándar para simular una petición de navegador y evitar bloqueos por seguridad
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return {
                'statusCode': response.status_code,
                'body': f'Error al acceder a la página del IGP: Código {response.status_code}'
            }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': f'Error en la solicitud HTTP hacia el IGP: {str(e)}'
        }

    soup = BeautifulSoup(response.content, 'html.parser')
    sismos_detectados = []

    # --- ESTRATEGIA 1: Extracción mediante Tabla Estándar ---
    table = soup.find('table')
    if table:
        headers_text = [th.text.strip() for th in table.find_all('th')]
        rows = table.find_all('tr')[1:]  # Omitir la fila de cabecera
        
        for row in rows:
            cells = [td.text.strip() for td in row.find_all('td')]
            if not cells:
                continue
                
            sismo_dict = {}
            for i, cell_value in enumerate(cells):
                header_name = headers_text[i] if i < len(headers_text) else f"columna_{i}"
                # Sanitizar nombres de columnas para que sean nombres de atributos válidos en DynamoDB
                attr_name = re.sub(r'[^a-zA-Z0-9_]', '_', header_name).strip('_')
                sismo_dict[attr_name] = cell_value
            
            if sismo_dict:
                sismos_detectados.append(sismo_dict)

    # --- ESTRATEGIA 2: Fallback por Bloques de Texto (Regex) ---
    if not sismos_detectados:
        text_content = soup.get_text()
        # Dividir el texto en bloques individuales que comiencen con "Cod reporte:"
        reports = re.findall(r'(Cod reporte:.*?)(?=Cod reporte:|$)', text_content, re.DOTALL)
        
        for item in reports:
            sismo_dict = {}
            cod_match = re.search(r'Cod reporte:\s*(.*)', item)
            ref_match = re.search(r'Referencia:\s*(.*)', item)
            mag_match = re.search(r'Magnitud:\s*(.*)', item)
            fecha_match = re.search(r'Fecha y hora de origen local:\s*(.*)', item)
            
            if cod_match: sismo_dict['Cod_reporte'] = cod_match.group(1).strip()
            if ref_match: sismo_dict['Referencia'] = ref_match.group(1).strip()
            if mag_match: sismo_dict['Magnitud'] = mag_match.group(1).strip()
            if fecha_match: sismo_dict['Fecha_hora_local'] = fecha_match.group(1).strip()
            
            if sismo_dict:
                sismos_detectados.append(sismo_dict)

    # Requerimiento estricto: Seleccionar los últimos 10 sismos reportados
    10_ultimos_sismos = sismos_detectados[:10]

    if not 10_ultimos_sismos:
        return {
            'statusCode': 404,
            'body': 'No se logró extraer ni estructurar información de sismos de la página web'
        }

    # --- Almacenamiento en DynamoDB ---
    dynamodb = boto3.resource('dynamodb')
    table_db = dynamodb.Table('TablaSismosIGP')

    # Limpiar registros previos de la tabla para mantenerla actualizada (siguiendo el patrón del Taller 2)
    try:
        scan = table_db.scan()
        with table_db.batch_writer() as batch:
            for each in scan.get('Items', []):
                batch.delete_item(Key={'id': each['id']})
    except Exception:
        pass  # Si la tabla está recién creada o vacía, ignorar el error de limpieza

    # Insertar los nuevos registros procesados
    datos_guardados = []
    for idx, sismo in enumerate(10_ultimos_sismos, start=1):
        item_data = {
            'id': str(uuid.uuid4()),
            '_numero_registro': idx
        }
        # Agregar los pares clave-valor extraídos
        for k, v in sismo.items():
            if k and v:
                item_data[k] = v
                
        table_db.put_item(Item=item_data)
        datos_guardados.append(item_data)

    return {
        'statusCode': 200,
        'body': datos_guardados
    }
