# Corpus de la Knowledge Base: manifiesto y procedimiento

Fecha: 2026-11-21; actualizado el 2026-11-22 (referencias técnicas propias,
ingesta `U36DLBRGFV`). Rama: `feature/bedrock-knowledge-base`. Este documento
lista los documentos de referencia cargados en el bucket de conocimiento, su
origen, sus condiciones de uso y las conversiones aplicadas, y describe cómo
repetir la carga. El estado del RAG y el resultado de la ingesta están en el
[resumen de trabajo](README.md).

Los documentos de terceros **no se versionan en este repositorio**: viven en
el bucket privado de conocimiento y en una copia local fuera del repositorio
con la misma estructura de carpetas. Aquí solo se registran sus datos.

## 1. Criterios

- **Versión del equipo.** El equipo auditado ejecuta FortiOS 7.6.8. La
  documentación de Fortinet se cargó en la edición 7.6.x más cercana que
  publica el fabricante (comprobado en docs.fortinet.com el 2026-11-21): la
  referencia de CLI existe para 7.6.8; la guía de buenas prácticas solo para
  7.6.0.
- **Formatos.** Según la documentación de AWS consultada el 2026-11-21
  ([requisitos de los datos](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-ds.html),
  [conector S3 administrado](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-s3.html)),
  se admiten `.txt`, `.md`, `.html`, `.doc`/`.docx`, `.csv`, `.xls`/`.xlsx` y
  `.pdf`, los tres primeros en UTF-8. El conector administrado ingiere
  archivos de hasta 500 MB (valor configurado en el origen de datos); la
  página general de requisitos indica 50 MB por archivo. El archivo más
  grande del corpus pesa 6,1 MB.
- **Texto sin alterar.** Un documento se convierte solo cuando su formato no
  se admite o no cumple la codificación exigida. La conversión conserva el
  texto completo; cada una está descrita en la sección 4.
- **Nombres.** Claves en ASCII, sin espacios, con un prefijo por emisor o
  jurisdicción: `fortinet/`, `nist/`, `disa/`, `argentina/`, `espana/` y
  `propio/`.
- **Normas vigentes.** No se cargan normas derogadas (ver sección 5).

## 2. Documentos cargados

31 documentos y 9 archivos de metadatos; 23,77 MB en total (23.766.209
bytes) al 2026-11-22, después de retirar la guía de FortiOS 8.0.0 y de agregar
las siete referencias técnicas propias. La columna
«Conversión» remite a la sección 4; «ninguna» significa que el objeto es
idéntico byte a byte al archivo publicado por el emisor.

### Fortinet

Documentos con derechos de autor de Fortinet, Inc. («All rights reserved»),
publicados sin registro en docs.fortinet.com. Se usan como material de
consulta interno y no comercial del proyecto; las condiciones que lo permiten
fueron informadas en el encargo y no se verificaron en esta tarea. Los avisos
de copyright de cada documento se conservan íntegros y los archivos no se
redistribuyen fuera del bucket privado.

| Clave | Título | Versión y fecha | Fuente | Conversión |
|---|---|---|---|---|
| `fortinet/FortiOS-7.6.0-Best_Practices.pdf` | FortiOS Best Practices | FortiOS 7.6.0; edición del 14/09/2026 | <https://fortinetweb.s3.amazonaws.com/docs.fortinet.com/v2/attachments/c0e909b9-2fef-11ef-8c42-fa163e15d75b/FortiOS-7.6.0-Best_Practices.pdf> | Ninguna |
| `fortinet/FortiOS-7.6.8-CLI_Reference-extracto.pdf` | FortiOS CLI Reference (extracto) | FortiOS 7.6.8; edición del 22/10/2026 | <https://fortinetweb.s3.amazonaws.com/docs.fortinet.com/v2/attachments/1c34e924-cbe3-11f1-8c5a-8e4c95ff11ac/FortiOS-7.6.8-CLI_Reference.pdf> | 4.1 |

