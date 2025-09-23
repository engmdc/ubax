# models/dashboard_stats.py

from odoo import models, fields, api


class IdilDashboardStats(models.TransientModel):
    _name = "idil.dashboard.stats"
    _description = "IDIL Dashboard Statistics"

    total_sales = fields.Integer(string="Total Sales", readonly=True)
    total_purchases = fields.Integer(string="Total Purchases", readonly=True)
    total_customers = fields.Integer(string="Total Customers", readonly=True)

    @api.model
    def get_dashboard_stats(self):
        SaleOrder = self.env["idil.sale.order"]
        PurchaseOrder = self.env["idil.purchase_order"]
        Customer = self.env["idil.customer.registration"]
        return {
            "total_sales": SaleOrder.search_count([]),
            "total_purchases": PurchaseOrder.search_count([]),
            "total_customers": Customer.search_count([]),
        }

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        stats = self.get_dashboard_stats()
        res.update(stats)
        return res
