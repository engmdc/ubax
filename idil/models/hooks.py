# hooks.py
def post_init_hook(cr, registry):
    from odoo.api import Environment

    env = Environment(cr, SUPERUSER_ID, {})
    env["idil.dashboard.metric"].refresh_dashboard()