La guía «Best Practices» de FortiOS 8.0.0
(`fortinet/FortiOS-8.0.0-Best_Practices.pdf`), cargada el 2026-11-18 cuando la
versión del equipo no se conocía, se retiró del bucket el 2026-11-21 junto con
su archivo de metadatos: no corresponde al equipo auditado (FortiOS 7.6.8) y
competía en la recuperación con la guía de 7.6.0. La ingesta `L0GF2MB3YJ`
sincronizó el índice después del retiro.

### NIST

Obras del gobierno federal de los Estados Unidos, sin derechos de autor en
ese país (17 U.S.C. § 105) y de distribución libre con atribución a NIST.

| Clave | Título | Versión y fecha | Fuente | Conversión |
|---|---|---|---|---|
| `nist/NIST.CSWP.29-CSF-2.0.pdf` | The NIST Cybersecurity Framework (CSF) 2.0 | CSWP 29; febrero de 2024 | <https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf> | Ninguna |
| `nist/NIST.SP.800-41r1-Firewalls.pdf` | Guidelines on Firewalls and Firewall Policy | SP 800-41 Rev. 1; septiembre de 2009 | <https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-41r1.pdf> | Ninguna |
| `nist/NIST.SP.800-52r2-TLS.pdf` | Guidelines for the Selection, Configuration, and Use of TLS Implementations | SP 800-52 Rev. 2; agosto de 2019 | <https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-52r2.pdf> | Ninguna |
| `nist/NIST.SP.800-53r5.pdf` | Security and Privacy Controls for Information Systems and Organizations | SP 800-53 Rev. 5; septiembre de 2020 | <https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf> | Ninguna |
| `nist/NIST.SP.800-53r5-control-catalog.xlsx` | SP 800-53 Rev. 5 Control Catalog (planilla) | Rev. 5, publicación `upd1` de CSRC | <https://csrc.nist.gov/files/pubs/sp/800/53/r5/upd1/final/docs/sp800-53r5-control-catalog.xlsx> | Ninguna |
| `nist/NIST.CSF-PF-to-SP.800-53r5-mappings.xlsx` | Cybersecurity Framework and Privacy Framework to SP 800-53 Rev. 5 Mappings (planilla) | Publicación `upd1` de CSRC | <https://csrc.nist.gov/files/pubs/sp/800/53/r5/upd1/final/docs/csf-pf-to-sp800-53r5-mappings.xlsx> | Ninguna |
| `nist/NIST.SP.800-63B-4-Authentication.pdf` | Digital Identity Guidelines: Authentication and Authenticator Management | SP 800-63B-4; 2025 | <https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-63B-4.pdf> | Ninguna |
| `nist/NIST.SP.800-77r1-IPsec-VPN.pdf` | Guide to IPsec VPNs | SP 800-77 Rev. 1; junio de 2020 | <https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-77r1.pdf> | Ninguna |
| `nist/NIST.SP.800-92-Log-Management.pdf` | Guide to Computer Security Log Management | SP 800-92; septiembre de 2006 | <https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-92.pdf> | Ninguna |
| `nist/NIST.SP.800-113-SSL-VPN.pdf` | Guide to SSL VPNs | SP 800-113; julio de 2008 | <https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-113.pdf> | Ninguna |

### DISA

Guías STIG del paquete `U_FN_FortiGate_Firewall_Y26M10_STIG.zip`, marcadas
«UNCLASSIFIED». El archivo `U_Readme_SRG_and_STIG.pdf` del paquete (V3R6, 10
de junio de 2026) solo describe su contenido y no establece ninguna
restricción de distribución; el aviso `terms-of-use` de ambos benchmarks está
vacío; el documento «Overview» indica que quienes no tienen credenciales del
organismo obtienen la guía en el sitio público y que otras organizaciones
pueden usarla. Los requisitos están escritos para FortiOS en general, no para
una versión 7.6 en particular.

