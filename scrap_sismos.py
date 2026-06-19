import requests
import boto3
import uuid

def lambda_handler(event, context):
    # URL y parametros de consulta para la API de ArcGIS del IGP
    api_url = "https://ide.igp.gob.pe/arcgis/rest/services/monitoreocensis/SismosReportados/MapServer/0/query"
    params = {
        "where": "1=1",
        "outFields": "objectid,code,fecha,hora,lat,lon,prof,profundidad,magnitud,mag,ref,int_,departamento",
        "orderByFields": "objectid DESC",
        "resultRecordCount": 50,
        "f": "json"
    }

    # 1. Solicitud HTTP y obtencion de datos
    try:
        response = requests.get(api_url, params=params, timeout=10)
        if response.status_code != 200:
            return {
                'statusCode': response.status_code,
                'body': f'Error en la API del IGP: Codigo de estado {response.status_code}'
            }
        data = response.json()
    except requests.exceptions.RequestException as e:
        return {
            'statusCode': 502,
            'body': f'Error de red o timeout al conectar con el IGP: {str(e)}'
        }
    except ValueError:
        return {
            'statusCode': 502,
            'body': 'La respuesta de la API del IGP no es un JSON valido'
        }

    # 2. Validacion y extraccion de caracteristicas
    features = data.get("features", [])
    if not features:
        return {
            'statusCode': 404,
            'body': 'No se encontraron registros de sismos en la respuesta'
        }

    # 3. Procesamiento y estructuracion de datos
    rows = []
    for feature in features:
        attrs = feature.get("attributes", {})
        code = str(attrs.get("code") or "").strip()
        
        if not code:
            continue
            
        sismo = {
            "code": "IGP/CENSIS/RS " + code,
            "fecha": str(attrs.get("fecha") or "").strip(),
            "hora": str(attrs.get("hora") or "").strip(),
            "latitud": str(attrs.get("lat") or "").strip(),
            "longitud": str(attrs.get("lon") or "").strip(),
            "prof_km": str(attrs.get("prof") or "").strip(),
            "profundidad": str(attrs.get("profundidad") or "").strip(),
            "magnitud": str(attrs.get("magnitud") or "").strip(),
            "mag": str(attrs.get("mag") or "").strip(),
            "referencia": str(attrs.get("ref") or "").strip(),
            "intensidad": str(attrs.get("int_") or "").strip(),
            "departamento": str(attrs.get("departamento") or "").strip()
        }
        rows.append(sismo)
        
        if len(rows) == 10:
            break

    if not rows:
        return {
            'statusCode': 422,
            'body': 'Ningun registro cumplio con los criterios de validacion necesarios'
        }

    # 4. Operaciones de persistencia en DynamoDB
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('TablaSismosIGP')

        # Escanear la tabla y eliminar los elementos existentes
        scan = table.scan()
        with table.batch_writer() as batch:
            for each in scan.get('Items', []):
                batch.delete_item(
                    Key={
                        'id': each['id']
                    }
                )

        # Insertar los nuevos registros con indices correlativos
        i = 1
        for row in rows:
            row['#'] = i
            row['id'] = str(uuid.uuid4())
            table.put_item(Item=row)
            i = i + 1

    except Exception as e:
        return {
            'statusCode': 500,
            'body': f'Error interno al procesar o almacenar en DynamoDB: {str(e)}'
        }

    # 5. Respuesta exitosa
    return {
        'statusCode': 200,
        'body': rows
    }
