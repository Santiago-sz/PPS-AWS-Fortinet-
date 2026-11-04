# Política de registro de eventos, sincronización horaria y resolución de nombres

Documento sintético para evaluación del pipeline (evals). No corresponde a
ninguna organización real ni reproduce un documento existente.

## 1. Objeto y alcance

1.1 Esta política define los requisitos de registro de eventos (logging), sincronización horaria y resolución de nombres del firewall perimetral FortiGate.

1.2 Aplica a la configuración global del equipo, a sus políticas de firewall y a sus servicios de red auxiliares.

## 2. Registro centralizado

2.1 El firewall debe enviar todos sus registros de eventos y de tráfico a la plataforma de registro centralizado de la organización (FortiAnalyzer o servidor syslog institucional).

2.2 El envío de registros debe utilizar un canal cifrado cuando la plataforma de destino lo soporte.

## 3. Registro de tráfico en las políticas de firewall

3.1 Toda política de firewall debe tener habilitado el registro de tráfico para todas las sesiones (registro de sesiones permitidas y denegadas), no solo para las violaciones de seguridad.

3.2 No se admiten políticas de firewall con el registro de tráfico deshabilitado, salvo excepción documentada y aprobada por Seguridad de la Información.

## 4. Sincronización horaria

4.1 El firewall debe sincronizar su reloj mediante NTP contra los servidores de hora institucionales.

4.2 La zona horaria configurada en el equipo debe corresponder a la zona horaria de Argentina (America/Argentina/Buenos_Aires), de modo que las marcas de tiempo de los registros sean comparables con el resto de la infraestructura.

## 5. Resolución de nombres

5.1 El firewall debe utilizar exclusivamente los servidores DNS internos de la organización, ubicados en el rango 10.0.0.0/8, como servidores DNS primario y secundario.

5.2 No se permite configurar resolutores DNS públicos de terceros en el equipo.

## 6. Identificación del equipo

6.1 El nombre de host del firewall debe seguir la convención institucional y comenzar con el prefijo FGT-.

## 7. Revisión de la política

7.1 Esta política se revisa anualmente o ante cambios en la plataforma de registro centralizado.
