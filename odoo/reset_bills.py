# Removes the DRAFT vendor bills created by trimatch-bot, so the demo can be replayed.
# Posted bills are never touched. Runs inside the container through `odoo shell`:
#   docker compose -f odoo/docker-compose.yml run --rm odoo bash -c "odoo shell -d trimatch --no-http < /mnt/trimatch/odoo/reset_bills.py"

bot = env.ref("__trimatch__.user_bot")
bills = env["account.move"].search(
    [("move_type", "=", "in_invoice"), ("state", "=", "draft"), ("create_uid", "=", bot.id)]
)
names = [f"{b.id} ({b.ref or 'no ref'})" for b in bills]
attachments = env["ir.attachment"].search([("res_model", "=", "account.move"), ("res_id", "in", bills.ids)])
attachments.unlink()
bills.unlink()
env.cr.commit()
print(f"\nRemoved {len(names)} draft bill(s) made by trimatch-bot: {', '.join(names) or '-'}")
