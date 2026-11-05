# Política de contraseñas y cuentas de usuario

Documento sintético para evaluación del pipeline (evals). No corresponde a
ninguna organización real ni reproduce un documento existente.

## 1. Objeto y alcance

1.1 Esta política define los requisitos de contraseñas y de gestión de cuentas para los administradores del firewall perimetral y para los usuarios locales definidos en el equipo.

1.2 Aplica a las cuentas de administración, a los usuarios locales utilizados para acceso remoto y a la configuración del portal SSL-VPN.

## 2. Longitud y complejidad

2.1 Las contraseñas deben tener una longitud mínima de doce (12) caracteres.

2.2 Las contraseñas deben combinar al menos tres de las siguientes cuatro categorías: letras mayúsculas, letras minúsculas, dígitos y símbolos.

2.3 No se permite reutilizar ninguna de las últimas cuatro (4) contraseñas.

## 3. Caducidad de contraseñas

3.1 Las contraseñas de las cuentas de administrador deben tener una fecha de caducidad configurada y renovarse al menos cada noventa (90) días.

3.2 Las cuentas de administrador creadas con contraseña inicial deben forzar el cambio de contraseña en el primer inicio de sesión.

## 4. Doble factor de autenticación

4.1 Todo usuario local habilitado para acceso remoto debe tener activado un segundo factor de autenticación (token FortiToken, correo electrónico o SMS).

4.2 No se admiten usuarios locales de acceso remoto autenticados únicamente con contraseña.

## 5. Cuentas inactivas

5.1 Las cuentas de usuario local deshabilitadas deben eliminarse del equipo dentro de los treinta (30) días posteriores a su deshabilitación.

5.2 No deben existir usuarios locales en estado deshabilitado de forma permanente.

## 6. Sesiones de acceso remoto

6.1 El portal SSL-VPN debe cerrar las sesiones inactivas tras un máximo de cinco (5) minutos sin actividad.

6.2 El tiempo máximo total de una sesión SSL-VPN no debe superar las ocho (8) horas.

## 7. Revisión de la política

7.1 Esta política se revisa anualmente por el área de Seguridad de la Información.
