#!/bin/bash
# Renders odoo/odoo.conf into $ODOO_RC with the master password, then hands over to the
# image's own entrypoint. Odoo can't read admin_passwd from the environment, and the
# password must not be committed. If ODOO_ADMIN_PASSWD is empty, a random one is used:
# the database manager is disabled (list_db = False), so nobody needs it.
set -e
passwd="${ODOO_ADMIN_PASSWD:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
sed "s|@ADMIN_PASSWD@|${passwd}|" /mnt/trimatch/odoo/odoo.conf > "$ODOO_RC"
exec /entrypoint.sh "$@"
