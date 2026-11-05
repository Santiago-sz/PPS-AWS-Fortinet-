# Política de acceso administrativo al firewall perimetral

Documento sintético para evaluación del pipeline (evals). No corresponde a
ninguna organización real ni reproduce un documento existente.

## 1. Objeto y alcance

1.1 Esta política establece los requisitos mínimos para el acceso administrativo al firewall perimetral FortiGate de la organización.

1.2 Aplica a todas las cuentas de administración locales del equipo, a los perfiles de acceso asociados y a las interfaces de red desde las cuales se permite la gestión.

## 2. Hosts de confianza

2.1 Toda cuenta de administrador debe tener configurados hosts de confianza (trusted hosts) que restrinjan el origen de las sesiones de administración a las redes de gestión autorizadas.

2.2 No se permiten cuentas de administrador sin restricción de origen, es decir, con hosts de confianza equivalentes a 0.0.0.0/0.

## 3. Bloqueo de administradores

3.1 Tras un máximo de tres (3) intentos fallidos consecutivos de autenticación, la cuenta de administrador debe bloquearse automáticamente.

3.2 La duración del bloqueo por intentos fallidos no debe ser inferior a trescientos (300) segundos.

## 4. Tiempo de inactividad

4.1 Las sesiones administrativas deben cerrarse automáticamente tras un máximo de diez (10) minutos de inactividad.

4.2 No se admite deshabilitar el cierre de sesión por inactividad en ninguna cuenta de administración.

## 5. Protocolos de administración

5.1 La administración del equipo debe realizarse exclusivamente mediante HTTPS; el acceso HTTP sin cifrar a la interfaz de administración debe estar deshabilitado o redirigido a HTTPS.

5.2 Ninguna interfaz de red debe permitir administración mediante HTTP ni Telnet.

## 6. Revisión de la política

6.1 Esta política se revisa al menos una vez al año o ante cambios significativos en la plataforma de seguridad perimetral.

6.2 El área de Seguridad de la Información es responsable de verificar su cumplimiento.