| Clave | Título | Versión y fecha | Fuente | Conversión |
|---|---|---|---|---|
| `disa/DISA-STIG-FortiGate-Firewall-V1R5.md` | Fortinet FortiGate Firewall Security Technical Implementation Guide | Versión 1, Release 5; benchmark del 30/09/2026; 29 reglas | <https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/U_FN_FortiGate_Firewall_Y26M10_STIG.zip> | 4.2 |
| `disa/DISA-STIG-FortiGate-Firewall-NDM-V1R6.md` | Fortinet FortiGate Firewall NDM Security Technical Implementation Guide | Versión 1, Release 6; benchmark del 30/09/2026; 60 reglas | El mismo paquete | 4.2 |

### Argentina

Textos normativos oficiales de acceso público, tomados de Infoleg
(Ministerio de Justicia), del Boletín Oficial y del Banco Central.

| Clave | Título | Versión y fecha | Fuente | Conversión |
|---|---|---|---|---|
| `argentina/DA-641-2021.html` | Decisión Administrativa 641/2021: requisitos mínimos de seguridad de la información para organismos del Sector Público Nacional | 25/06/2021 | <https://servicios.infoleg.gob.ar/infolegInternet/anexos/350000-354999/351345/norma.htm> | 4.3 |
| `argentina/DA-641-2021-Anexo-I.pdf` | DA 641/2021, Anexo I | 25/06/2021 | <https://servicios.infoleg.gob.ar/infolegInternet/anexos/350000-354999/351345/dea641.pdf> | Ninguna |
| `argentina/Disp-1-2022-DNCIB-Anexo-I-Modelo-Referencial-PSI.pdf` | Disposición 1/2022 de la Dirección Nacional de Ciberseguridad, Anexo I: Modelo Referencial de Política de Seguridad de la Información | Boletín Oficial del 16/02/2022 | Anexo del [aviso del Boletín Oficial](https://www.boletinoficial.gob.ar/detalleAviso/primera/257620/20220216?anexos=1); la URL exacta de descarga no quedó registrada | Ninguna |
| `argentina/Ley-25326-Proteccion-Datos-Personales.html` | Ley 25.326 de Protección de los Datos Personales | Texto actualizado de Infoleg, descargado el 2026-11-21 | <https://servicios.infoleg.gob.ar/infolegInternet/anexos/60000-64999/64790/texact.htm> | 4.3 |
| `argentina/Res-AAIP-47-2018.html` | Resolución 47/2018 de la Agencia de Acceso a la Información Pública: medidas de seguridad recomendadas | 2018 | <https://servicios.infoleg.gob.ar/infolegInternet/anexos/310000-314999/312662/norma.htm> | 4.3 |
| `argentina/Res-AAIP-47-2018-Anexos-I-II.pdf` | Resolución AAIP 47/2018, Anexos I y II | 2018 | Las 27 imágenes `res47*.jpg` de la misma carpeta de Infoleg | 4.4 |
| `argentina/BCRA-TO-Requisitos-minimos-riesgos-TI-SI.pdf` | BCRA: requisitos mínimos para la gestión y control de los riesgos de tecnología y seguridad de la información | Texto ordenado al 13/02/2026; última comunicación incorporada «A» 8401 | <https://www.bcra.gob.ar/Pdfs/Texord/t-rmgcti.pdf> | Ninguna |
| `argentina/Res-SIP-44-2023-Segunda-Estrategia-Nacional-Ciberseguridad.html` | Resolución 44/2023 de la Secretaría de Innovación Pública: Segunda Estrategia Nacional de Ciberseguridad | 01/09/2023 | <https://servicios.infoleg.gob.ar/infolegInternet/anexos/385000-389999/389245/norma.htm> | 4.3 |

### España

| Clave | Título | Versión y fecha | Fuente | Conversión |
|---|---|---|---|---|
| `espana/BOE-A-2022-7191-RD-311-2022-ENS.pdf` | Real Decreto 311/2022, de 3 de mayo, por el que se regula el Esquema Nacional de Seguridad | Texto consolidado; última modificación del 06/11/2024 | <https://www.boe.es/buscar/pdf/2022/BOE-A-2022-7191-consolidado.pdf> | Ninguna |

Texto consolidado publicado por la Agencia Estatal Boletín Oficial del
Estado. Las condiciones de reutilización del aviso legal del BOE no se
verificaron en esta tarea.

### Material propio

| Clave | Título | Versión y fecha | Fuente | Conversión |
|---|---|---|---|---|
| `propio/catalogo-endpoints-fortigate.md` | Catálogo de los 31 endpoints de FortiGate y qué se revisa en cada uno | Cargado el 2026-11-18 | Este proyecto | Ninguna |
| `propio/fortios-7.6.8-campos-api-rest-sistema-administracion.md` | FortiOS 7.6.8, campos reales de la API REST (cmdb) por endpoint: sistema y administración (`system_global`, `admins`, `admin_profiles`, `api_users`, `password_policy`, `ntp`, `dns`, `snmp_sysinfo`, `central_management`, `fortiguard`) | FortiOS 7.6.8 build 3744; 2026-11-22 | Este proyecto, equipo de laboratorio | 4.5 |
| `propio/fortios-7.6.8-campos-api-rest-red.md` | Ídem: red, alta disponibilidad y VDOM (`interfaces`, `vdom_settings`, `ha`, `static_routes`, `sdwan`, `dhcp_servers`) | Ídem | Ídem | 4.5 |
| `propio/fortios-7.6.8-campos-api-rest-registro.md` | Ídem: registro (`log_settings`, `log_syslogd`, `log_fortianalyzer`, `log_memory`) | Ídem | Ídem | 4.5 |
| `propio/fortios-7.6.8-campos-api-rest-firewall.md` | Ídem: políticas y direcciones (`firewall_policies`, `firewall_addresses`) | Ídem | Ídem | 4.5 |
| `propio/fortios-7.6.8-campos-api-rest-perfiles-seguridad.md` | Ídem: perfiles de seguridad (`ips_sensors`, `av_profiles`, `webfilter_profiles`, `ssl_ssh_profiles`) | Ídem | Ídem | 4.5 |
| `propio/fortios-7.6.8-campos-api-rest-vpn-usuarios.md` | Ídem: VPN y usuarios (`vpn_ipsec`, `vpn_ssl`, `local_users`, `ldap_servers`, `radius_servers`) | Ídem | Ídem | 4.5 |
| `propio/notas-auditoria-laboratorio-2026-11-22.md` | Notas de auditoría de PostureGuard: lecciones del laboratorio (lista vacía con `super_admin_readonly`, nombres de campo inexistentes, convención de rutas cmdb, tablas que pueden o no estar vacías, objeto frente a lista) | FortiOS 7.6.8 build 3744; 2026-11-22 | Este proyecto, equipo de laboratorio | 4.5 |

Los siete documentos del 2026-11-22 son **referencias técnicas, no
normativas**: cada uno lo declara en un aviso al comienzo, con la versión de
FortiOS y la fecha. No contienen valores de configuración, direcciones ni
datos de ninguna organización. Se cargaron con la ingesta `U36DLBRGFV` (ver
el [resumen de trabajo](README.md)).

## 3. Metadatos

Los documentos de Fortinet (tres al 2026-11-21; dos desde el retiro de la
guía de 8.0.0) y, desde el 2026-11-22, las siete referencias técnicas propias
de FortiOS 7.6.8 tienen un archivo `<documento>.metadata.json` junto a ellos,
con el atributo `fortios_version` que usa el filtro opcional del generador
(`KNOWLEDGE_BASE_FORTIOS_VERSION`):

| Documento | `fortios_version` |
|---|---|
| `fortinet/FortiOS-7.6.0-Best_Practices.pdf` | `7.6` |
| `fortinet/FortiOS-7.6.8-CLI_Reference-extracto.pdf` | `7.6` |
| `propio/fortios-7.6.8-campos-api-rest-*.md` (seis documentos) | `7.6` |
| `propio/notas-auditoria-laboratorio-2026-11-22.md` | `7.6` |

El valor es la rama de versión, no la versión exacta, para que un solo valor
de filtro alcance a los dos documentos de 7.6. Formato del archivo, según la
documentación del conector S3 administrado:

```json
{
  "metadataAttributes": {
    "fortios_version": {"value": {"type": "STRING", "stringValue": "7.6"}}
  }
}
```

Los demás documentos no llevan el atributo. El filtro es una igualdad: con
`KNOWLEDGE_BASE_FORTIOS_VERSION=7.6` la consulta devuelve solo los dos
documentos de Fortinet 7.6 y las siete referencias técnicas propias, y deja
fuera las normas, las guías de NIST y las STIG. La consulta con filtro no se
volvió a probar después de agregar las referencias propias. Antes de habilitarlo en el pipeline hay que decidir si ese es el
comportamiento buscado.

## 4. Conversiones aplicadas

### 4.1 Extracto de la referencia de CLI de FortiOS 7.6.8

El documento original tiene 4.092 páginas y 18,5 MB. Se cargaron solo los
comandos `config` de las áreas que audita el catálogo de endpoints: 561
páginas y 2,9 MB. Las páginas se copiaron sin modificar con `pypdf`, usando
los marcadores del propio PDF para ubicar cada comando; cada tramo llega
hasta la página donde empieza el comando siguiente. Se conservan la portada,
la página de información del documento, la introducción (páginas 1, 2 y 130 a
132 del original) y la página final con el aviso de copyright (4.092).

Páginas del original por comando:

| Comando | Páginas | Comando | Páginas |
|---|---|---|---|
| `antivirus profile` | 141-177 | `system ha` | 1603-1618 |
| `firewall address` | 455-462 | `system interface` | 1639-1713 |
| `firewall policy` | 537-564 | `system ntp` | 1895-1899 |
| `firewall ssl-ssh-profile` | 659-690 | `system password-policy` | 1900-1902 |
| `ips sensor` | 789-795 | `system sdwan` | 1967-1995 |
| `log disk setting` | 818-823 | `system settings` | 2000-2026 |
| `log fortianalyzer setting` | 839-844 | `system snmp community` | 2031-2041 |
| `log memory setting` | 908 | `system snmp sysinfo` | 2042-2044 |
| `log setting` | 913-918 | `system snmp user` | 2044-2051 |
| `log syslogd setting` | 931-935 | `user ldap` | 2144-2152 |
| `router static` | 1189-1192 | `user local` | 2152-2156 |
| `system accprofile` | 1400-1413 | `user password-policy` | 2159-2161 |
| `system admin` | 1414-1422 | `user radius` | 2166-2182 |
| `system api-user` | 1428-1430 | `user setting` | 2189-2194 |
| `system central-management` | 1456-1462 | `vpn ipsec phase1-interface` | 2288-2325 |
| `system dhcp server` | 1478-1490 | `vpn ipsec phase2-interface` | 2339-2353 |
| `system dns` | 1499-1502 | `vpn ssl settings` | 2359-2373 |
| `system fortiguard` | 1530-1540 | `webfilter profile` | 2501-2519 |
| `system global` | 1549-1600 | | |

Quedan fuera los demás comandos `config` y los capítulos `diagnose` y
`execute`. Si una auditoría necesita otro comando, se agrega su tramo y se
vuelve a cargar el extracto.

### 4.2 STIG de DISA: de XCCDF a Markdown

La Knowledge Base no admite XML. Cada benchmark `*-xccdf.xml` del paquete se
convirtió con `audit-engine/scripts/stig_to_markdown.py` a un Markdown con un
encabezado (identificador, emisor, versión, release, estado, cantidad de
reglas) y una sección por regla, separadas por una línea `---`. Cada sección
lleva el identificador del grupo (`V-…`), el de la regla (`SV-…`), el STIG
ID, la severidad con su categoría (CAT I, II o III), el SRG, los CCI, la
descripción (el campo `VulnDiscussion`), el texto de verificación y el texto
de corrección. Los textos de verificación y corrección se copian sin cambios
dentro de bloques delimitados.

El zip se extrajo en un directorio nuevo y vacío, comprobando que ninguna
ruta saliera de él. Del paquete no se cargaron el zip, las hojas de estilo,
los logotipos ni los PDF de presentación e historial de revisiones.

```bash
# Desde audit-engine/, con el XML ya extraído fuera del repositorio
../.venv/Scripts/python.exe -I scripts/stig_to_markdown.py <benchmark-xccdf.xml> <salida.md>
```

El script rechaza un XML que declare un DTD o entidades y no sobrescribe un
archivo existente. Sus tests están en
`audit-engine/tests/test_stig_to_markdown.py` y usan un benchmark sintético.

### 4.3 Páginas de Infoleg: HTML en UTF-8 sin elementos del sitio

Las cuatro páginas de Infoleg están en ISO-8859-1 o Windows-1252 y la
Knowledge Base exige HTML en UTF-8. Se guardaron como `.html` en UTF-8 con el
cuerpo de la norma tal como lo publica Infoleg; se quitaron los scripts de
analítica, el encabezado gráfico del sitio y las imágenes, y se agregó un
título y un comentario con la URL de origen. Para cada archivo se comprobó de
forma automática que el texto visible resultante es idéntico al del original.

Donde el original tenía una imagen quedó una nota entre corchetes que empieza
con «Nota del corpus» y nombra el archivo de imagen:

- Resolución AAIP 47/2018: 27 imágenes, que contienen los Anexos I y II (ver
  4.4).
- Resolución 44/2023: 6 imágenes, que son los encabezados y firmas de los
  anexos; no se cargaron.

### 4.4 Anexos de la Resolución AAIP 47/2018: imágenes reunidas en un PDF

Infoleg publica los Anexos I y II de esta resolución (las medidas de
seguridad recomendadas) como 27 imágenes JPEG y no como texto. Se
descargaron de la misma carpeta que la norma y se reunieron, en el orden de
la página, en un PDF de 27 páginas sin modificar las imágenes. El texto de
los anexos no fue transcripto: su recuperación depende de la extracción de
imágenes de la Knowledge Base (ver el resultado en el
[resumen de trabajo](README.md)).

### 4.5 Referencias técnicas propias de FortiOS 7.6.8 (2026-11-22)

No son una conversión de un documento de terceros: se generaron a partir de
dos salidas `shapes.json` del diagnóstico de solo lectura
(`audit-engine/scripts/diagnose_fortigate_local.py`) contra el FortiGate-VM
del laboratorio, FortiOS 7.6.8 build 3744. Esas salidas contienen solo nombres
de campo y tipos, sin valores del equipo. La primera cubre los 31 endpoints
con un usuario de API de perfil `super_admin_readonly`; la segunda cubre
`admins` y `api_users` con un usuario de perfil `super_admin`, porque con el
perfil de solo lectura esas dos tablas llegan vacías.

Los seis documentos de campos se generan de forma mecánica con
`_herramientas/build_fortios_fields.py`, guardado en la copia local del corpus
(no en este repositorio y no en el bucket). Por cada endpoint hay una sección
cuyo encabezado lleva la etiqueta y la ruta cmdb, con el tipo de respuesta
(objeto o lista) y la lista completa de campos; los campos de objetos anidados
y de elementos de listas se indican a un nivel de profundidad. Las listas
largas se parten en bloques de 40 campos y cada bloque repite el endpoint,
para que un fragmento conserve el nombre del endpoint junto a sus campos. El
mismo script escribe las notas de auditoría y comprueba contra las capturas
cada nombre de campo que las notas declaran inexistente o real.

```bash
# Con las dos capturas fuera del repositorio versionado
python -I <carpeta-del-corpus>/_herramientas/build_fortios_fields.py   <carpeta-del-corpus>/propio <shapes-31-endpoints.json> <shapes-admins.json>
```

Límites de estos documentos:

- `dhcp_servers` y `snmp_sysinfo` figuran con campos desconocidos: la consulta
  falló en la captura por una ruta mal escrita, corregida después a
  `system.dhcp/server` y `system.snmp/sysinfo`. Falta repetir la captura.
- `vpn_ipsec` y `radius_servers` figuran con campos desconocidos: el equipo de
  laboratorio no tenía entradas en esas tablas.
- En `interfaces`, `local_users`, `log_fortianalyzer` y `fortiguard` la
  herramienta de diagnóstico omitió un nombre de clave por no tener forma de
  nombre de campo.
- Reflejan un solo equipo (FortiGate-VM) y una sola versión. Un campo que
  depende del modelo o de una función no habilitada puede faltar.

## 5. Documentos evaluados y excluidos

| Documento | Motivo |
|---|---|
| Disposición ONTI 1/2015 (Política de Seguridad de la Información Modelo) | Derogada por el artículo 9 de la DA 641/2021; cargarla induciría a error |
| Catálogo OSCAL de SP 800-53 Rev. 5 en JSON (10 MB) | Duplica el contenido de la planilla del catálogo y agrega ruido |
| «Summary of Changes» de SP 800-53 Release 5.2.0 (2 páginas) | No aporta contenido de consulta |
| Segunda copia de SP 800-41 Rev. 1 y de SP 800-53 Rev. 5 | Idénticas byte a byte a las que ya estaban en el bucket |
| Zip de la STIG, hojas de estilo, logotipos, memorando, presentación e historial | Se cargan solo los dos benchmarks convertidos |
| Referencia de CLI de FortiOS 7.6.8 completa | Se carga el extracto de la sección 4.1 |
| Cualquier documento que exija registro o pago | Fuera de alcance |

## 6. Fuentes pendientes por un paso manual

| Documento | Qué falta |
|---|---|
| CIS Fortinet FortiGate Benchmark 7.4.x v1.0.2 | Se descarga completando el formulario de <https://learn.cisecurity.org/benchmarks>. Licencia CC BY-NC-SA: uso no comercial con atribución. Es de la rama 7.4, no de la 7.6 del equipo |
| CCN-STIC-1406, «Procedimiento de empleo seguro Cortafuegos FortiGate» (CCN-CERT) | Descargar la guía y comprobar su aviso de licencia antes de cargarla |

## 7. Decisiones abiertas

- Transcribir a texto los anexos de la Resolución AAIP 47/2018 si la
  recuperación sobre el PDF de imágenes no resulta suficiente.
- Ajustar `expected_sources` de `audit-engine/evals/retrieval/questions.json`
  a los nombres reales de los documentos y grabar la evaluación de
  recuperación en vivo. Las subcadenas actuales (`hardening`,
  `cli-reference`, `administration-guide`, `cis`) no coinciden con las claves
  del corpus.

## 8. Cómo repetir la carga

Requiere credenciales de AWS y la autorización explícita del dueño del
repositorio (`AGENTS.md`, regla 10). Los identificadores salen de los
outputs del módulo `infrastructure/knowledge-base`.

```bash
# 1. Subir solo lo nuevo o modificado desde la copia local del corpus.
#    Sin --delete: nada se borra del bucket. La carpeta _herramientas/ guarda
#    scripts de generación y no se sube.
aws s3 sync <carpeta-del-corpus>/ "s3://<knowledge_bucket>/" --size-only   --exclude "_herramientas/*"

# 2. Iniciar la ingesta (no es automática) y esperar a COMPLETE
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id <knowledge_base_id> --data-source-id <data_source_id>
aws bedrock-agent get-ingestion-job \
  --knowledge-base-id <knowledge_base_id> --data-source-id <data_source_id> \
  --ingestion-job-id <ingestion_job_id> \
  --query "ingestionJob.[status,statistics,failureReasons]"

# 3. Comprobar la recuperación
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id <knowledge_base_id> \
  --retrieval-query '{"text": "minimum password length in the system password policy"}' \
  --retrieval-configuration '{"managedSearchConfiguration": {"numberOfResults": 5}}' \
  --query "retrievalResults[].[score,location.s3Location.uri]" --output text
```

La ingesta es incremental: indexa lo agregado o modificado y quita del índice
lo que ya no está en el bucket. No conviene borrar objetos ni detener un
trabajo mientras corre: el trabajo del 2026-11-18 se detuvo en esas
condiciones y dejó el índice desfasado (ver el resumen de trabajo).
